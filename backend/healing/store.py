"""Serialized companionship with bounded caches and durable recovery snapshots."""

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

from backend.models.healing import HealingState
from backend.models.states import _now


@dataclass
class HealingSlot:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    state: HealingState | None = None
    start_receipts: dict = field(default_factory=dict)
    touched_at: object = field(default_factory=_now)


class HealingStore:
    def __init__(self, max_sessions=1000, ttl=timedelta(hours=2), archive=None):
        self.archive = archive
        self.slots: dict[str, HealingSlot] = {}
        self.max_sessions = max_sessions
        self.ttl = ttl

    def slot(self, session_id: str) -> HealingSlot:
        now = _now()
        for key, value in list(self.slots.items()):
            if not value.lock.locked() and now - value.touched_at > self.ttl:
                self.slots.pop(key, None)
        if session_id not in self.slots:
            if len(self.slots) >= self.max_sessions:
                unlocked = [(key, value) for key, value in self.slots.items() if not value.lock.locked()]
                if not unlocked:
                    raise RuntimeError("陪伴服务繁忙，请稍后重试")
                self.slots.pop(min(unlocked, key=lambda pair: pair[1].touched_at)[0])
            self.slots[session_id] = HealingSlot()
            saved = self.archive.load_healing(session_id) if self.archive is not None else None
            if saved is not None:
                self.slots[session_id].state = HealingState.model_validate(saved["state"])
                self.slots[session_id].start_receipts = saved["receipts"]
        slot = self.slots[session_id]
        slot.touched_at = now
        return slot

    def persist(self, session_id, slot):
        if self.archive is not None and slot.state is not None:
            self.archive.save_healing(session_id, slot.state, slot.start_receipts)

    def delete_sessions(self, session_ids: list[str]) -> int:
        """删除与已撤销筛查会话关联的临时陪伴状态。"""
        deleted = 0
        for session_id in session_ids:
            if self.slots.pop(session_id, None) is not None:
                deleted += 1
        return deleted


from backend.core.conversation_archive import conversation_archive

healing_store = HealingStore(archive=conversation_archive)
