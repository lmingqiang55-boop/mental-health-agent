"""Decide the next screening action with a model, then phrase it with a model.

Two responsibilities, two interfaces
------------------------------------
``QuestionDecider`` reads this turn's student answer, the extracted evidence, the
current topic, the ``asked_once``/``confirmed`` state of all nine PHQ-A topics
and the recent dialogue, and returns exactly one ``QuestionAction``. **It is the
only component that chooses the topic and the intent.** There is no priority
list anywhere in this module or in the engine.

``QuestionGenerator`` receives the already-selected ``QuestionAction`` and writes
one natural question for a student. It must not switch the topic or the intent.

``validate_question_action`` sits between them and checks *legality only*:

* the topic exists and is still open — a topic that is both ``confirmed`` and
  already asked is closed, so a completed topic can never be repeated without a
  reason (a recorded contradiction un-confirms the topic first, so resolving it
  is still legal);
* a quoted ``anchor_quote`` must be verbatim student text, taken from this
  turn's answer or from that topic's recorded evidence. Invented quotes are
  rejected instead of being paraphrased into a question;
* ``intent`` must match the recorded state — you cannot "open" a topic that was
  already asked, "resolve a conflict" that was never recorded, or "confirm a
  mention" that has no evidence from the student.

It deliberately does **not** rank topics and **does nothing to rescue an illegal
action**: an illegal action is rejected, and the turn is not committed. Silently
substituting a "more sensible" topic would put the fixed priority rule back in.

There is likewise no "finish" action: the turn graph completes only when all nine
topics are both explicitly asked and confirmed
(:func:`backend.assessment.models.can_complete`), so a decision model cannot end
the assessment while topics are still open.

Configuration
-------------
``ASSESSMENT_QUESTION_GENERATOR=mock|openai_compatible`` selects the pipeline.
The decider and generator each accept their own ``ASSESSMENT_DECIDER_*`` and
``ASSESSMENT_GENERATOR_*`` endpoint/model settings. Legacy ``ASSESSMENT_LLM_*``
values remain fallbacks for older configurations and the evidence extractor.
The ``mock`` pair is deterministic, offline and intended for tests only.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from backend.assessment.bank import ANSWER_CHOICES, BY_ID, ITEMS
from backend.assessment.extractor import EvidenceCandidate
from backend.assessment.models import AssessmentSession

_TWO_WEEK_TERMS = ("过去两周", "最近两周", "这两周", "近两周", "过去14天", "最近14天", "这14天")


class QuestionGenerationUnavailable(Exception):
    """The configured question model did not return a usable question."""


class QuestionActionRejected(QuestionGenerationUnavailable):
    """The decider proposed an action the program must not execute.

    Subclasses ``QuestionGenerationUnavailable`` so an existing caller that only
    handles the older exception still fails the turn safely.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


QuestionIntent = Literal[
    "open_topic",          # 开启主题：该主题尚未明确提问
    "clarify_period",      # 澄清时间：时间窗不清
    "clarify_frequency",   # 澄清频率：未落到四档
    "resolve_conflict",    # 处理矛盾：前后回答冲突
    "confirm_mention",     # 确认主动提及的主题
]

INTENT_LABELS: dict[str, str] = {
    "open_topic": "开启主题",
    "clarify_period": "澄清时间",
    "clarify_frequency": "澄清频率",
    "resolve_conflict": "处理矛盾",
    "confirm_mention": "确认主动提及的主题",
}


class QuestionAction(BaseModel):
    """What the decider chose. The program validates it before anything is asked."""

    model_config = ConfigDict(extra="forbid")

    target_item_id: str
    intent: QuestionIntent
    anchor_quote: str = ""
    reason: str = ""


# ============================================================================
# What the decider is allowed to read
# ============================================================================


