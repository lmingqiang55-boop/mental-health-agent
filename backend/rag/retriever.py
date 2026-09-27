"""知识检索。

框架阶段使用本地 Markdown + 关键词匹配，启动时加载并缓存。
接入向量检索时保持 ``retrieve(query, top_k)`` 接口不变。
"""

from abc import ABC, abstractmethod
from pathlib import Path

KNOWLEDGE_PATH = Path(__file__).parent / "knowledge" / "demo_knowledge.md"

KEYWORDS = {
    "情绪状态": ("心情", "情绪", "低落", "难过", "mood"),
    "压力状态": ("压力", "焦虑", "紧张", "pressure"),
    "人际关系": ("人际", "同学", "朋友", "家人", "关系"),
    "自我认知": ("自我", "否定", "自卑", "没用", "认知"),
    "学习生活": ("学习", "生活", "精力", "疲惫", "睡眠"),
    "症状持续时间": ("多久", "持续", "开始", "duration"),
}


class Retriever(ABC):
    @abstractmethod
    def retrieve(self, query: str, top_k: int = 3) -> list[str]:
        """返回与 query 相关的知识片段。"""


class KeywordRetriever(Retriever):
    """本地 Markdown 关键词检索，模块级缓存避免每次读文件。"""

    def __init__(self, path: Path = KNOWLEDGE_PATH) -> None:
        self._sections: list[tuple[str, str]] = []
        self._load(path)

    def _load(self, path: Path) -> None:
        raw = path.read_text(encoding="utf-8").split("\n## ")[1:]
        for section in raw:
            title = section.splitlines()[0].strip()
            self._sections.append((title, section.strip()))

    def retrieve(self, query: str, top_k: int = 3) -> list[str]:
        if top_k <= 0:
            return []
        normalized = query.lower()
        ranked: list[tuple[int, str]] = []
        for title, body in self._sections:
            score = sum(normalized.count(word.lower())
                        for word in KEYWORDS.get(title, ()))
            if score:
                ranked.append((score, body))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [body for _, body in ranked[:top_k]]


_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = KeywordRetriever()
    return _retriever


def retrieve(query: str, top_k: int = 3) -> list[str]:
    """模块级便捷函数，保持旧接口兼容。"""
    return get_retriever().retrieve(query, top_k)
