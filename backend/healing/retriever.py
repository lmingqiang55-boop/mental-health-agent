"""Chinese BM25, pre-filtered metadata and optional BGE/RRF comparison.

Reference: LlamaIndex BM25Retriever metadata filtering; FlagEmbedding BGE CLS
embeddings; EmoLLM's retrieval -> generation separation. No upstream code copied.
"""

import math
import re
from collections import Counter
from functools import lru_cache

import jieba
from rank_bm25 import BM25Okapi

from backend.healing.knowledge import load_knowledge
from backend.models.healing import HealingBackground, KnowledgeHit, KnowledgeItem, Scene

jieba.setLogLevel(40)
STOPWORDS = {"的", "了", "是", "我", "你", "和", "在", "就", "都", "有", "很", "也", "不", "想", "最近"}


def tokenize(text: str) -> list[str]:
    return [word for word in jieba.lcut(text.lower()) if word.strip() and word not in STOPWORDS
            and re.search(r"[\w\u4e00-\u9fff]", word)]


def retrieval_query(query: str, scene: Scene) -> str:
    # A small, explicit synonym bridge for disagreement. It only affects
    # ranking after the original suitability filters, never steps or scope.
    if scene == "relationships" and re.search(
            r"意见(?:不一致|不同|不一样)|观点(?:不同|不一致)|(?:意见|观点)分歧", query):
        return query + " 分歧 冲突 表达 感受"
    return query


def age_match(item: KnowledgeItem, background: HealingBackground) -> str | None:
    age, stage = background.age, background.school_stage
    if age is None and stage is None:
        return None
    if item.age_min is not None or item.age_max is not None:
        if age is None:
            return None  # A school stage cannot stand in for an exact numerical range.
        if (item.age_min is not None and age < item.age_min or
                item.age_max is not None and age > item.age_max):
            return None
    if item.school_stages and (stage is None or stage not in item.school_stages):
        return None
    if item.audience == "unspecified":
        return None
    if item.audience == "adolescents" and not item.school_stages:
        if age is None or age < 13:
            return None  # Do not extend a broad teen label to all middle-school ages.
    if item.audience == "children" and not item.school_stages:
        if (age is None and stage != "primary") or (age is not None and age > 12):
            return None
    return "explicit_age_or_stage; source_audience_preserved"


class HealingRetriever:
    def __init__(self, items: list[KnowledgeItem] | None = None, encoder=None):
        self.items = items if items is not None else load_knowledge()
        self.encoder = encoder

    def retrieve_explanations(self, query: str, scene: Scene, background: HealingBackground,
                              top_k: int = 2) -> list[KnowledgeItem]:
        """Background prose only; never returns steps or executable adult tasks."""
        tokens = tokenize(query)
        candidates = [item for item in self.items if item.status == "explanation_only"
                      and item.semantic_checked and not item.validation_issues
                      and (item.purpose == "explanation" or item.purpose == "method" and item.executor == "adult")
                      and scene in item.scenes and age_match(item, background) is not None]
        ranked = sorted(candidates, key=lambda item: -sum(token in item.title + item.goal for token in tokens))
        return [item for item in ranked if any(token in item.title + item.goal for token in tokens)][:top_k]

    def retrieve(self, query: str, scene: Scene, background: HealingBackground,
                 excluded_methods: set[str] | None = None, top_k: int | None = 4,
                 mode: str = "bm25") -> list[KnowledgeHit]:
        # None exposes the same complete ranking for bounded context-filter
        # batches; defaults and callers requesting a fixed top-k stay unchanged.
        if (top_k is not None and top_k <= 0) or scene == "general":
            return []
        excluded = excluded_methods or set()
        candidates = []
        for item in self.items:
            if (item.status != "usable" or not item.semantic_checked or item.validation_issues
                    or item.purpose != "method" or item.executor not in {"student", "adult_guided"}
                    or scene not in item.scenes or item.method_key in excluded):
                continue
            matched = age_match(item, background)
            if matched is None or item.executor == "adult_guided" and background.adult_support_available is False:
                continue
            candidates.append((item, matched))
        if not candidates:
            return []
        texts = [" ".join([item.title, item.goal, *item.steps, *item.keywords]) for item, _ in candidates]
        corpus = [tokenize(text) for text in texts]
        query = retrieval_query(query, scene)
        query_tokens = tokenize(query)
        # BM25 IDF can be zero/negative in tiny filtered corpora. Positive IDF
        # preserves useful ranking rather than treating a one-entry KB as no-hit.
        bm25 = BM25Okapi(corpus)
        counts = Counter(token for row in corpus for token in set(row))
        bm25.idf = {word: math.log(1 + (len(corpus) - count + .5) / (count + .5))
                    for word, count in counts.items()}
        lexical = list(map(float, bm25.get_scores(query_tokens)))
        if mode == "keyword":
            lexical = [float(sum(word in text for word in query_tokens)) for text in texts]
        scores = lexical
        if mode in {"vector", "hybrid"}:
            if self.encoder is None:
                raise RuntimeError("向量检索未配置编码器")
            vectors = self.encoder([query, *texts])
            semantic = [float(sum(a*b for a, b in zip(vectors[0], vector))) for vector in vectors[1:]]
            if mode == "vector":
                scores = [score if score >= .5 else 0 for score in semantic]
            else:
                scores = [0.] * len(candidates)
                for values in (lexical, semantic):
                    for rank, idx in enumerate(sorted(range(len(values)), key=lambda i: values[i], reverse=True)):
                        if values[idx] > (0 if values is lexical else .5):
                            scores[idx] += 1 / (60 + rank + 1)
        elif mode not in {"keyword", "bm25"}:
            raise ValueError("未知检索方式")
        ranked = sorted(range(len(candidates)), key=lambda i: (-scores[i], candidates[i][0].knowledge_id))
        result, methods = [], set()
        for idx in ranked:
            item, matched = candidates[idx]
            if scores[idx] <= 0 or item.method_key in methods:
                continue
            methods.add(item.method_key)
            result.append(KnowledgeHit(item=item, score=scores[idx], age_match=matched,
                                       scene_match=scene, risk_limits=item.exclusions))
            if top_k is not None and len(result) >= top_k:
                break
        return result


@lru_cache(maxsize=1)
def get_healing_retriever() -> HealingRetriever:
    return HealingRetriever()
