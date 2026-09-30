from backend.llm.client import LLMClient
from backend.models.response import DialogueResponse
from backend.models.states import AudioState, SessionState, VisionState
from backend.policy.client import get_policy_client
from backend.policy.topic_constraint import topic_constraint


class DialogueManager:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self._policy = get_policy_client()
        self._constraint = topic_constraint
        self._constrained_session_id: str | None = None

    def process_turn(
        self,
        user_text: str,
        session_state: SessionState,
        vision_state: VisionState | None = None,
        audio_state: AudioState | None = None,
    ) -> DialogueResponse:
        decision = self._policy.predict(session_state.conversation_history)
        # The demo starts a new assessment with a new session, so the topic
        # counter is cleared on the first turn of each session. It is a single
        # in-process counter and is therefore not parallel-session safe.
        if (session_state.turn_count == 0
                or session_state.session_id != self._constrained_session_id):
            self._constraint.reset()
            self._constrained_session_id = session_state.session_id
        actions = self._constraint.apply([action.value for action in decision.actions])
        # The reply generator remains on its temporary follow_up fallback.
        strategy = "follow_up"
        reply = self.llm_client.generate_reply(
            user_text, strategy, [], session_state.conversation_history
        )
        return DialogueResponse(
            reply=reply,
            next_strategy=" -> ".join(actions),
            current_stage=session_state.current_stage,
            actions=actions,
        )
