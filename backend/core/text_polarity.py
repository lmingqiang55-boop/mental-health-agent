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
2. **纯否定词不算情绪词，整句否认另有读法**。HowNet 的否定词表与负向词表重叠，
   "没有""没事"这类回答会被算成负分（实测 ``"没事"`` → ``neg=1``），可它只是在
   否认，本身不带情绪。本模块按 jieba 分词逐个查表、跳过纯否定词；而当整句话
   就是一句否认时（"我没事""没什么"），按**弱正向**处理，理由见
   :data:`DENIAL_CORES`。
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

整句否认（"我没事""没什么"）按**弱正向**处理，就是 :data:`DENIAL_CORES` 那条
规则。它换来的是"嘴上说没事、脸上却难过"能被核对通道抓到；代价是**症状否认**
也会被算成弱正向——问"最近有没有失眠"、答"没有"，那句话在字面上就是"没问题"，
会和脸上的低落构成一次假矛盾。用 0.5 的弱权重（与"还好"同档）加 0.4 的差值门槛
把影响压到最小，核对通道也只会温和地问一次、明令不许下结论；要彻底区分"否认
症状"与"否认情绪"必须先有对话上下文，那不是单句极性函数能做的判断。

**这条弱正向只给单句核对用，会话级的一致性分数不采用它**：调用方先问
:func:`is_whole_sentence_denial`，整句否认的句子不计入比对（见
:mod:`backend.core.multimodal_consistency`）。理由是那个分数要回答"两路信号彼此
接近的程度"，而否认句是回答"有没有"的，把它当成情绪表达会让普通筛查普遍低分。

**本函数不是语义理解**：它看不见反讽、读不出上下文，拿不准时返回 ``None``，
由调用方把这一句排除在统计之外，而不是塞一个 0 假装"中性"。
"""

from __future__ import annotations

import math
import re
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

_DENIAL_EXTRAS: frozenset[str] = frozenset({"没什么", "没啥", "没什么事", "没啥事"})
r"""口语否认说法，补进知网否定词表。

知网的否定词只收"没/没有/不/不是"这类，"没什么""没啥"一个都没收。它们因此被当成
普通词往下走，落到本体里当负向词用：实测 ``"没什么问题"`` 读成 ``-0.32``，而意思
相同的 ``"没问题"`` 读成 ``+0.32``——同一个意思两个方向。补进来之后两者一致。
"""

_DENIED_DENIAL = re.compile(
    r"(?:不是|不算|并不|没有|没|不)"
    r"[^，。！？、；：,.!?;:]{0,2}"
    r"(?:没事儿|没什么事|没啥事|没什么|没啥|没事|没关系)",
)
r"""「否认自己的否认」= 我不好。

``"我不是没事"``\ ``"我没有说没事"``\ ``"我不觉得没事"`` 在字面上是否定一个否认，
实际意思是**在说自己不好**。按"奇数个否定词翻转"的老规则，它们会被读成弱正
（实测 ``+0.32``），配上难过的脸就构成一次假矛盾——正好是这个模块最不该犯的错：
拿摄像头的猜测去反驳学生自己的诉苦。这里对这类说法单独给弱负向。

中间允许插两个字，是为了盖住 ``"没有说没事"``\ ``"不觉得没事"``；
核心词不含光秃秃的"没""没有"，避免把 ``"我没有不开心"``（= 我不难过）也卷进来。
"""

_DENIED_DENIAL_WEIGHT = 0.5
"""「否认的否认」与 :data:`DENIAL_WEIGHT` 同档，只是方向相反。"""

DENIAL_WEIGHT = 0.5
"""整句否认的语气强度：与"还好""还行"同档（0.5），只是弱正向，不是强正向。"""

DENIAL_CORES: frozenset[str] = frozenset({
    "没事", "没事儿", "没什么", "没什么事", "没啥", "没啥事", "没关系",
    "没有", "没",
})
r"""整句话只是否认时，剥掉前后缀之后剩下的核心说法。

