"""Per-session serialization and atomic commits for ephemeral companionship."""

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
    def __init__(self, max_sessions=1000, ttl=timedelta(hours=2)):
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
        slot = self.slots[session_id]
        slot.touched_at = now
        return slot


healing_store = HealingStore()
