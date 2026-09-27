from backend.core.multimodal_fusion import fuse
from backend.core.risk_engine import assess_risk
from backend.llm.client import LLMClient
from backend.models.response import DialogueResponse
from backend.models.states import AudioState, SessionState, VisionState
from backend.rag.retriever import retrieve


DIMENSIONS = ("mood", "interest", "sleep", "energy", "concentration", "duration")
TOPIC_CLUES = {
    "mood": ("心情", "情绪", "低落", "难过"),
    "interest": ("兴趣", "喜欢", "不想做"),
    "sleep": ("睡", "失眠"),
    "energy": ("精力", "精神", "疲惫", "累"),
    "concentration": ("注意力", "集中", "专注"),
    "duration": ("多久", "持续", "周", "个月", "开始"),
}


class DialogueManager:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def process_turn(
        self,
        user_text: str,
        session_state: SessionState,
        vision_state: VisionState | None = None,
        audio_state: AudioState | None = None,
    ) -> DialogueResponse:
        fused = fuse(user_text, vision_state, audio_state)
        risk = assess_risk(fused.user_text)
        session_state.latest_risk = risk

        if risk.requires_intervention:
            return DialogueResponse(
                reply="听起来你现在可能很难受。请尽快联系身边可信任的人、当地急救服务或专业危机支持，确保自己此刻有人陪伴。",
                next_strategy="follow_up", current_stage=session_state.current_stage, risk=risk,
            )

        if session_state.current_stage == "completed":
            strategy = "follow_up"
        else:
            active = next((name for name in DIMENSIONS
                           if session_state.assessment_state[name] == "in_progress"), None)
            is_vague = user_text.strip().lower() in {"嗯", "哦", "好", "不知道", "不清楚", "yes", "no"}
            if active and is_vague:
                strategy = "clarify_answer"
            else:
                if active:
                    session_state.assessment_state[active] = "covered"
                # The first spontaneous answer can cover one clear topic.
                if session_state.turn_count == 0:
                    for dimension, clues in TOPIC_CLUES.items():
                        if any(clue in user_text for clue in clues):
                            session_state.assessment_state[dimension] = "covered"
                            break
                next_dimension = next((name for name in DIMENSIONS
                                       if session_state.assessment_state[name] == "pending"), None)
                if next_dimension:
                    session_state.assessment_state[next_dimension] = "in_progress"
                    strategy = f"explore_{next_dimension}"
                else:
                    session_state.current_stage = "completed"
                    strategy = "finish_assessment"

        context = retrieve(f"{user_text} {strategy}")
        reply = self.llm_client.generate_reply(
            user_text, strategy, context, session_state.conversation_history
        )
        return DialogueResponse(reply=reply, next_strategy=strategy,
                                current_stage=session_state.current_stage, risk=risk)
