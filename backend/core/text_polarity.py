"""把一句中文自述映射成 [-1, 1] 的极性，供多模态一致性比对使用。

来源与依据
----------
词典用 ``cnsenti``（MIT，见 ``requirements.txt``）：它把知网 HowNet 的正 / 负情感
词典连同**否定词与程度副词**一起打包，``Sentiment.sentiment_calculate`` 已经实现
了中文口语里最容易踩坑的那条规则——情感词前有奇数个否定词就翻转极性
（实测 ``"不开心"`` → ``pos=-1``），程度副词按 4 / 3 / 2 / 0.5 加权。自己重写一份
词典既没有出处，也不如它经得起追问。

它不做的三件事由本模块补上：

1. **判断"这句话到底有没有情绪词"**。``sentiment_calculate`` 返回的 ``words``
   是 jieba 分词总数而不是命中数（"今天挺好的"与"没什么好说的"都返回 4），
   只看它无法知道句子里有没有情感词。
2. **纯否定词不算情绪词**。HowNet 的否定词表与负向词表重叠，"没有""没事"
   这类回答会被算成负分（实测 ``"没事"`` → ``neg=1``），可它只是在否认，
   本身不带情绪。本模块按 jieba 分词逐个查表，跳过纯否定词。
3. **程度副词与情感词重叠时按副词算**。两张表有 19 个词重叠（"特别" ∈ Poss
   且 ∈ Verys 等），``sentiment_calculate`` 先判情感词，会把整句方向算反：
   实测 ``"我今天特别难过"`` → ``pos=2, neg=1``（应为 -3），而语义相同的
   ``"我最近很难过"`` → ``neg=3`` 是对的。权重与窗口规则照抄它的实现，
   详见 :func:`_hownet_polarity`。

另外补一处分词粘连：jieba 会把程度副词与情绪词合成一个未登录词
（实测 ``jieba.lcut("非常高兴")`` → ``["非常高兴"]``），整句因此读不出情绪。
:func:`_split_off_adverb` 只在"切出来的后半段确实是词表里的情绪词"时才切开，
所以它只是把分词还原，不引入任何自造的极性。

兜底用大连理工七类情感本体（``cnsenti.Emotion``）：两套词典的重合度很高
（实测 30 个常见情绪词里 22 个同时在两套里），本体独有的如"迷茫"在知网得 0 分，
所以本体只用来**定方向**，强度仍由知网给。

为什么还要一张口语补充词表
--------------------------
知网与大连理工两套词典**只收双字及以上的词**：实测"累""烦""困""闷""慌""怕""好"
在两套词典里都不存在（知网正表里唯一的单字是"雩"，负表里是"烂"）。于是最口语、
也是学生最常说的"我最近很累""有点烦""心里挺闷的"全都读不出极性，
:func:`text_polarity` 返回 ``None``——一致性分数于是经常显示"没得比"，
"说话和表情反着来"的那条通道也永远不触发。

所以本模块自带两张**人工整理的**口语词表（:data:`COLLOQUIAL_NEGATIVE` 与
:data:`COLLOQUIAL_POSITIVE`），只补单字词和两套词典漏收的高频口语说法：

- **只补词，不改权重规则**：一条口语词的基准权重与知网的一条普通情感词一样是
  1.0（"还好""还行"这类语气暧昧的给 0.5），程度副词、否定翻转、扫描窗口
  三套规则完全共用。这样两条来源的分数仍在一个量纲上，可以相加。
- **选词参考了 BosonNLP 微博情感词典**（114767 词、其中 8671 个单字）作为
  "哪些口语说法确实常用"的对照清单。**它的许可禁止再分发、且商用需付费**
  （见其 license：禁止提供给第三方使用；全集或子集用于商业目的需付费；
  研究"不得针对特定人"），因此仓库里**不放它的任何文件、也不抄它的分值**——
  只借它确认覆盖面，权重由本模块自己定。
- **它仍然是启发式**：没有权威出处，量级是拍的。它的作用是把"读不出"变成
  "读出偏负/偏正"，不是给出精确强度。要校准请拿真实样本按分位数来。

仍然存在的盲区：反讽、比喻、以及"我以为我没事"这类转折句一律读不出；
"还好""还行"本身语气暧昧，本模块按**弱正向**处理——这正是"嘴上说还行、脸色
不好"能被抓到的前提，但反过来也会把真心平气和说成弱正向。拿不准时返回 ``None``。

否认句式也按词典原样处理，不做特判：``"没有"`` 因为同时是否定词（否定词表与负向
词表重叠）而返回 ``None``；但 ``"没事"`` 在大连理工本体里被当成一个负向词，实测
会读成 ``-0.32``。于是"嘴上说没有烦心事、脸上却难过"这种最典型的矛盾信号会被
漏掉——这是一个待产品/伦理拍板的取舍，不是疏忽：要让"没有"也进入比对，
需要先在规则集里单独定义否认语境下的极性（例如"没有 + 情绪词"才计负分），
而不是把整个否定词表当成负向词。

**本函数不是语义理解**：它看不见反讽、读不出上下文，拿不准时返回 ``None``，
由调用方把这一句排除在统计之外，而不是塞一个 0 假装"中性"。
"""

