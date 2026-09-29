from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.assessment.bank import CATEGORY_SCORE
from backend.assessment.extractor import (
    EvidenceCandidate, EvidenceExtractor, build_extractor_from_env,
    safety_signal, validate_candidate,
)
from backend.assessment.models import (
    AssessmentSession, EvidenceEvent, SelectedAction, TurnRecord, pending_item_ids,
)
from backend.assessment.question_generator import (
    DecisionContext, QuestionAction, QuestionDecider, QuestionGenerator,
    build_question_pipeline_from_env, ensure_single_question,
    validate_question_action,
)


STOP_PHRASES = ("先到这里", "不想继续", "结束测评", "停止测评", "不测了")
SAFETY_REPLY = (
    "测评先暂停。你提到了可能伤害自己的想法，请现在联系身边可信任的人，"
    "并尽快寻求当地急救服务或专业人员的帮助。"
)
COMPLETE_REPLY = "九项回答已记录完毕。你现在可以查看本次结果。"


class TurnGraphState(TypedDict, total=False):
    session: AssessmentSession
    user_text: str
    initial: bool
    target_item_id: str | None
    turn_id: int
    candidates: list[EvidenceCandidate]
    touched: list[str]
    decision_context: DecisionContext
    action: QuestionAction
    reply: str
    done: bool


