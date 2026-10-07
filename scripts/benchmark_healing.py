"""Compare retrieval on fixed synthetic cases, plus optional upstream prototypes.

Research packages are optional: --research-deps can point to an isolated pip
target. They are not added to the running backend's environment or dependency set.
"""

import argparse
import json
import platform
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class BGEEncoder:
    def __init__(self, cache_dir):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        model = "BAAI/bge-small-zh-v1.5"
        self.tokenizer = AutoTokenizer.from_pretrained(model, cache_dir=str(cache_dir))
        self.model = AutoModel.from_pretrained(model, cache_dir=str(cache_dir))
        self.model.eval()

    def __call__(self, texts):
        batch = self.tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt")
        with self.torch.no_grad():
            embeddings = self.model(**batch).last_hidden_state[:, 0]
        embeddings = self.torch.nn.functional.normalize(embeddings, p=2, dim=1)
        return embeddings.cpu().tolist()


class BGEReranker:
    """FlagEmbedding's documented cross-encoder recipe, via existing Transformers."""
    def __init__(self, cache_dir):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        model = "BAAI/bge-reranker-base"
        self.tokenizer = AutoTokenizer.from_pretrained(model, cache_dir=str(cache_dir))
        self.model = AutoModelForSequenceClassification.from_pretrained(model, cache_dir=str(cache_dir))
        self.model.to(self.device).eval()

    def rank(self, query, hits):
        if not hits:
            return []
        pairs = [[query, " ".join([hit.item.title, hit.item.goal, *hit.item.steps])] for hit in hits]
        inputs = self.tokenizer(pairs, padding=True, truncation=True, max_length=512, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            scores = self.model(**inputs).logits.view(-1).float().cpu().tolist()
        return [hits[idx] for idx in sorted(range(len(hits)), key=lambda idx: -scores[idx])]


def main(args):
    if args.research_deps:
        sys.path.insert(0, str(args.research_deps.resolve()))
    from backend.healing.knowledge import load_knowledge
    from backend.healing.retriever import HealingRetriever, age_match, tokenize
    from backend.llm.config import load_deepseek_config
    from backend.models.healing import HealingBackground
    from importlib.metadata import version
    args.work_dir.mkdir(parents=True, exist_ok=True)
    loaded_at = perf_counter()
    items = load_knowledge()
    knowledge_load_ms = (perf_counter()-loaded_at)*1000
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    result = {"cases": [], "upstream": {}, "versions": {"rank-bm25": version("rank-bm25"), "jieba": version("jieba")}}
    result["knowledge_load_ms"] = knowledge_load_ms
    result["environment"] = {"python": platform.python_version(), "system": platform.system(),
                             "machine": platform.machine(), "knowledge_items": len(items)}
    started = perf_counter()
    retriever = HealingRetriever(items)
    result["retriever_init_ms"] = (perf_counter()-started)*1000
    if args.vector:
        started = perf_counter()
        try:
            retriever.encoder = BGEEncoder(args.model_cache or args.work_dir / "models")
            result["vector_load_ms"] = (perf_counter()-started)*1000
        except Exception as exc:
            result["vector_error"] = type(exc).__name__
    modes = ["keyword", "bm25"] + (["vector", "hybrid"] if retriever.encoder else [])
    llama_bm25 = None
    if args.research_deps:
        try:
            from llama_index.core.schema import TextNode
            from llama_index.retrievers.bm25 import BM25Retriever
            def llama_bm25(query, scene, background, excluded):
                # Apply the project's exact hard eligibility before handing nodes
                # to the optional framework. No framework may waive these limits.
                eligible = [item for item in items if item.status == "usable" and item.semantic_checked
                    and not item.validation_issues and item.purpose == "method"
                    and item.executor in {"student", "adult_guided"} and scene in item.scenes and item.method_key not in excluded
                    and age_match(item, background) is not None
                    and not (item.executor == "adult_guided" and background.adult_support_available is False)]
                if not eligible:
                    return []
                by_id = {item.knowledge_id: item for item in eligible}
                nodes = [TextNode(id_=item.knowledge_id, text=" ".join(tokenize(" ".join(
                    [item.title, item.goal, *item.steps, *item.keywords])))) for item in eligible]
                prototype = BM25Retriever.from_defaults(nodes=nodes, skip_stemming=True, language="zh",
                    token_pattern=r"(?u)\b\w+\b", similarity_top_k=min(len(nodes), 4))
                found = prototype.retrieve(" ".join(tokenize(query)))
                selected, keys = [], set()
                for node in found:
                    key = by_id[node.node.node_id].method_key
                    if node.score > 0 and key not in keys:
                        keys.add(key)
                        selected.append(by_id[node.node.node_id])
                return selected[:2] if scene != "general" else []
            modes.append("llama_index_bm25")
        except ImportError as exc:
            result["llama_index_case_error"] = type(exc).__name__
    reranker = None
    if args.rerank:
        started = perf_counter()
        try:
            reranker = BGEReranker(args.model_cache or args.work_dir / "models")
            result["reranker_load_ms"] = (perf_counter()-started)*1000
            result["reranker_device"] = reranker.device
            result["environment"]["torch"] = version("torch")
            result["environment"]["transformers"] = version("transformers")
            result["environment"]["accelerator"] = (reranker.torch.cuda.get_device_name(0)
                if reranker.device == "cuda" else "CPU")
            modes.append("bm25_rerank")
        except Exception as exc:
            result["reranker_error"] = type(exc).__name__
    from statistics import median
    repetitions = max(1, args.repetitions)
    for case in cases:
        background = HealingBackground(**case["background"])
        row = {**case, "results": {}}
        excluded = set(case.get("excluded_methods", []))
        for mode in modes:
            elapsed = []
            for repetition in range(repetitions):
                started = perf_counter()
                if mode == "llama_index_bm25":
                    selected = llama_bm25(case["query"], case["scene"], background, excluded)
                elif mode == "bm25_rerank":
                    recalled = retriever.retrieve(case["query"], case["scene"], background, excluded, mode="bm25", top_k=8)
                    hits = reranker.rank(case["query"], recalled)[:2]
                    selected = [hit.item for hit in hits]
                else:
                    hits = retriever.retrieve(case["query"], case["scene"], background, excluded, mode=mode, top_k=2)
                    selected = [hit.item for hit in hits]
                elapsed.append((perf_counter()-started)*1000)
            keys = [item.method_key for item in selected]
            expected = set(case["expected_methods"])
            correct = bool(expected.intersection(keys)) if expected else not keys
            safe = all(item.status == "usable" and item.semantic_checked and not item.validation_issues
                and item.purpose == "method" and item.executor in {"student", "adult_guided"}
                and case["scene"] in item.scenes and age_match(item, background) is not None
                and item.method_key not in excluded
                and not (item.executor == "adult_guided" and background.adult_support_available is False)
                for item in selected) and len(keys) == len(set(keys))
            reciprocal = next((1 / (index + 1) for index, key in enumerate(keys) if key in expected), 0.)
            row["results"][mode] = {"methods": keys, "knowledge_ids": [item.knowledge_id for item in selected],
                                     "correct": correct, "hard_filters_passed": safe, "reciprocal_rank_at_2": reciprocal,
                                     "cold_query_ms": elapsed[0], "warm_median_ms": median(elapsed[1:]) if repetitions > 1 else None,
                                     "elapsed_ms": median(elapsed), "repetitions": repetitions}
        result["cases"].append(row)

    if args.research_deps and not getattr(args, "retrieval_only", False):
        try:
            from llama_index.core.schema import TextNode
            from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
            from llama_index.retrievers.bm25 import BM25Retriever
            nodes = [TextNode(id_=item.knowledge_id, text=" ".join(tokenize(item.title + " " + item.goal)),
                              metadata={"status": item.status}) for item in items]
            prototype = BM25Retriever.from_defaults(nodes=nodes, skip_stemming=True,
                language="zh", token_pattern=r"(?u)\b\w+\b", similarity_top_k=2,
                filters=MetadataFilters(filters=[MetadataFilter(key="status", value="usable")]))
            found = prototype.retrieve(" ".join(tokenize("考试压力")))
            result["upstream"]["llama_index"] = {"version": version("llama-index-retrievers-bm25"),
                "hits": [node.node.node_id for node in found], "metadata_filter_passed": all(node.node.metadata["status"] == "usable" for node in found)}
        except Exception as exc:
            result["upstream"]["llama_index"] = {"error": type(exc).__name__}
        try:
            import langextract as lx
            from langextract.factory import ModelConfig
            config = load_deepseek_config()
            text = "儿童青少年在成人指导下，把令自己紧张的事情说具体。"
            examples = [lx.data.ExampleData(text="学生在成人陪伴下说出担心。", extractions=[
                lx.data.Extraction(extraction_class="support_method", extraction_text="学生在成人陪伴下说出担心。",
                                   attributes={"executor": "adult_guided", "prerequisite": "成人陪伴"})])]
            started = perf_counter()
            extracted = lx.extract(text_or_documents=text, prompt_description=
                "提取完整支持方法，逐字引用原文方法，保留执行者和成人指导条件，不扩大适用对象。",
                examples=examples, config=ModelConfig(model_id=config.model, provider="openai",
                    provider_kwargs={"api_key": config.api_key, "base_url": config.base_url}),
                use_schema_constraints=False, max_char_buffer=1500,
                language_model_params={"max_output_tokens": 1200}, show_progress=False)
            result["upstream"]["langextract"] = {"version": version("langextract"),
                "elapsed_ms": (perf_counter()-started)*1000,
                "extractions": [{"class": item.extraction_class, "text": item.extraction_text,
                                 "attributes": item.attributes, "interval": (
                                     {"start": item.char_interval.start_pos, "end": item.char_interval.end_pos}
                                     if item.char_interval else None)} for item in extracted.extractions]}
        except Exception as exc:
            result["upstream"]["langextract"] = {"error": type(exc).__name__}
    result["summary"] = {mode: {"correct": sum(row["results"][mode]["correct"] for row in result["cases"]),
                               "total": len(cases),
                               "positive_hits": sum(row["results"][mode]["correct"] for row in result["cases"] if row["expected_methods"]),
                               "positive_total": sum(bool(row["expected_methods"]) for row in result["cases"]),
                               "negative_correct": sum(row["results"][mode]["correct"] for row in result["cases"] if not row["expected_methods"]),
                               "negative_total": sum(not row["expected_methods"] for row in result["cases"]),
                               "hard_filter_violations": sum(not row["results"][mode]["hard_filters_passed"] for row in result["cases"]),
                               "mrr_at_2_positive": sum(row["results"][mode]["reciprocal_rank_at_2"] for row in result["cases"] if row["expected_methods"]) / max(1, sum(bool(row["expected_methods"]) for row in result["cases"])),
                               "median_ms": median(row["results"][mode]["elapsed_ms"] for row in result["cases"])} for mode in modes}
    (args.work_dir / "retrieval_benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": result["summary"], "upstream": result["upstream"],
                      "vector_error": result.get("vector_error")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path("tests/fixtures/healing_retrieval_cases.json"))
    parser.add_argument("--research-deps", type=Path)
    parser.add_argument("--retrieval-only", action="store_true", help="Skip the separate extraction/model probe")
    parser.add_argument("--vector", action="store_true")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--model-cache", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    main(parser.parse_args())