from __future__ import annotations

import math
from functools import lru_cache

from backend.core.text_signals import predicate_is_negated


POLARITY_SCALE = 3.0
"""知网加权分压到 [-1, 1] 的尺度：3 分约等于一次明确表态（实测"我很难过"= 3）。"""

LEAN_SCALE = 1.5
"""本体命中数压到 [-1, 1] 的尺度：1.5 约等于一次明确表态。"""

ADVERB_WEIGHT_SOURCES = (
    ("Extremes", 4.0), ("Verys", 3.0), ("Mores", 2.0), ("Ishs", 0.5),
)
"""程度副词的档位与权重，取自 ``cnsenti/sentiment.py`` 的 ``sentiment_calculate``。"""

POSITIVE_CATEGORIES = ("Haos", "Les")
NEGATIVE_CATEGORIES = ("Ais", "Nus", "Jus", "Wus")
"""本体七类里定方向的正向 / 负向；"惊"（``Jings``）不计方向。"""

COLLOQUIAL_NEGATIVE: dict[str, float] = {
    # 单字（两套词典一个都不收，实测"累/烦/困/闷/慌/怕"全不在表里）
    "累": 1.0, "烦": 1.0, "闷": 1.0, "慌": 1.0, "怕": 1.0, "苦": 1.0,
    "惨": 1.0, "憋": 1.0, "崩": 1.0, "痛": 1.0, "沉": 1.0,
    "困": 0.5, "愁": 0.5, "丧": 0.5, "坏": 0.5, "躁": 0.5, "堵": 0.5,
    "虚": 0.5, "差": 0.5, "骗": 0.5,
    # 两套词典漏收的高频口语说法（jieba 实际切出来的形态）
    "提不起": 1.0, "提不起劲": 1.0, "心累": 1.0, "想哭": 1.0, "撑不住": 1.0,
    "撑不下去": 1.0, "打不起精神": 1.0, "打不起劲": 1.0, "没精神": 1.0,
    "浑身没劲": 1.0, "浑身无力": 1.0, "懒得动": 1.0, "心慌": 1.0,
    "心里堵": 1.0, "烦死": 1.0, "烦透了": 1.0, "心情不好": 1.0, "心情差": 1.0,
    "情绪低落": 1.0, "睡不好": 1.0,
    "睡不好觉": 1.0, "提不起兴趣": 1.0, "喘不过气": 1.0, "想不开": 1.0,
    "不想动": 0.5, "不想说话": 0.5, "走神": 0.5, "心不在焉": 0.5,
    "想不通": 0.5, "犯困": 0.5, "不想": 0.5, "懒得": 0.5,
}
r"""口语负向词 → 基准权重；1.0 与知网的一条普通情感词等价，0.5 表示语气弱。

注意**不要**把 ``好烦``\ ``好困``\ ``好累`` 这类"程度副词＋情绪词"整词写进来：
写进来就会挡住 :func:`_split_off_adverb` 的切分，把本该由"好"加强的语气
（``好烦`` 应比 ``烦`` 更重）压平成一个普通词。
"""

