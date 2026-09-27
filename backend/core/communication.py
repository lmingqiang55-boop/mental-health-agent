"""学生与心理老师双向互动沟通（C 模块）。

对应目标图「双向互动沟通」：结果反馈、问题咨询、建议互动、持续跟进。
与 AI 对话消息分开存储，老师人工消息不得冒充 AI 回复。
"""

from threading import RLock
from uuid import uuid4

from backend.models.assessment import CommunicationMessage


class CommunicationStore:
    def __init__(self) -> None:
        self._messages: dict[str, CommunicationMessage] = {}
        self._by_student: dict[str, list[str]] = {}
        self._lock = RLock()

    def send(self, student_ref: str, direction: str, content: str,
             counselor_ref: str | None = None) -> CommunicationMessage:
        message = CommunicationMessage(
            message_id=str(uuid4()),
            student_ref=student_ref,
            counselor_ref=counselor_ref,
            direction=direction,
            content=content,
        )
        with self._lock:
            self._messages[message.message_id] = message
            self._by_student.setdefault(student_ref, []).append(
                message.message_id)
        return message

    def list_for_student(self, student_ref: str) -> list[CommunicationMessage]:
        with self._lock:
            ids = self._by_student.get(student_ref, [])
            return [self._messages[i].model_copy(deep=True)
                    for i in ids if i in self._messages]

    def mark_read(self, student_ref: str) -> None:
        with self._lock:
            for mid in self._by_student.get(student_ref, []):
                message = self._messages.get(mid)
                if message:
                    message.read = True


communication_store = CommunicationStore()
