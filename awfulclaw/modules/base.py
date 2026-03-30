"""Module ABC and SkillTag dataclass for the awfulclaw module system."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SkillTag:
    name: str
    pattern: re.Pattern[str]
    description: str
    usage: str


class Module(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique module name, e.g. 'web', 'imap'."""

    @property
    @abstractmethod
    def skill_tags(self) -> list[SkillTag]:
        """Skill tags this module handles."""

    @property
    @abstractmethod
    def system_prompt_fragment(self) -> str:
        """Documentation injected into system prompt when module is active."""

    @abstractmethod
    def dispatch(self, tag_match: re.Match[str], history: list[dict[str, str]], system: str) -> str:
        """Process a matched skill tag. Return result text to inject as a user message."""

    def is_available(self) -> bool:
        """Return True if this module's dependencies are met. Default: True."""
        return True