@dataclass(frozen=True)
class DecisionContext:
    """Everything the decision model is given, and nothing else.

    Built by the turn graph after evidence extraction, so the model sees the same
    view the program acts on: this turn's answer, the extracted evidence, the
    current topic, the nine topics' ``asked_once``/``confirmed`` state, and the
    recent dialogue plus the actions already taken.
    """

    session: AssessmentSession
    allowed_item_ids: tuple[str, ...]
    latest_text: str = ""
    evidence: tuple[EvidenceCandidate, ...] = ()
    accepted_item_ids: tuple[str, ...] = ()

    @property
    def current_item_id(self) -> str | None:
        return self.session.current_item_id

    def grounded_quotes(self, item_id: str) -> tuple[str, ...]:
        """Verbatim student text a quote for ``item_id`` may be drawn from."""
        state = self.session.items[item_id]
        quotes = [self.latest_text, state.evidence_quote or ""]
        quotes.extend(event.quote for event in state.evidence_history)
        return tuple(quote for quote in quotes if quote and quote.strip())

    def is_grounded(self, item_id: str, quote: str) -> bool:
        value = quote.strip()
        return bool(value) and any(value in source for source in self.grounded_quotes(item_id))

    def payload(self) -> dict[str, object]:
        """The JSON view handed to the decision model (also used by tests)."""
        return {
            "grade": self.session.grade,
            "current_item_id": self.current_item_id,
            "latest_student_answer": self.latest_text,
            "allowed_item_ids": list(self.allowed_item_ids),
            "extracted_evidence": [
                {"item_id": c.item_id, "quote": c.quote, "period": c.period, "category": c.category}
                for c in self.evidence
            ],
            "accepted_item_ids": list(self.accepted_item_ids),
            "topics": [self._topic(item.item_id, item.label) for item in ITEMS],
            "recent_turns": [
                {"target_item_id": turn.target_item_id, "student": turn.user_text,
                 "assistant": turn.assistant_text}
                for turn in self.session.turns[-3:]
            ],
            "recent_actions": [
                {"item_id": entry.item_id, "intent": entry.intent}
                for entry in self.session.action_log[-3:]
            ],
        }

    def _topic(self, item_id: str, label: str) -> dict[str, object]:
        state = self.session.items[item_id]
        return {
            "item_id": item_id,
            "label": label,
            "status": state.status,
            "asked_once": state.asked_once,
            "confirmed": state.status == "confirmed",
            "conflict": state.conflict,
            "latest_evidence": [event.quote for event in state.evidence_history[-2:]],
        }


# ============================================================================
# Legality only — never a choice of topic
# ============================================================================


def validate_question_action(action: QuestionAction, context: DecisionContext) -> QuestionAction:
    """Reject an illegal action; otherwise return it, normalised.

    Raises ``QuestionActionRejected`` with a machine-readable ``code``:
    ``assessment_complete``, ``unknown_item``, ``topic_not_open``,
    ``ungrounded_quote``, ``missing_anchor``, ``intent_mismatch``.
    """
    if not context.allowed_item_ids:
        raise QuestionActionRejected(
            "assessment_complete", "all nine topics are confirmed and explicitly asked"
        )

    item_id = action.target_item_id.strip()
    if item_id not in BY_ID:
        raise QuestionActionRejected(
            "unknown_item", f"{item_id!r} is not one of the nine PHQ-A topics"
        )
    if item_id not in context.allowed_item_ids:
        raise QuestionActionRejected(
            "topic_not_open",
            f"{item_id} is confirmed and already asked; a completed topic cannot be repeated",
        )

    state = context.session.items[item_id]
    quote = action.anchor_quote.strip()
    if quote and not context.is_grounded(item_id, quote):
        raise QuestionActionRejected(
            "ungrounded_quote",
            f"anchor_quote {quote!r} is not verbatim student text for {item_id}",
        )

    intent = action.intent
    if intent == "open_topic":
        if state.asked_once:
            raise QuestionActionRejected(
                "intent_mismatch",
                f"open_topic needs a topic never explicitly asked, but {item_id} was asked",
            )
    elif intent == "confirm_mention":
        if not quote:
            raise QuestionActionRejected(
                "missing_anchor", "confirm_mention must quote the student's own words"
            )
        if not state.evidence_history:
            raise QuestionActionRejected(
                "intent_mismatch", f"no student mention of {item_id} is recorded"
            )
    elif intent in ("clarify_period", "clarify_frequency"):
        # The topic must already have been put to the student: either recorded as
        # asked, or with an answer on record for it.
        if not (state.asked_once or state.evidence_history):
            raise QuestionActionRejected(
                "intent_mismatch",
                f"{intent} needs a topic the assistant already asked, but {item_id} was never asked",
            )
    elif intent == "resolve_conflict":
        if not quote:
            raise QuestionActionRejected(
                "missing_anchor", "resolve_conflict must quote the conflicting student text"
            )
        if not state.conflict:
            raise QuestionActionRejected(
                "intent_mismatch", f"no recorded conflict for {item_id}"
            )

    return action.model_copy(update={"target_item_id": item_id, "anchor_quote": quote})


