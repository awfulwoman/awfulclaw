"""Module ABC and SkillTag dataclass for the awfulclaw module system."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol


@dataclass
class SkillTag:
    name: str
    pattern: re.Pattern[str]
    description: str
    usage: str


class ToolMatcher(Protocol):
    """Protocol for pluggable tool dispatch matchers."""

    def match(self, reply: str) -> re.Match[str] | None:
        """Return a match if this tool should fire, or None."""
        ...

    def execute(
        self,
        match: re.Match[str],
        reply: str,
        history: list[dict[str, str]],
        system: str,
    ) -> str:
        """Execute the tool. Return the cleaned reply text to pass back to Claude."""
        ...


class SkillTagMatcher:
    """Wraps a Module + SkillTag pair as a ToolMatcher."""

    def __init__(self, module: Module, skill_tag: SkillTag) -> None:
        self._module = module
        self._skill_tag = skill_tag

    def match(self, reply: str) -> re.Match[str] | None:
        return self._skill_tag.pattern.search(reply)

    def execute(
        self,
        match: re.Match[str],
        reply: str,
        history: list[dict[str, str]],
        system: str,
    ) -> str:
        """Strip the tag, dispatch to module, update history. Returns cleaned reply."""
        cleaned = self._skill_tag.pattern.sub("", reply, count=1).strip()
        result_text = self._module.dispatch(match, history, system)
        history.append({"role": "assistant", "content": cleaned})
        history.append({"role": "user", "content": result_text})
        return cleaned


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
