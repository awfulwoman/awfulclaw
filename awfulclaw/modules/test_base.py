"""Tests for Module ABC and SkillTag dataclass."""

from __future__ import annotations

import re

import pytest

from awfulclaw.modules.base import Module, SkillTag


class ConcreteModule(Module):
    @property
    def name(self) -> str:
        return "test"

    @property
    def skill_tags(self) -> list[SkillTag]:
        return [
            SkillTag(
                name="test",
                pattern=re.compile(r"<skill:test\s*/>"),
                description="A test skill",
                usage="<skill:test/>",
            )
        ]

    @property
    def system_prompt_fragment(self) -> str:
        return "### TEST\nUse `<skill:test/>` for testing."

    def dispatch(self, tag_match: re.Match[str], history: list[dict[str, str]], system: str) -> str:
        return "[test result]"


def test_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Module()  # type: ignore[abstract]


def test_concrete_subclass_works():
    mod = ConcreteModule()
    assert mod.name == "test"
    assert len(mod.skill_tags) == 1
    assert mod.skill_tags[0].name == "test"
    assert mod.system_prompt_fragment.startswith("### TEST")
    assert mod.is_available() is True


def test_dispatch_returns_text():
    mod = ConcreteModule()
    m = mod.skill_tags[0].pattern.match("<skill:test/>")
    assert m is not None
    result = mod.dispatch(m, [], "")
    assert result == "[test result]"


def test_skill_tag_fields():
    tag = SkillTag(
        name="foo",
        pattern=re.compile(r"<skill:foo/>"),
        description="foo skill",
        usage="<skill:foo/>",
    )
    assert tag.name == "foo"
    assert tag.description == "foo skill"
    assert tag.usage == "<skill:foo/>"
    assert tag.pattern.match("<skill:foo/>") is not None
