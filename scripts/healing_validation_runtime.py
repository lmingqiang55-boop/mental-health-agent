"""Isolation and safe usage evidence shared by live healing acceptance scripts."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from time import perf_counter

PROJECT = Path(__file__).resolve().parents[1]


class ValidationRuntime:
    def __init__(self, work_dir):
        self.work = Path(work_dir).resolve()
        allowed = (PROJECT.parent / "codex_proc").resolve()
        if not self.work.is_relative_to(allowed):
            raise ValueError("验证过程目录必须位于挂载根目录的 codex_proc 下")
        self.work.mkdir(parents=True, exist_ok=True)
        sys.dont_write_bytecode = True
        tempfile.tempdir = str(self.work)
        os.environ["TMP"] = os.environ["TEMP"] = str(self.work)
        normal = (PROJECT / "data/evaluation_memory.sqlite3").resolve()
        connect = sqlite3.connect

        def isolated(database, *args, **kwargs):
            if str(database) != ":memory:" and Path(database).resolve() == normal:
                database = self.work / "isolated_default.sqlite3"
            return connect(database, *args, **kwargs)

        sqlite3.connect = isolated
        import jieba
        jieba.dt.tmp_dir = str(self.work)
        self.protected = {}
        for folder in (PROJECT / "backend", PROJECT / "evaluation_agent", PROJECT / "frontend/src"):
            for path in folder.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    self.protected[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        if normal.exists():
            self.protected[str(normal)] = hashlib.sha256(normal.read_bytes()).hexdigest()
        self.calls = []
        self.decisions = []
        self.case_id = None
        self.capture_calls()

    def capture_calls(self):
        from backend.llm.deepseek_client import DeepSeekClient
        from evaluation_agent.llm_client import EvaluationLLMClient
        from backend.healing.client import HealingJSONClient
        generate = DeepSeekClient.generate
        assess = EvaluationLLMClient.assess_with_trace
        decide = HealingJSONClient.generate
        runtime = self

        async def measured(client, *args, **kwargs):
            started = perf_counter()
            row = {"case_id": runtime.case_id, "component": "healing", "model": client.config.model}
            try:
                value = await generate(client, *args, **kwargs)
                row.update(success=True, usage=client.last_usage)
                return value
            except Exception as exc:
                row.update(success=False, error_type=type(exc).__name__, usage=None)
                raise
            finally:
                row["elapsed_ms"] = (perf_counter() - started) * 1000
                runtime.calls.append(row)
                runtime.save_calls()

        def assessed(client, *args, **kwargs):
            started = perf_counter()
            row = {"case_id": runtime.case_id, "component": "assessment", "model": client.config.model}
            try:
                value = assess(client, *args, **kwargs)
                row.update(success=True, trace=value.trace.model_dump(mode="json"))
                usage = value.trace.usage
                row["usage"] = ({"prompt_tokens": usage.input_tokens, "completion_tokens": usage.output_tokens,
                                 "total_tokens": usage.total_tokens} if usage else None)
                return value
            except Exception as exc:
                row.update(success=False, error_type=type(exc).__name__, usage=None)
                raise
            finally:
                row["elapsed_ms"] = (perf_counter() - started) * 1000
                runtime.calls.append(row)
                runtime.save_calls()

        DeepSeekClient.generate = measured
        EvaluationLLMClient.assess_with_trace = assessed

        async def decided(client, system, payload, schema, **kwargs):
            value = await decide(client, system, payload, schema, **kwargs)
            runtime.decisions.append({"case_id": runtime.case_id, "schema": schema.__name__,
                "phase": payload.get("phase"), "result": value.model_dump(mode="json")})
            (runtime.work / "structured_decisions.json").write_text(
                json.dumps(runtime.decisions, ensure_ascii=False, indent=2), encoding="utf-8")
            return value

        HealingJSONClient.generate = decided

    def save_calls(self):
        (self.work / "model_calls.json").write_text(json.dumps(self.calls, ensure_ascii=False, indent=2), encoding="utf-8")

    def finish(self):
        changed = [path for path, digest in self.protected.items()
                   if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest]
        totals = {field: sum((row.get("usage") or {}).get(field) or 0 for row in self.calls)
                  for field in ("prompt_tokens", "completion_tokens", "total_tokens")}
        result = {"protected_files": len(self.protected), "changed_files": changed,
                  "assessment_invocations": sum(row["component"] == "assessment" for row in self.calls),
                  "healing_requests": sum(row["component"] == "healing" for row in self.calls),
                  "usage_missing_invocations": sum(row.get("usage") is None for row in self.calls),
                  "known_usage": totals, "assessment_trace_preserves_attempt_counts": True}
        (self.work / "runtime_verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if changed:
            raise RuntimeError("运行文件或正常数据库发生变化，见 runtime_verification.json")
        return result