COLLOQUIAL_POSITIVE: dict[str, float] = {
    "好": 1.0, "爽": 1.0, "棒": 1.0, "赞": 1.0,
    "挺好的": 1.0, "还不错": 1.0, "挺不错": 1.0, "有劲": 1.0,
    "有精神": 1.0, "精神好": 1.0, "睡得好": 1.0, "吃得香": 1.0,
    "放松": 1.0, "舒坦": 1.0, "满足": 1.0, "幸福": 1.0, "温暖": 1.0,
    "有希望": 1.0, "有盼头": 1.0, "顺心": 1.0, "顺利": 1.0,
    "还好": 0.5, "还行": 0.5, "行": 0.5,
}
"""口语正向词 → 基准权重；"还好""还行"语气暧昧，按弱正向处理。"""

_SPOKEN_DIRECTION: dict[str, float] = {
    **{word: 1.0 for word in COLLOQUIAL_POSITIVE},
    **{word: -1.0 for word in COLLOQUIAL_NEGATIVE},
}
"""口语词 → 方向；权重另查 :data:`_SPOKEN_WEIGHTS`。"""

_SPOKEN_WEIGHTS: dict[str, float] = {**COLLOQUIAL_POSITIVE, **COLLOQUIAL_NEGATIVE}
"""口语词 → 基准权重。"""

DUAL_ROLE_WORDS = frozenset({"好", "坏", "沉", "惨", "苦", "痛", "死", "老"})
"""既在程度副词表、又当情绪词用的字。

"好"是典型：``好累`` 里的"好"是"很"的意思，``我很好`` 里的"好"是情绪词。
两者都出现在程度副词表里，只能靠**后一个词是不是情绪词**来分——见
:func:`_hownet_polarity` 的注释。
"""

try:  # pragma: no cover - 依赖缺失时整条文本链路退化为"读不出极性"
    from cnsenti import Emotion, Sentiment
except ImportError:  # pragma: no cover
    Emotion = None  # type: ignore[assignment]
    Sentiment = None  # type: ignore[assignment]


def _squash(value: float, scale: float) -> float:
    """把无界的加权分压进 [-1, 1]，保留方向与相对强弱。"""

    return math.tanh(value / scale)


@lru_cache(maxsize=1)
def _sentiment_lexicon():
    return Sentiment() if Sentiment is not None else None


@lru_cache(maxsize=1)
def _hownet_word_sets():
    lexicon = _sentiment_lexicon()
    if lexicon is None:
        return None
    return frozenset(lexicon.Poss), frozenset(lexicon.Negs), frozenset(lexicon.Denys)


@lru_cache(maxsize=1)
def _ontology_word_sets():
    if Emotion is None:
        return None
    lexicon = Emotion()
    positive = frozenset().union(*(getattr(lexicon, name) for name in POSITIVE_CATEGORIES))
    negative = frozenset().union(*(getattr(lexicon, name) for name in NEGATIVE_CATEGORIES))
    return positive, negative


def _tokens(text: str) -> list[str]:
    import jieba

    return [word for word in jieba.lcut(text) if word.strip()]


@lru_cache(maxsize=1)
def _adverb_weights() -> dict[str, float] | None:
    """程度副词 → 权重；同一词出现在多档时取先出现的那一档。"""

    lexicon = _sentiment_lexicon()
    if lexicon is None:
        return None
    weights: dict[str, float] = {}
    for name, weight in ADVERB_WEIGHT_SOURCES:
        for word in getattr(lexicon, name):
            weights.setdefault(word, weight)
    return weights


@lru_cache(maxsize=1)
def _adverbs_by_length() -> tuple[str, ...]:
    """程度副词按长度从长到短，切开粘连词时先用长的。"""

    weights = _adverb_weights()
    if not weights:
        return ()
    return tuple(sorted(weights, key=len, reverse=True))


def _is_sentiment_word(word: str, sentiment: tuple[frozenset[str], ...]) -> bool:
    """这个词是不是一个能定方向的情感词（知网、本体或口语三张表任一命中）。"""

    return word in _SPOKEN_DIRECTION or any(word in table for table in sentiment)


def _next_word(words: list[str], index: int) -> str:
    return words[index + 1] if index + 1 < len(words) else ""


