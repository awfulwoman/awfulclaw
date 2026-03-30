"""Module ABC for awfulclaw hook modules."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Module(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique module name, e.g. 'briefing', 'startup_briefing'."""

    def is_available(self) -> bool:
        """Return True if this module's dependencies are met. Default: True."""
        return True