def ensure_single_question(text: str) -> str:
    """One line, one question. Adds the two-week window when the model omitted it.

    PHQ-A is a two-week recall instrument: a question without the window is not
    asking the measured thing.
    """
    value = (text or "").strip()
    if not value:
        raise QuestionGenerationUnavailable("question is empty")
    if "\n" in value:
        raise QuestionGenerationUnavailable("question must be a single line")
    if len(re.findall(r"[？?]", value)) != 1:
        raise QuestionGenerationUnavailable("question must contain exactly one question mark")
    if not any(term in value for term in _TWO_WEEK_TERMS):
        value = f"回想过去两周，{value}"
    return value


# ============================================================================
# Interfaces
# ============================================================================


class QuestionDecider(Protocol):
    """Chooses ``QuestionAction``. Replaceable, and the thing future data trains."""

    version: str

    def decide(self, context: DecisionContext) -> QuestionAction: ...


class QuestionGenerator(Protocol):
    """Phrases an already-chosen action. Must not choose a topic or an intent."""

    version: str

    def generate(self, context: DecisionContext, action: QuestionAction) -> str: ...


# ============================================================================
# Offline pair (local runs and tests only)
# ============================================================================


class LocalQuestionDecider:
    """Deterministic offline decider — a test double, not a decision model.

    It exists so the graph, the validator and the API can run without an
    endpoint. It applies the same five intents a model would, in a fixed local
    order; the real order is the model's business.
    """

    version = "local_rule_decider_v1"

    def decide(self, context: DecisionContext) -> QuestionAction:
        pending = list(context.allowed_item_ids)
        if not pending:
            raise QuestionActionRejected("assessment_complete", "no open topic remains")

        conflicts = [item_id for item_id in pending if context.session.items[item_id].conflict]
        if conflicts:
            item_id = conflicts[0]
            return QuestionAction(
                target_item_id=item_id, intent="resolve_conflict",
                anchor_quote=self._quote(context, item_id),
                reason="记录到前后矛盾，先按过去两周确认",
            )

        unclear = [item_id for item_id in pending
                   if context.session.items[item_id].status == "needs_clarification"]
        if unclear:
            item_id = context.current_item_id if context.current_item_id in unclear else unclear[0]
            state = context.session.items[item_id]
            last_period = state.evidence_history[-1].period if state.evidence_history else "past_14_days"
            return QuestionAction(
                target_item_id=item_id,
                intent="clarify_period" if last_period != "past_14_days" else "clarify_frequency",
                anchor_quote=self._quote(context, item_id),
                reason="上一轮该主题没落到过去两周的四档之一",
            )

        mentioned = [item_id for item_id in pending
                     if context.session.items[item_id].status == "mentioned"]
        if mentioned:
            item_id = mentioned[0]
            return QuestionAction(
                target_item_id=item_id, intent="confirm_mention",
                anchor_quote=self._quote(context, item_id),
                reason="学生主动提到该主题，先确认",
            )

        # The topic this answer belonged to is still unresolved: pose it again
        # rather than moving on, so an unclear answer is never silently kept.
        current = context.current_item_id
        if (current in pending and context.session.items[current].asked_once
                and context.session.items[current].status != "confirmed"):
            state = context.session.items[current]
            last_period = state.evidence_history[-1].period if state.evidence_history else "past_14_days"
            return QuestionAction(
                target_item_id=current,
                intent="clarify_period" if last_period != "past_14_days" else "clarify_frequency",
                anchor_quote=self._quote(context, current),
                reason="本轮回答没有把当前主题落到过去两周的四档之一",
            )

        never_asked = [item_id for item_id in pending
                       if not context.session.items[item_id].asked_once]
        if never_asked:
            return QuestionAction(
                target_item_id=never_asked[0], intent="open_topic", anchor_quote="",
                reason="该主题还没有明确问过",
            )

        item_id = pending[0]
        return QuestionAction(
            target_item_id=item_id, intent="clarify_frequency",
            anchor_quote=self._quote(context, item_id),
            reason="仍需确认四档频率",
        )

    @staticmethod
    def _quote(context: DecisionContext, item_id: str) -> str:
        history = context.session.items[item_id].evidence_history
        if history:
            return history[-1].quote
        return ""


