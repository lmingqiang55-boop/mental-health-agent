"""单轮访谈节点：每轮决策一次，共用后端覆盖门槛后再接受模型结束。"""

from backend.core.dialogue_manager import (
    DialogueManager, closing_payload, ensure_screening_open,
    finalize_visual_feedback, open_payload, resolve_current_vision,
    select_visual_channels,
)
from backend.core.screening_flow import adopt_decision, completion_reason, record_answer
from backend.graph.state import TurnState

CLOSING_PATH = ("prepare_turn", "closing_check", "dialogue_close", "commit")
OPEN_DECIDED_PATH = ("prepare_turn", "closing_check", "decision", "resolve_target",
                     "visual_prepare", "dialogue_execute", "commit")
MODEL_CLOSING_PATH = ("prepare_turn", "closing_check", "decision", "dialogue_close", "commit")


class TurnNodes:
    def __init__(self, manager: DialogueManager) -> None:
        self._manager = manager

    def prepare_turn(self, state: TurnState) -> dict:
        session = state["session"]
        current_vision = resolve_current_vision(
            session, state.get("vision_snapshot"), state.get("use_latest_states", True))
        ensure_screening_open(session)
        record_answer(session)
        return {"current_vision": current_vision}

    def closing_check(self, state: TurnState) -> dict:
        return {"ending": completion_reason(state["session"], state["user_text"])}

    @staticmethod
    def route_after_closing(state: TurnState) -> str:
        return "closing" if state.get("ending") is not None else "open"

    def decision(self, state: TurnState) -> dict:
        decision = self._manager.decide(state["session"])
        return {"decision": decision,
                "ending": "model_finished" if decision.is_finished else None}

    def resolve_target(self, state: TurnState) -> dict:
        adopt_decision(state["session"], state["decision"])
        return {}

    def visual_prepare(self, state: TurnState) -> dict:
        channels = select_visual_channels(
            state["session"], state.get("utterance_id"),
            state.get("current_vision"), state["user_text"])
        return {"channels": channels}

    def dialogue_execute(self, state: TurnState) -> dict:
        channels = state["channels"]
        response = self._manager.reply_for_decision(
            state["session"], state["user_text"], state.get("current_vision"),
            state["decision"], channels)
        finalize_visual_feedback(state["session"], channels, response.reply)
        return {"response": response, "visual_feedback": channels.feedback}

    def dialogue_close(self, state: TurnState) -> dict:
        response = self._manager.closing_reply(
            state["user_text"], state["session"], state.get("current_vision"), state["ending"])
        return {"response": response}

    def commit(self, state: TurnState) -> dict:
        if state.get("ending") is not None:
            payload = closing_payload(state["session"], state["response"], state["ending"])
        else:
            payload = open_payload(
                state["session"], state["response"],
                state["decision"].target_label, state["visual_feedback"])
        return {"payload": payload}
