from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class Verdict(Enum):
    approved = "approved"
    rejected = "rejected"
    escalated = "escalated"


class Handler(ABC):
    @abstractmethod
    async def check(self, write_type: str, proposed_value: str) -> Verdict: ...