这些说法是**本人对自己状态的否认**（"我没事""没什么"），不是带情绪的描述。
两条词典路径都读不出这层意思，反而会读错：知网把"没有"当纯否定词跳过，整句
因此返回 ``None``；大连理工本体又把"没事"收成一个负向词，实测读成 ``-0.32``。
于是"嘴上说没事、脸上却难过"这种最典型的矛盾信号会被漏掉。

按**弱正向**处理的理由与"还好""还行"完全一样：字面上他是在说自己没问题，
这正是核对通道能成立的前提。整句匹配而不匹配句中的否认片段，是为了避免把
"没有烦心事"之外更长的句子也卷进来——那种句子里通常还有别的情绪词可读，
交给正常规则处理更准。
"""

DENIAL_WHOLE_PHRASES: frozenset[str] = frozenset({
    "没什么大不了", "没什么大不了的",
})
r"""整句原样匹配的否认说法，不参与剥头剥尾。

为什么单列：``"没什么大不了的"`` 里的"了"是"大不了"这个词的一部分，不是语气词，
按 :data:`_DENIAL_STRIP_TAIL` 剥掉尾巴就只剩 ``"没什么大不"``，核心匹配不到，
于是落回词典路径、实测读成 ``-0.58``（本体把"大不了"当负向词，前面的"没什么"
没被算作否定）——和"没事"的读法正好相反，同为"我在说没事"却一个抓矛盾一个抓不到。
"""

_NOT_YET_CORES: frozenset[str] = frozenset({"没", "没有"})
r"""光秃秃的"没""没有"——它们既可能是"我没问题"，也可能是"尚未"。

区别只在有没有"还"和"呢"：``"还没睡"``\ ``"还没呢"`` 是"尚未"，不是"我没问题"；
而 ``"没呢"``\ ``"没有呢"`` 是同一层"尚未"的意思被剥掉了语气词之后的样子。
拿不准，所以按本模块一贯的规矩返回 ``None``（见 :func:`_denial_core`）。
"""

_DENIAL_STRIP_HEAD: tuple[str, ...] = (
    "我觉得", "我感觉", "我认为", "说实话", "老实说", "总的来说",
    "我", "也", "都", "其实", "真的", "现在", "目前", "最近", "刚刚", "刚", "今天",
)
r"""否认句里可以剥掉的人称与副词前缀，长的在前（先剥"我觉得"再剥"我"）。

故意不收"还"：``"还没"`` 意思是"尚未"，不是"我没事"，剥掉就会把它误读成正向。
实测这层前缀是"我没事"这类读法的**唯一**入口：多一个"我觉得""最近"就落回词典
路径，被读成 ``-0.32``（本体把"没事"收成负向词），方向正好读反。
"""

_DENIAL_STRIP_TAIL: tuple[str, ...] = (
    "真的", "来着", "就是了", "而已",
    "了", "的", "啊", "呀", "呢", "吧", "嘛", "哦", "噢", "嘞", "啦", "啰", "喔",
)
r"""否认句尾常见的语气词与口头填充，长的在前（先剥"真的"再剥"的"）。