class LocalQuestionGenerator:
    """Offline template phrasing. Local runs and tests only."""

    version = "local_template_generator_v1"

    def generate(self, context: DecisionContext, action: QuestionAction) -> str:
        item = BY_ID[action.target_item_id]
        if action.intent == "resolve_conflict":
            return ensure_single_question(
                f"关于{item.label}，前后的回答不一致。以过去两周为准，属于哪一档：{ANSWER_CHOICES}？"
            )
        if action.intent == "clarify_period":
            return ensure_single_question(
                f"关于{item.label}，这里只统计过去两周。{item.question}（{ANSWER_CHOICES}）"
            )
        if action.intent == "clarify_frequency":
            if item.item_id == "item_02":
                return ensure_single_question(
                    f"这里问的是平时喜欢的活动，不只是某一门课。{item.question}（{ANSWER_CHOICES}）"
                )
            return ensure_single_question(
                f"关于{item.label}，请只看过去两周，属于哪一档：{ANSWER_CHOICES}？"
            )
        anchor = (action.anchor_quote or context.latest_text).strip().rstrip("。！？?!")
        if action.intent == "confirm_mention" and anchor and len(anchor) <= 36:
            return ensure_single_question(
                f"你提到“{anchor}”。{item.question}（{ANSWER_CHOICES}）"
            )
        return ensure_single_question(f"{item.question}（{ANSWER_CHOICES}）")


# ============================================================================
# OpenAI-compatible pair
# ============================================================================

_TOPICS = "\n".join(f"{item.item_id}: {item.label}" for item in ITEMS)

_DECIDE_SYSTEM = (
    "你是对话式九项抑郁筛查的提问决策器。根据本轮学生原话、抽取到的证据、"
    "每个主题的 asked_once 与确认状态、当前主题和最近对话，决定下一步问哪个主题、"
    "以及为什么要问。你不写具体问句。\n"
    "可选 intent：\n"
    "  open_topic       ：该主题还没有明确问过，现在开启它\n"
    "  clarify_period   ：该主题的时间窗不清楚（说的不是过去两周，或没说时间）\n"
    "  clarify_frequency：时间窗清楚，但没落到四档频率之一\n"
    "  resolve_conflict ：该主题记录到前后矛盾\n"
    "  confirm_mention  ：学生主动提到该主题，需要确认\n"
    "必须遵守：\n"
    "1. target_item_id 必须在 allowed_item_ids 中；已确认且已问过的主题不要重复问。\n"
    "2. confirm_mention 与 resolve_conflict 必须给出 anchor_quote，且必须是学生原话的"
    "逐字连续片段，取自 latest_student_answer 或该主题的 latest_evidence。\n"
    "3. open_topic 只能用于 asked_once=false 的主题；clarify_period 与 clarify_frequency"
    "只能用于 asked_once=true 的主题。\n"
    "4. 由你判断此刻哪个主题最值得问：不要套用固定顺序，不必按条目编号推进。\n"
    "5. 只输出 JSON 对象："
    '{"target_item_id":"item_03","intent":"clarify_frequency",'
    '"anchor_quote":"睡不好","reason":"..."}。\n'
    "九个主题：\n" + _TOPICS
)

_PHRASE_SYSTEM = (
    "你是访谈提问模块。主题和提问意图已经选定，你只负责把它写成一句自然、具体的中文问题。\n"
    "必须遵守：\n"
    "1. 只写一句问题，句中只能出现一个问号；不要写成『有没有……？有多少天……？』"
    "这样的两个问句。不要换主题、不要改变提问意图。\n"
    "2. 必须限定「过去两周」，语言与学生年级相称。\n"
    "3. 可以引用学生刚才的具体原话，但不能把没有说过的经历写成事实。\n"
    "4. 不诊断、不计分、不诱导；一次只问一件事。\n"
    '只返回 JSON 对象：{"question":"...？"}。'
)

_THINKING_MODES = {"default", "enabled", "disabled"}


class _PhrasedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


