# -*- coding: utf-8 -*-
"""Evaluation Agent 的**输入契约**：哪些内容会被送进评估模型。

本模块是"什么可以进入评估流程"的唯一定义，由后端自己构造
（**不是**大模型产出），因此使用严格模式：未知字段直接报错。

数据流位置::

    EvaluationInput        <- 本模块
          ↓
    [未来：强模型]
          ↓
    RawLLMAssessment

设计约定
--------

- ``dialogue_history`` 至少 1 条：没有任何对话就没有可评估的内容，
  不要用空列表占位。
- ``content`` 不做自动 trim，但拒绝空串与纯空白；
  原文照传，评测口径依赖原话。
- ``role`` 用枚举固定，写错（例如 ``"asistant"``）会直接报错，
  而不是被静默当成合法角色。四个取值与上游 ``MessageRole`` 对齐。
- 视觉输入分**两级**（见 :mod:`evaluation_agent.multimodal`）：
  句级 ``vision_snapshot`` 挂在每条消息上，会话级 ``vision_summary``
  放在顶层。两级都可选，缺失时省略字段而不是传空字符串。
- ``user_memory`` 可选，缺失时不要传空字符串，直接省略该字段。
- 本模块**不包含**自伤 / 自杀或其他安全风险字段：本项目当前阶段不处理安全模块，
  安全信号不应混进评估输入契约。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from .base import (
    NonEmptyStr,
    StrictSchemaBase,
    UpstreamSchemaBase,
    ValueStrEnum,
)
from .multimodal import SessionVisionSummary, VisionState

__all__ = ["DialogueRole", "DialogueMessage", "EvaluationInput"]


class DialogueRole(ValueStrEnum):
    """对话角色。四个取值与上游 ``backend/models/enums.py::MessageRole`` 一致。

    为什么要四种：上游的会话记录里确实可能混入**心理老师的人工消息**
    （``counselor``）和**系统消息**（``system``）。如果这里只认两种，
    真实数据一旦带这两类消息就会整份被拒收、评估完全跑不起来。

    但"能收下"不等于"一视同仁"：只有 ``USER`` 的话属于被评估者的自述，
    其余三种都只是上下文，**不得**当作症状证据（详见 Prompt 的口径说明）。
    """

    USER = "user"
    ASSISTANT = "assistant"
    COUNSELOR = "counselor"
    SYSTEM = "system"


#: 「谁的话算被评估者自述」。Prompt 与测试共用这一份定义，避免两处口径漂移。
SELF_REPORT_ROLES: frozenset[DialogueRole] = frozenset({DialogueRole.USER})


class DialogueMessage(UpstreamSchemaBase):
    """一条对话消息：角色、原文，以及这句话对应的**句级**视觉状态。

    为什么句级视觉挂在消息上、而不是另开一个平行列表：平行列表要靠下标对齐，
    一旦上游少发或多发一条快照，整份数据的对应关系就全错位了；
    挂在消息上则天然自洽（上游的 ``Message.vision_snapshot`` 也是这么做的）。

    **本模型是宽松层**：它直接承接上游 ``Message`` 对象，而上游的消息还带
    ``created_at`` / ``audio_snapshot`` 等本阶段不处理的字段。我们只读取
    上游数据、不定义上游协议，因此多一个字段就拒收整份对话并不划算——
    未知字段会留在 ``model_extra`` 里供后端诊断，**不参与评估**。

    注意代价：宽松层也意味着**消息内部的字段名拼错不会报错**（例如把
    ``vision_snapshot`` 写成 ``visoin_snapshot``，视觉数据会被静默忽略）。
    这是有意接受的取舍——顶层 :class:`EvaluationInput` 仍是严格的，
    写错一级字段名一定会被发现；消息内部的拼写由调用方自行保证。
    """

    role: DialogueRole = Field(
        ...,
        description=(
            '消息角色，只能是 "user"（被评估者本人）、"assistant"（对话 Agent）、'
            '"counselor"（心理老师人工消息）或 "system"（系统消息）。'
        ),
    )
    content: NonEmptyStr = Field(
        ...,
        description=(
            "消息原文，必须非空（空串与纯空白都会被拒绝）。"
            "文本不会被自动 trim，原话照传。"
        ),
    )
    vision_snapshot: VisionState | None = Field(
        default=None,
        description=(
            "这句话对应的句级视觉状态（可选）。没有视觉能力或该句未采集时省略。"
            "上游字段名为 Message.vision_snapshot。"
        ),
    )


class EvaluationInput(StrictSchemaBase):
    """一次评估所需的全部输入。

    这是整段对话结束后交给强模型的输入契约：

    - ``dialogue_history``：必填，按时间顺序排列，至少 1 条；
      每条消息可携带自己的**句级**视觉快照 ``vision_snapshot``；
    - ``vision_summary``：可选，**会话级**视觉汇总（整段对话聚合而成）；
    - ``user_memory``：可选，关于该用户的**长期背景信息**（自由文本），
      例如既往对话中稳定出现的情况；没有时省略。

    ``assessment_id`` **不在这里**：它由后端在评估开始时生成，
    大模型不得自行编造，因此不进入模型输入。
    """

    dialogue_history: list[DialogueMessage] = Field(
        ...,
        min_length=1,
        description="按时间顺序排列的对话记录，至少 1 条；空列表会被拒绝。",
    )
    vision_summary: SessionVisionSummary | None = Field(
        default=None,
        description=(
            "会话级视觉汇总（可选）：整段对话的均值、逐句效价趋势与出现占比。"
            "没有视觉能力时请省略该字段。句级数据请挂在各条消息的 vision_snapshot 上。"
        ),
    )
    user_memory: NonEmptyStr | None = Field(
        default=None,
        description=(
            "用户长期背景信息，自由文本（可选）。没有时请省略该字段，"
            "不要传空字符串。"
        ),
    )

    # -- 序列化辅助（纯数据转换，便于把输入固化成可复用的样例文件） ---------

    def to_json_str(self, *, indent: int = 2) -> str:
        """序列化为 JSON 字符串；中文不转义，便于人工阅读。"""
        return self.model_dump_json(indent=indent)

    def to_dict(self) -> dict[str, Any]:
        """转为 JSON 安全的 dict（枚举转字符串）。"""
        return self.model_dump(mode="json")

    def to_json_file(self, path: str | Path, *, indent: int = 2) -> None:
        """写入 JSON 文件，末尾补一个换行。"""
        Path(path).write_text(self.to_json_str(indent=indent) + "\n", encoding="utf-8")

    @classmethod
    def from_json_str(cls, data: str) -> "EvaluationInput":
        """从 JSON 字符串构造并严格校验。"""
        return cls.model_validate_json(data)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "EvaluationInput":
        """从 JSON 文件构造并严格校验（例如演示用的样例输入）。"""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