def _split_off_adverb(
    word: str, weights: dict[str, float], sentiment: tuple[frozenset[str], ...],
) -> list[str]:
    r"""把被 jieba 粘成一个未登录词的"程度副词 + 情绪词"切开。

    实测 jieba 把``挺沉``\ ``有点烦``\ ``好烦``\ ``好困``粘成一个词，却又把
    ``很累``\ ``好累``分开；不切这几类就整句读不出极性。两条约束保证不误伤：

    - 整词本身已经是词表里的情绪词（"难受""不错""还好"）就不切——否则"难过"
      这类词有被"难"+"过"拆坏的风险；
    - 前半段必须真是程度副词、后半段必须真是情绪词，否则不切（"不想""很早"
      "好久"因此安全）。
    """

    if len(word) < 2 or _is_sentiment_word(word, sentiment):
        return []
    for adverb in _adverbs_by_length():
        if len(adverb) >= len(word) or not word.startswith(adverb):
            continue
        rest = word[len(adverb):]
        if rest in weights or _is_sentiment_word(rest, sentiment):
            return [adverb, rest]
    return []


def _hownet_polarity(text: str) -> float | None:
    """按知网七张词表 + 口语补充词表算极性，读不出情绪词时返回 ``None``。

    为什么不用 ``cnsenti.Sentiment.sentiment_calculate``：它判情感词用的是
    ``if word in self.Poss``，而程度副词表与情感词表有 19 个词重叠（``"特别"``
    既在 ``Poss`` 又在 ``Verys``），这类词一旦被当成情感词，整句方向就会反。
    重叠的词全部是副词形态、没有一个能单独当情绪词用，所以这里改成
    "先副词、后情感词"：权重、扫描窗口（上一个情感词之后的词）与"奇数个否定词
    翻转"三条规则仍照抄 ``sentiment_calculate``，量纲与它保持一致。

    唯一的例外是 :data:`DUAL_ROLE_WORDS`：``好`` 既是程度副词（``好累`` =
    很累）又是情绪词（``我很好``），这里靠**后一个词是不是情绪词**来分。
    """

    word_sets = _hownet_word_sets()
    weights = _adverb_weights()
    if word_sets is None or weights is None:
        return None
    positive, negative, denial = word_sets
    tables = (positive, negative)
    words = _words_to_score(text, weights, tables)
    total = 0.0
    weight = 1.0
    negations = 0
    for index, word in enumerate(words):
        if word in denial:
            negations += 1
            continue
        spoken = _SPOKEN_DIRECTION.get(word)
        adverb = word in weights and (
            spoken is None
            or (
                word in DUAL_ROLE_WORDS
                and _is_sentiment_word(_next_word(words, index), tables)
            )
        )
        if adverb:
            weight *= weights[word]
            continue
        if spoken is not None:
            direction, magnitude = spoken, _SPOKEN_WEIGHTS[word]
        elif word in positive or word in negative:
            direction, magnitude = (1.0 if word in positive else -1.0), 1.0
        else:
            continue
        total += weight * magnitude * (-1.0 if negations % 2 else 1.0) * direction
        # 窗口从上一个情感词之后重新开始，后面的副词不再影响这一词。
        weight, negations = 1.0, 0
    if total == 0.0:
        return None
    return _squash(total, POLARITY_SCALE)


def _words_to_score(
    text: str, weights: dict[str, float], sentiment: tuple[frozenset[str], ...],
) -> list[str]:
    """分词，并修补程度副词与情绪词被粘成一个词的情况。"""

    words: list[str] = []
    for word in _tokens(text):
        split = _split_off_adverb(word, weights, sentiment)
        words.extend(split if split else [word])
    return words


def _ontology_polarity(text: str) -> float | None:
    word_sets = _ontology_word_sets()
    if word_sets is None:
        return None
    positive, negative = word_sets
    lean = 0.0
    cursor = 0
    for word in _tokens(text):
        index = text.find(word, cursor)
        if index < 0:
            continue
        cursor = index + len(word)
        if word in positive:
            direction = 1.0
        elif word in negative:
            direction = -1.0
        else:
            continue
        lean += -direction if predicate_is_negated(text, index) else direction
    if lean == 0.0:
        return None
    return _squash(lean, LEAN_SCALE)


def text_polarity(text: str) -> float | None:
    """把一句自述映射到 [-1, 1]；读不出情绪时返回 ``None``。

    正向为 + 、负向为 -，量级表示强度，与视觉效价 ``valence`` 同一量纲，
    便于直接作差比较。
    """

    if not text or not text.strip():
        return None
    hownet = _hownet_polarity(text)
    if hownet is not None:
        return hownet
    return _ontology_polarity(text)
