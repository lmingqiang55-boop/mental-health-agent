from pathlib import Path


KNOWLEDGE_PATH = Path(__file__).parent / "knowledge" / "demo_knowledge.md"
KEYWORDS = {
    "情绪低落": ("心情", "情绪", "低落", "难过", "mood"),
    "兴趣减退": ("兴趣", "喜欢", "interest"),
    "睡眠变化": ("睡", "失眠", "sleep"),
    "精力变化": ("精力", "没精神", "疲惫", "energy"),
    "注意力变化": ("注意力", "专注", "集中", "concentration"),
    "症状持续时间": ("多久", "持续", "开始", "duration"),
}


def retrieve(query: str, top_k: int = 3) -> list[str]:
    if top_k <= 0:
        return []
    sections = KNOWLEDGE_PATH.read_text(encoding="utf-8").split("\n## ")[1:]
    ranked: list[tuple[int, str]] = []
    normalized = query.lower()
    for section in sections:
        title = section.splitlines()[0].strip()
        score = sum(normalized.count(word.lower()) for word in KEYWORDS.get(title, ()))
        if score:
            ranked.append((score, section.strip()))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [section for _, section in ranked[:top_k]]