class AssessmentEngine:
    """One screening turn as an explicit node chain.

    提取证据 → 更新状态 → 模型选择动作 → 生成问句 → 记录

    ``extract`` → ``apply`` → ``decide`` → ``phrase`` → ``record`` (with
    ``guard`` in front for safety and stop phrases). The model chooses the topic
    and the intent in ``decide``; ``phrase`` only writes the wording; the program
    between them validates legality and nothing else.
    """

    def __init__(
        self, extractor: EvidenceExtractor | None = None,
        question_generator: QuestionGenerator | None = None,
        question_decider: QuestionDecider | None = None,
    ) -> None:
        self.extractor = extractor if extractor is not None else build_extractor_from_env()
        default_decider, default_generator = build_question_pipeline_from_env()
        self.question_decider = question_decider if question_decider is not None else default_decider
        self.question_generator = (
            question_generator if question_generator is not None else default_generator
        )
        graph = StateGraph(TurnGraphState)
        graph.add_node("guard", self._guard)
        graph.add_node("extract", self._extract)
        graph.add_node("apply", self._apply)
        graph.add_node("decide", self._decide)
        graph.add_node("phrase", self._phrase)
        graph.add_node("record", self._record)
        graph.add_edge(START, "guard")
        graph.add_conditional_edges("guard", lambda state: "record" if state.get("done") else (
            "decide" if state.get("initial") else "extract"
        ))
        graph.add_edge("extract", "apply")
        graph.add_conditional_edges("apply", lambda state: "record" if state.get("done") else "decide")
        graph.add_conditional_edges("decide", lambda state: "record" if state.get("done") else "phrase")
        graph.add_edge("phrase", "record")
        graph.add_edge("record", END)
        self.graph = graph.compile()

    def start(self, grade: int | None = None) -> tuple[AssessmentSession, str]:
        state = AssessmentSession(grade=grade, extractor_version=self.extractor.version)
        result = self.graph.invoke({"session": state, "user_text": "", "initial": True})
        return result["session"], result["reply"]

    def process(self, original: AssessmentSession, user_text: str) -> tuple[AssessmentSession, str]:
        if original.status != "in_progress":
            raise ValueError("assessment is closed")
        text = user_text.strip()
        if not text:
            raise ValueError("answer is blank")
        result = self.graph.invoke({
            "session": original.model_copy(deep=True), "user_text": text, "initial": False,
        })
        return result["session"], result["reply"]

    # --- 节点 ---------------------------------------------------------------

    @staticmethod
    def _guard(graph_state: TurnGraphState) -> TurnGraphState:
        state = graph_state["session"]
        if graph_state.get("initial"):
            return {"target_item_id": None, "turn_id": 0, "done": False}
        text = graph_state["user_text"]
        target = state.current_item_id
        turn_id = len(state.turns) + 1
        if safety_signal(text) == "urgent":
            state.safety_flag = "urgent"
            state.status = "safety_paused"
            state.current_item_id = None
            return {"session": state, "target_item_id": target, "turn_id": turn_id,
                    "reply": SAFETY_REPLY, "done": True}
        if any(phrase in text for phrase in STOP_PHRASES):
            state.status = "stopped"
            state.current_item_id = None
            return {"session": state, "target_item_id": target, "turn_id": turn_id,
                    "reply": "已停止本次测评；未完成的条目不会计为零分。", "done": True}
        return {"target_item_id": target, "turn_id": turn_id, "done": False}

    def _extract(self, graph_state: TurnGraphState) -> TurnGraphState:
        candidates = self.extractor.extract(
            graph_state["user_text"], graph_state["target_item_id"],
        )
        return {"candidates": candidates}

    @staticmethod
    def _apply(graph_state: TurnGraphState) -> TurnGraphState:
        state = graph_state["session"]
        text = graph_state["user_text"]
        target = graph_state["target_item_id"]
        turn_id = graph_state["turn_id"]
        touched: list[str] = []
        for candidate in graph_state["candidates"]:
            validated = validate_candidate(candidate, text, target)
            if validated is None:
                continue
            AssessmentEngine._apply_candidate(state, validated, turn_id, target)
            touched.append(validated.item_id)

        if safety_signal(text) == "needs_review" or (
            state.items["item_09"].status == "confirmed"
            and (state.items["item_09"].score or 0) > 0
        ):
            state.safety_flag = "needs_review"
            state.status = "safety_paused"
            state.current_item_id = None
            return {"session": state, "touched": touched, "reply": SAFETY_REPLY, "done": True}
        return {"session": state, "touched": touched, "done": False}

    def _decide(self, graph_state: TurnGraphState) -> TurnGraphState:
        """The model picks the topic and the intent; the program only validates.

        Completion is decided here, not proposed by the model: while any of the
        nine topics is unconfirmed or was never explicitly asked, the assessment
        cannot end.
        """
        state = graph_state["session"]
        pending = pending_item_ids(state)
        if not pending:
            state.status = "complete"
            state.current_item_id = None
            return {"session": state, "reply": COMPLETE_REPLY, "done": True}

        context = DecisionContext(
            session=state,
            allowed_item_ids=tuple(pending),
            latest_text=graph_state["user_text"],
            evidence=tuple(graph_state.get("candidates", ())),
            accepted_item_ids=tuple(graph_state.get("touched", ())),
        )
        action = validate_question_action(self.question_decider.decide(context), context)
        return {"decision_context": context, "action": action, "done": False}

    def _phrase(self, graph_state: TurnGraphState) -> TurnGraphState:
        """Write one question for the already-selected action."""
        state = graph_state["session"]
        action = graph_state["action"]
        question = ensure_single_question(
            self.question_generator.generate(graph_state["decision_context"], action)
        )
        state.current_item_id = action.target_item_id
        state.items[action.target_item_id].asked_once = True
        return {"session": state, "reply": question}

    def _record(self, graph_state: TurnGraphState) -> TurnGraphState:
        """Log the selected action, then close the turn."""
        state = graph_state["session"]
        action = graph_state.get("action")
        if action is not None:
            state.action_log.append(SelectedAction(
                turn_id=graph_state.get("turn_id", 0),
                item_id=action.target_item_id,
                intent=action.intent,
                anchor_quote=action.anchor_quote,
                reason=action.reason,
                decider_version=getattr(self.question_decider, "version", ""),
                question=graph_state.get("reply", ""),
            ))
        if graph_state.get("initial"):
            return {"session": state}
        finished, _ = AssessmentEngine._finish_turn(
            state, graph_state["turn_id"], graph_state["target_item_id"],
            graph_state["user_text"], graph_state["reply"],
        )
        return {"session": finished}

    # --- 状态更新 -----------------------------------------------------------

    @staticmethod
    def _apply_candidate(
        state: AssessmentSession, candidate: EvidenceCandidate, turn_id: int, target: str | None
    ) -> None:
        item = state.items[candidate.item_id]
        event = EvidenceEvent(
            turn_id=turn_id,
            quote=candidate.quote,
            period=candidate.period,
            proposed_category=candidate.category,
        )
        item.evidence_history.append(event)

        if candidate.period != "past_14_days":
            event.reason = "outside_or_unknown_period"
            if candidate.item_id == target and item.status != "confirmed":
                item.status = "needs_clarification"
            elif item.status == "unasked":
                item.status = "mentioned"
            return

        if candidate.category is None:
            event.reason = "frequency_not_confirmed"
            if item.status != "confirmed":
                item.status = "needs_clarification" if candidate.item_id == target else "mentioned"
            return

        if item.status == "confirmed" and item.category != candidate.category:
            event.reason = "conflicts_with_prior_answer"
            item.status = "needs_clarification"
            item.conflict = True
            item.category = None
            item.score = None
            item.evidence_quote = None
            item.evidence_turn_id = None
            item.period = None
            item.confirmed_by_user = False
            return

        event.accepted = True
        item.status = "confirmed"
        item.category = candidate.category
        item.score = CATEGORY_SCORE[candidate.category]
        item.evidence_quote = candidate.quote
        item.evidence_turn_id = turn_id
        item.period = "past_14_days"
        item.confirmed_by_user = True
        item.conflict = False

    @staticmethod
    def _finish_turn(
        state: AssessmentSession, turn_id: int, target: str | None, text: str, reply: str
    ) -> tuple[AssessmentSession, str]:
        state.turns.append(TurnRecord(
            turn_id=turn_id, target_item_id=target,
            user_text=text, assistant_text=reply,
        ))
        state.updated_at = datetime.now(timezone.utc)
        return state, reply
