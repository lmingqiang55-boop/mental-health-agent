import os

from backend.llm.prompts import QUESTIONS
from backend.models.states import Message


class LLMClient:
    """Stable generation interface; v0.1 intentionally supports mock only."""

    def __init__(self) -> None:
        provider = os.getenv("LLM_PROVIDER", "mock").lower()
        if provider != "mock":
            raise ValueError("v0.1 only supports LLM_PROVIDER=mock")

    def generate_reply(
        self,
        user_text: str,
        strategy: str,
        retrieved_context: list[str],
        conversation_history: list[Message],
    ) -> str:
        # The context and history are kept in the interface for future providers.
        return QUESTIONS.get(strategy, QUESTIONS["follow_up"])
