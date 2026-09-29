"""OpenAI-compatible JSON extractor. Its output is untrusted until engine validation."""
import json

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.assessment.bank import ITEMS
from backend.assessment.extractor import EvidenceCandidate, ExtractionUnavailable
from backend.assessment.models import Category


class _CandidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    quote: str
    period: str
    category: Category | None


class _ExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[_CandidatePayload] = Field(max_length=12)


_ITEMS = "\n".join(f"{item.item_id}: {item.label}; 线索: {', '.join(item.clues)}" for item in ITEMS)
_SYSTEM = (
    "你是测评对话的证据定位器。只抽取用户本轮原话，不诊断、不打分、不生成下一问。"
    "返回严格的 JSON 对象，如 "
    '{"candidates":[{"item_id":"item_01","quote":"用户原文中的连续片段",'
    '"period":"unknown","category":null}]}。'
    "period 只能是 past_14_days、other、unknown；category 只能是 "
    "not_at_all、several_days、more_than_half_days、nearly_every_day 或 JSON null。"
    "每条 quote 必须是原文逐字连续片段。"
    "只有用户明确选择四档频率才填写 category；'经常'、'偶尔'或具体天数填 null。"
    "只有明确说过去两周才填写 past_14_days；说去年等填 other，其余填 unknown。"
    "不要把第三人称、假设句、否定的自伤意图当作用户已有症状。"
    "一段话可返回多条候选；没有证据返回空数组。条目定义：\n" + _ITEMS
)


class OpenAICompatibleExtractor:
    """Calls a cloud or local OpenAI-compatible chat completions endpoint."""

    def __init__(
        self, base_url: str, model: str, api_key: str = "", *,
        thinking_mode: str = "default",
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip() or not model.strip():
            raise ValueError("ASSESSMENT_LLM_BASE_URL and ASSESSMENT_LLM_MODEL are required")
        if thinking_mode not in {"default", "enabled", "disabled"}:
            raise ValueError("ASSESSMENT_LLM_THINKING must be default, enabled, or disabled")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.thinking_mode = thinking_mode
        self.client = client or httpx.Client(timeout=20.0)
        self.version = f"openai_compatible_json_v1:{model}"

    def extract(self, text: str, target_item_id: str | None) -> list[EvidenceCandidate]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps({
                    "current_item_id": target_item_id,
                    "user_text": text,
                }, ensure_ascii=False)},
            ],
        }
        if self.thinking_mode != "default":
            payload["thinking"] = {"type": self.thinking_mode}
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=payload,
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("truncated model output")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("message content is not a string")
            parsed = _ExtractionPayload.model_validate_json(content)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            raise ExtractionUnavailable("Structured extraction failed") from exc
        return [EvidenceCandidate(c.item_id, c.quote, c.period, c.category)
                for c in parsed.candidates]
