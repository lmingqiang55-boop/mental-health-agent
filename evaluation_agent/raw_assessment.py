# -*- coding: utf-8 -*-
"""强模型**原始产出**的 Schema：11 个小项的 score / evidence / reason。

本模块描述的是"模型应该返回什么结构"，而**不是**"什么值一定合法"：

- ``score`` 允许 ``int`` / ``float`` / ``str`` 三种形态，
  因为强模型经常把 ``2`` 写成 ``2.0`` 或 ``"2"``；
  真正的合法性判定在 :mod:`evaluation_agent.normalization` 里完成；
- 结构本身仍然严格：11 个小项一个都不能少，``evidence`` / ``reason`` 必须非空；
- 未知字段**不报错**，会被保留在 ``model_extra`` 供后端观察模型漂移，
  但不参与任何计算（详见 :mod:`evaluation_agent.base`）。

数据流位置::

    EvaluationInput
          ↓
    [未来：强模型]
          ↓
    RawLLMAssessment        <- 本模块（未归一化）
          ↓
    normalization
          ↓
    AssessmentItemScores

本模块**不包含**自伤 / 自杀或其他安全风险字段。
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Union

from pydantic import Field, field_validator

from .base import LenientSchemaBase, NonEmptyStr
from .schemas import ITEM_KEYS as _ITEM_KEYS

__all__ = [
    "RawItemScore",
    "EvidenceList",
    "wrap_evidence",
    "ItemAssessment",
    "RawLLMAssessment",
    "ModelReplyParseError",
    "extract_json_object",
    "build_response_json_schema",
    "RESPONSE_SCHEMA_NAME",
]


#: 模型可能返回的原始分数形态。**只用于接收**，不参与计算：
#: 计算前必须经过 ``normalize_item_score()`` 转成 0-3 的整数。
RawItemScore = Union[int, float, str]

#: 依据列表：至少 1 条，每条非空。
#: 一次判断可能引用多处原话，因此用列表；只有一处时就是单元素列表。
EvidenceList = Annotated[list[NonEmptyStr], Field(min_length=1)]


def wrap_evidence(value: Any) -> Any:
    """把裸字符串包装成单元素列表（``evidence`` 的宽松输入处理）。

    ``evidence`` 的正式形态是列表，但为了兼容"只引用一句话"的简写
    以及宽松模式下的模型输出，收到裸字符串时自动包装，
    而不是判定为结构错误。原始产出层与后台明细层共用这一处理。
    """
    if isinstance(value, str):
        return [value]
    return value


class ItemAssessment(LenientSchemaBase):
    """单个小项的模型原始判断结果：分数 + 依据 + 理由。

    三个字段都必须存在，且 ``evidence`` / ``reason`` 必须非空：
    没有依据或没有理由的分数无法审计，也不应该被后端保存。

    - ``evidence``：对话中的**原始依据**，至少 1 条（引用或贴近原话的转述）；
      一次判断可能引用多处原话，所以是列表；对话完全没提到该方面时，
      按 Prompt 约定写 ``["对话中未提及相关表现"]``。
    - ``reason``：**为什么**据此给出这个分数（判断理由）。

    两者都会由后端单独保存（见
    :class:`evaluation_agent.normalization.ItemAssessmentDetails`），
    **不进入**用户可见的 ``EvaluationOutput``。
    """

    score: RawItemScore = Field(
        ...,
        description=(
            "模型给出的原始分数，允许整数、浮点或数字字符串（如 2 / 2.0 / \"2\"）。"
            "进入计算前一律经过 normalize_item_score() 归一化为 0-3 的整数。"
        ),
    )
    evidence: EvidenceList = Field(
        ...,
        description=(
            "对话中的原始依据：引用或贴近原话的转述，至少 1 条。"
            "也接受单个字符串（会被包装成单元素列表）。"
        ),
    )
    reason: NonEmptyStr = Field(
        ...,
        description="为什么据此给出该分数：判断理由。必须非空。",
    )

    @field_validator("evidence", mode="before")
    @classmethod
    def _accept_single_string_evidence(cls, value: Any) -> Any:
        """允许 ``evidence`` 传单个字符串（包装成列表）。"""
        return wrap_evidence(value)


class RawLLMAssessment(LenientSchemaBase):
    """强模型对 11 个小项的完整原始判断结果。

    字段与 :class:`evaluation_agent.schemas.AssessmentItemScores` **一一对应**
    （同名、同顺序），只是每个字段携带 ``score`` / ``evidence`` / ``reason``
    三部分，且 ``score`` 尚未归一化。

    11 个字段全部必填；未知字段进入 ``model_extra``，不参与计算。
    """

    # -- emotion ---------------------------------------------------------
    depressed_mood: ItemAssessment = Field(
        ..., description="情绪低落：持续低落、悲伤、空虚、明显消沉、悲观情绪。"
    )
    low_self_worth_guilt: ItemAssessment = Field(
        ..., description="自我价值降低与内疚：自我否定、失败感、无价值感、过度内疚。"
    )

    # -- interest_motivation ---------------------------------------------
    anhedonia: ItemAssessment = Field(
        ..., description="兴趣或愉悦感下降：对原本喜欢的活动兴趣下降、很难获得愉悦感。"
    )
    reduced_activity_initiative: ItemAssessment = Field(
        ..., description="主动性下降：做事意愿下降、开始任务困难、活动减少。"
    )

    # -- sleep_energy ----------------------------------------------------
    sleep_disturbance: ItemAssessment = Field(
        ..., description="睡眠异常：入睡困难、夜间易醒、早醒、睡眠过多、质量下降。"
    )
    fatigue_low_energy: ItemAssessment = Field(
        ..., description="疲劳与精力不足：疲劳、精力不足、很容易累。"
    )
    appetite_change: ItemAssessment = Field(
        ..., description="食欲变化：食欲下降或明显增加、与近期状态相关的进食变化。"
    )

    # -- attention_thinking ----------------------------------------------
    concentration_indecision: ItemAssessment = Field(
        ..., description="注意力与决策困难：难以集中、思考效率下降、明显决策困难。"
    )
    psychomotor_change: ItemAssessment = Field(
        ..., description="精神运动性变化：思维或动作明显变慢、说话变慢、坐立不安、躁动。"
    )

    # -- social_daily（功能影响类） ---------------------------------------
    study_work_impairment: ItemAssessment = Field(
        ..., description="学习 / 工作功能受损：必须有实际功能影响的证据。"
    )
    social_daily_impairment: ItemAssessment = Field(
        ..., description="社交与日常功能受损：明显减少社交、回避他人、生活规律受影响。"
    )

    @classmethod
    def from_model_reply(cls, reply: str) -> "RawLLMAssessment":
        """从模型的回复文本中解析出原始产出。

        Prompt 要求模型"只输出一个 JSON 对象"，但实际回复经常带上
        Markdown 代码围栏或少量前后说明。本方法按以下顺序尝试：

        1. 整段文本直接就是 JSON；
        2. 去掉 ``` / ```json 围栏后再解析；
        3. 从文本中截出第一个**括号配对**的 JSON 对象（会跳过字符串内的括号）。

        结构校验仍然严格（11 项一个不能少、evidence/reason 非空），
        未知字段照旧被容忍。

        :param reply: 模型的原始回复文本。
        :returns: 校验通过的原始产出。
        :raises ModelReplyParseError: 文本里找不到可解析的 JSON 对象。
        :raises pydantic.ValidationError: JSON 结构不符合 11 小项要求。
        """
        return cls.model_validate(extract_json_object(reply))


class ModelReplyParseError(ValueError):
    """模型回复文本里找不到可解析的 JSON 对象。

    继承 ``ValueError``，调用方可以单独捕获它来决定是否重试。
    错误信息里会带一小段原文，便于排查模型到底返回了什么。
    """


def extract_json_object(reply: str) -> dict[str, Any]:
    """从文本中提取第一个 JSON 对象。

    容错对象是**包裹形式**（代码围栏、前后说明），不是**结构错误**：
    解析出来的对象仍要经过严格校验，不合法一样会被拒绝。

    额外容忍一种**实测高频**的线格式缺陷：模型偶尔会把最外层对象的
    收尾 ``}`` 漏掉（其余内容完整）。这属于"包裹没收好"，见
    :func:`_close_unbalanced`；补括号既不新增也不修改任何内容，
    而且补齐结果仍要过 11 项必填校验，所以不可能让残缺判断蒙混过关。

    :param reply: 模型回复文本。
    :returns: 解析出的 dict。
    :raises ModelReplyParseError: 找不到可解析的 JSON 对象。
    :raises ModelReplyParseError: 找到了但不是 JSON 对象（例如是数组或字符串）。
    """
    if not isinstance(reply, str) or not reply.strip():
        raise ModelReplyParseError("模型回复为空，无法解析出 11 小项结果")

    candidates = [reply.strip(), _strip_code_fence(reply)]
    for candidate in candidates:
        parsed = _try_load(candidate)
        if parsed is not None:
            return _require_object(parsed, reply)

    for candidate in _balanced_object_slices(reply):
        parsed = _try_load(candidate)
        if parsed is not None:
            return _require_object(parsed, reply)

    for candidate in candidates:
        repaired = _close_unbalanced(candidate)
        if repaired is not None:
            parsed = _try_load(repaired)
            if parsed is not None:
                return _require_object(parsed, reply)

    raise ModelReplyParseError(
        "模型回复中找不到可解析的 JSON 对象。回复开头："
        f"{reply.strip()[:200]!r}"
    )


def _close_unbalanced(text: str) -> str | None:
    """补上最外层 JSON 对象缺少的收尾括号，只补不改。

    实测（``deepseek-flash`` + ``json_schema``，12 次里 3 次）模型会把
    **最外层那个 ``}`` 漏掉**：11 个小项的内容全都完整，就是最后一个
    括号没输出。这种情况下重试能成功，但要白等十几秒并重新计费一次，
    而补一个括号是确定且零成本的。

    只做"补括号"，刻意不做的事：

    - **字符串没收尾时不补**（返回 ``None``）：那说明是真的被截断了，
      内容缺一半，猜不出来，只能交给重试；
    - 不删字符、不改字符、不尝试"修"任何已有内容。

    因此这个函数最多只能把"只差收尾括号"的文本救回来；至于救回来的对象
    是不是完整判断，由 :class:`RawLLMAssessment` 的 11 项必填校验负责。

    :param text: 待检查的文本。
    :returns: 补齐后的文本；无需补齐或无法安全补齐时返回 ``None``。
    """
    start = text.find("{")
    if start == -1:
        return None

    fragment = text[start:]
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in fragment:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack:
                return None  # 括号对不上，不是"只缺收尾"，别乱补
            stack.pop()

    if in_string:
        return None  # 停在字符串中间：真的被截断了
    if not stack:
        return None  # 本来就是配平的，缺的不是括号
    return fragment + "".join("}" if item == "{" else "]" for item in reversed(stack))


def _try_load(text: str) -> Any | None:
    """尝试 json.loads，失败返回 None。"""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _require_object(parsed: Any, reply: str) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ModelReplyParseError(
            f"模型回复解析出的是 {type(parsed).__name__}，不是 JSON 对象。"
            f"回复开头：{reply.strip()[:200]!r}"
        )
    return parsed


def _strip_code_fence(text: str) -> str:
    """去掉 Markdown 代码围栏（```json ... ```）。"""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    lines = lines[1:]  # 去掉开头的 ``` 或 ```json
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _balanced_object_slices(text: str) -> list[str]:
    """扫描出括号配对的 JSON 对象片段（跳过字符串内的括号与转义）。

    只处理第一个对象：模型的回复里通常只有一个目标 JSON。
    """
    start = text.find("{")
    if start == -1:
        return []

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return [text[start : index + 1]]
    return []


# ---------------------------------------------------------------------------
# 线格式（wire format）：发给模型的 JSON Schema
# ---------------------------------------------------------------------------

#: 发给模型的 schema 名称（Responses API 的 ``text.format.name``）。
RESPONSE_SCHEMA_NAME = "psychological_item_assessment"

#: 依据条数上限。只约束**线格式**：模型不应把整段对话都抄回来。
_MAX_EVIDENCE_ITEMS = 6


def build_response_json_schema() -> dict[str, Any]:
    """构造发给模型的 **JSON Schema**（``text.format.type = "json_schema"``）。

    这里有两点刻意的设计：

    1. **线格式比本地模型更严**。线上用 ``additionalProperties: false`` +
    全部字段 ``required`` + ``score`` 限定为 ``0-3`` 整数，
    把"结构正确"这件事交给约束解码，而不是指望模型自觉；
    本地 ``RawLLMAssessment`` 仍然保留容忍度，用于兜底与
    ``json_object`` 模式。
    2. **明确禁止模型输出派生结论**。schema 里只有 11 个小项，
    没有 ``psychological_profile`` / ``concern_index`` / ``overall_level``
    ——五维与指数由代码计算，模型无权决定。

    :returns: 可直接放进 ``text.format.schema`` 的 JSON Schema。
    """
    item_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "score": {
                "type": "integer",
                "enum": [0, 1, 2, 3],
                "description": "该小项的 0-3 整数分，含义见系统提示中的 rubric。",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
                "maxItems": _MAX_EVIDENCE_ITEMS,
                "description": (
                    "对话中的原始依据，至少 1 条。完全未提及时写 "
                    "[\"对话中未提及相关表现\"]。"
                ),
            },
            "reason": {
                "type": "string",
                "minLength": 1,
                "description": "为什么给这个分数，以及与相邻分数的区别。",
            },
        },
        "required": ["score", "evidence", "reason"],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {item: item_schema for item in _ITEM_KEYS},
        "required": list(_ITEM_KEYS),
        "additionalProperties": False,
    }