def _post_json(
    client: httpx.Client, *, base_url: str, api_key: str, thinking_mode: str,
    model: str, temperature: float, max_tokens: int, system: str, user: str,
) -> str:
    """One structured JSON call. Keeps request shaping in a single place."""
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if thinking_mode != "default":
        payload["thinking"] = {"type": thinking_mode}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
    response.raise_for_status()
    choice = response.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("truncated model output")
    content = choice["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("message content is not a string")
    return content


class OpenAICompatibleQuestionDecider:
    """Decision model over an OpenAI-compatible ``/chat/completions`` endpoint.

    Temperature 0: picking a topic is a judgement, not a wording task. The
    chosen action is still validated by :func:`validate_question_action`.
    """

    def __init__(
        self, base_url: str, model: str, api_key: str = "", *,
        thinking_mode: str = "default", client: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip() or not model.strip():
            raise ValueError("ASSESSMENT_LLM_BASE_URL and ASSESSMENT_LLM_MODEL are required")
        if thinking_mode not in _THINKING_MODES:
            raise ValueError("ASSESSMENT_LLM_THINKING must be default, enabled, or disabled")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.thinking_mode = thinking_mode
        self.client = client or httpx.Client(timeout=30.0)
        self.version = f"openai_compatible_decider_v1:{model}"

    def decide(self, context: DecisionContext) -> QuestionAction:
        try:
            content = _post_json(
                self.client, base_url=self.base_url, api_key=self.api_key,
                thinking_mode=self.thinking_mode, model=self.model, temperature=0,
                max_tokens=256, system=_DECIDE_SYSTEM,
                user=json.dumps(context.payload(), ensure_ascii=False),
            )
            return QuestionAction.model_validate_json(content)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            raise QuestionGenerationUnavailable("Question decision failed") from exc


class OpenAICompatibleQuestionGenerator:
    """Phrasing model. Receives one chosen action and writes one question.

    It is not shown the topic list, so it cannot quietly pick a different topic;
    the engine additionally checks the returned wording's shape.
    """

    def __init__(
        self, base_url: str, model: str, api_key: str = "", *,
        thinking_mode: str = "default", client: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip() or not model.strip():
            raise ValueError("ASSESSMENT_LLM_BASE_URL and ASSESSMENT_LLM_MODEL are required")
        if thinking_mode not in _THINKING_MODES:
            raise ValueError("ASSESSMENT_LLM_THINKING must be default, enabled, or disabled")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.thinking_mode = thinking_mode
        self.client = client or httpx.Client(timeout=30.0)
        self.version = f"openai_compatible_generator_v1:{model}"

    def generate(self, context: DecisionContext, action: QuestionAction) -> str:
        item = BY_ID[action.target_item_id]
        state = context.session.items[item.item_id]
        request = {
            "chosen_action": {
                "target_item_id": item.item_id,
                "intent": action.intent,
                "intent_zh": INTENT_LABELS[action.intent],
                "anchor_quote": action.anchor_quote,
                "reason": action.reason,
            },
            "topic_label": item.label,
            "topic_status": state.status,
            "conflict": state.conflict,
            "latest_student_answer": context.latest_text,
            "latest_evidence": [event.quote for event in state.evidence_history[-2:]],
            "recent_turns": [
                {"student": turn.user_text, "assistant": turn.assistant_text}
                for turn in context.session.turns[-3:]
            ],
        }
        try:
            content = _post_json(
                self.client, base_url=self.base_url, api_key=self.api_key,
                thinking_mode=self.thinking_mode, model=self.model, temperature=0.5,
                max_tokens=256, system=_PHRASE_SYSTEM,
                user=json.dumps(request, ensure_ascii=False),
            )
            question = _PhrasedQuestion.model_validate_json(content).question
            return ensure_single_question(question)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            raise QuestionGenerationUnavailable("Question phrasing failed") from exc


def build_question_pipeline_from_env() -> tuple[QuestionDecider, QuestionGenerator]:
    """Build independently configured decision and phrasing models."""
    provider = os.getenv("ASSESSMENT_QUESTION_GENERATOR", "mock").strip().lower()
    if provider == "mock":
        return LocalQuestionDecider(), LocalQuestionGenerator()
    if provider == "openai_compatible":
        def settings_for(role: str) -> dict[str, str]:
            return {
                "base_url": os.getenv(
                    f"ASSESSMENT_{role}_BASE_URL", os.getenv("ASSESSMENT_LLM_BASE_URL", "")
                ),
                "model": os.getenv(
                    f"ASSESSMENT_{role}_MODEL", os.getenv("ASSESSMENT_LLM_MODEL", "")
                ),
                "api_key": os.getenv(
                    f"ASSESSMENT_{role}_API_KEY", os.getenv("ASSESSMENT_LLM_API_KEY", "")
                ),
                "thinking_mode": os.getenv(
                    f"ASSESSMENT_{role}_THINKING",
                    os.getenv("ASSESSMENT_LLM_THINKING", "default"),
                ).strip().lower(),
            }

        return (
            OpenAICompatibleQuestionDecider(**settings_for("DECIDER")),
            OpenAICompatibleQuestionGenerator(**settings_for("GENERATOR")),
        )
    raise ValueError(f"Unsupported ASSESSMENT_QUESTION_GENERATOR: {provider}")