剥掉"呢"之后 ``"还没呢"`` → ``"还没"`` 仍不匹配核心；但 ``"没呢"``\ ``"没有呢"``
会剥成光秃秃的"没""没有"，那层"尚未"的意思就没了，所以 :func:`_denial_core` 对这两个
核心另有判断，不因为少一个"还"就当成"我没事"。
"""

_DENIAL_STRIP_CHARS = frozenset(
    "，。！？、；：,.!?;: \t\r\n\u3000～~…—-_*/\\\"'“”‘’()（）[]【】"
)
"""整句否认判定前先剔除的标点与空白。"""

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


_NEGATION_PREFIXES: tuple[str, ...] = ("不是", "并不", "没有", "不", "没", "别")
r"""被 jieba 粘进同一个词里的否定前缀，长的在前。"""


def _split_off_negation(
    word: str, weights: dict[str, float], sentiment: tuple[frozenset[str], ...],
) -> list[str]:
    r"""把被 jieba 粘成一个词的"否定 + 情绪词"切开：``"不太好"`` → ``"不" + "太好"``。

    :func:`_split_off_adverb` 管的是"程度副词 + 情绪词"被粘起来；这一条管前面还多
    一个否定词的情况。实测 jieba 把 ``"不太好"`` 整体当成一个词，而它两张词典都不收，
    于是"我不太好"读出来是 ``None``——一句很常见的自述直接消失，而语义相同的
    ``"我不太开心"`` 是 ``-0.76``。

    只在**切出来的后半段确实是情绪词**时才切，并且整词本来就是词表里的情绪词、
    或是整句否认核心（"没事""没什么""没关系"）时一律不切。于是：

    - ``"不想"``\ ``"不行"`` 在口语词表里 → 不切；
    - ``"不好意思"``\ ``"不同"``\ ``"不用"``\ ``"受不了"`` 后半段不是情绪词 → 不切；
    - ``"不差"``\ ``"不烦"`` 切完再按否定翻转 → 读成弱正向，和语义一致。
    """

    if len(word) < 2 or _is_sentiment_word(word, sentiment):
        return []
    if word in DENIAL_CORES or word in DENIAL_WHOLE_PHRASES:
        return []
    for prefix in _NEGATION_PREFIXES:
        if len(prefix) >= len(word) or not word.startswith(prefix):
            continue
        rest = word[len(prefix):]
        if _is_sentiment_word(rest, sentiment):
            return [prefix, rest]
        split = _split_off_adverb(rest, weights, sentiment)
        if split:
            return [prefix, *split]
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
    denial = denial | _DENIAL_EXTRAS
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
            # 既不是副词也不是情绪词——否定管到它为止。不截断的话
            # "我没有说没事"里的"没有"会一路管到句尾的"没事"，把诉苦读成正向；
            # 截断之后"没有"只否定"说"，"没事"按自己的方向算（弱负）。
            negations = 0
            continue
        total += weight * magnitude * (-1.0 if negations % 2 else 1.0) * direction
        # 窗口从上一个情感词之后重新开始，后面的副词与否定都不再影响这一词。
        weight, negations = 1.0, 0
    if total == 0.0:
        return None
    return _squash(total, POLARITY_SCALE)


def _words_to_score(
    text: str, weights: dict[str, float], sentiment: tuple[frozenset[str], ...],
) -> list[str]:
    """分词，修补程度副词与情绪词被粘成一个词、或口语词被拆成几个词的情况。"""

    words: list[str] = []
    for word in _merge_spoken_compounds(_tokens(text)):
        split = _split_off_negation(word, weights, sentiment) or _split_off_adverb(word, weights, sentiment)
        words.extend(split if split else [word])
    return words


@lru_cache(maxsize=1)
def _spoken_span_limit() -> int:
    """口语词最多被 jieba 拆成几段（够覆盖词表里最碎的那条），上限 4。"""

    return min(4, max((len(_tokens(word)) for word in _SPOKEN_WEIGHTS), default=1))


def _merge_spoken_compounds(words: list[str]) -> list[str]:
    r"""把被 jieba 拆开的口语词合回去——:func:`_split_off_adverb` 的反向修补。

    为什么必须有这一步：:data:`COLLOQUIAL_POSITIVE`\ :data:`COLLOQUIAL_NEGATIVE`
    是按"学生实际会怎么说"写的词，jieba 并不认识它们。实测两张表里 25 条被拆开：

    - ``"还行"`` → ``["还", "行"]``，于是"还"按程度副词加倍（2.0）、"行"按 0.5 算，
      得到 ``+0.32``，是文档里写的弱正向（``+0.16``）的两倍；
    - ``"心情不好"`` → ``["心情", "不好"]``、``"提不起劲"`` → ``["提不起", "劲"]``、
      ``"想哭"`` → ``["想", "哭"]``：拆完每一段都不在词表里，整句直接读不出极性
      （返回 ``None``），口语词表白写。

    只对**本模块自己的口语词表**做这一步：拼起来必须一字不差地命中表里的词，
    所以它不会把"不"+"错"合成别的意思，也不会碰知网/本体那两套自带分词的词典。
    合出来的词必定在 :data:`_SPOKEN_DIRECTION` 里，:func:`_split_off_adverb`
    因此不会再把它切开。
    """

    limit = _spoken_span_limit()
    merged: list[str] = []
    index = 0
    while index < len(words):
        span = min(limit, len(words) - index)
        while span > 1:
            candidate = "".join(words[index:index + span])
            if candidate in _SPOKEN_WEIGHTS:
                merged.append(candidate)
                index += span
                break
            span -= 1
        else:
            merged.append(words[index])
            index += 1
    return merged


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


def _denial_core(text: str) -> str:
    r"""剥掉标点、人称与语气词，得到否认句的核心说法；不是整句否认时返回空串。

    先按 :data:`DENIAL_WHOLE_PHRASES` 整句原样匹配（"没什么大不了的"里的"了"不是
    语气词，剥不得），再走剥头剥尾；剥的过程里每一步也回头查一次整句短语表，
    所以 ``"我没什么大不了的"`` 会在剥掉"我""的"之后命中。

    剥头剥尾都按**从长到短**匹配，且一轮只剥一处、循环到剥不动为止：``"我没事，真的"``
    先剥标点、再剥"我"、再剥尾部的"真的"，才剩得下"没事"。只剥单字的话
    ``"真的"`` 会剩成一个"真"，核心匹配不上，整句就落回词典路径被读成 ``-0.32``。

    尾部语气词里只有"呢"会改变否定应答的意思（``"没呢"``\ ``"没有呢"`` 是"尚未"），
    所以剥掉过"呢"之后只剩 :data:`_NOT_YET_CORES` 的，按"拿不准"处理，返回空串。
    """

    stripped = "".join(ch for ch in text.strip() if ch not in _DENIAL_STRIP_CHARS)
    core = stripped
    if core in DENIAL_WHOLE_PHRASES or core in DENIAL_CORES:
        return core
    dropped_yet_particle = False
    while core:
        head = next((value for value in _DENIAL_STRIP_HEAD
                     if core.startswith(value) and len(core) > len(value)), "")
        if head:
            core = core[len(head):]
        else:
            tail = next((value for value in _DENIAL_STRIP_TAIL
                         if core.endswith(value) and len(core) > len(value)), "")
            if not tail:
                break
            if "呢" in tail:
                dropped_yet_particle = True
            core = core[:-len(tail)]
        if core in DENIAL_WHOLE_PHRASES:
            return core
    if core not in DENIAL_CORES:
        return ""
    if dropped_yet_particle and core in _NOT_YET_CORES:
        return ""
    return core


def is_whole_sentence_denial(text: str) -> bool:
    """整句话只是一句否认（"我没事""没什么""没有"）时为真。

    ``text_polarity`` 会把这些句子读成弱正向，好让"嘴上说没事、脸上却难过"能被
    **单句**核对通道抓到；但它们不是情绪表达，而是回答"有没有"的，所以
    :func:`backend.core.multimodal_consistency.compute_consistency` 用它把这些
    句子排除在会话级一致性分数之外。
    """

    return bool(_denial_core(text))


def _denial_polarity(text: str) -> float | None:
    """整句话只是一句否认时给弱正向；否则返回 ``None`` 交给词典路径。"""

    return _squash(DENIAL_WEIGHT, POLARITY_SCALE) if _denial_core(text) else None


def _denied_denial_polarity(text: str) -> float | None:
    """「否认自己的否认」（"我不是没事"）给弱负向；不是这种说法时返回 ``None``。"""

    if not _DENIED_DENIAL.search(text):
        return None
    return -_squash(_DENIED_DENIAL_WEIGHT, POLARITY_SCALE)


def text_polarity(text: str) -> float | None:
    """把一句自述映射到 [-1, 1]；读不出情绪时返回 ``None``。

    正向为 + 、负向为 -，量级表示强度，与视觉效价 ``valence`` 同一量纲，
    便于直接作差比较。
    """

    if not text or not text.strip():
        return None
    denial = _denial_polarity(text)
    if denial is not None:
        return denial
    denied = _denied_denial_polarity(text)
    if denied is not None:
        return denied
    hownet = _hownet_polarity(text)
    if hownet is not None:
        return hownet
    return _ontology_polarity(text)
