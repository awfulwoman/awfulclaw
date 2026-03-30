"""Tests for module_generator module."""

from __future__ import annotations

from pathlib import Path

import pytest

from awfulclaw.modules.module_generator import create_module
from awfulclaw.modules.module_generator._module_generator import (
    ModuleGeneratorModule,
    substitute,
)


def _dispatch(tag: str) -> str:
    mod = ModuleGeneratorModule()
    skill_tag = mod.skill_tags[0]
    m = skill_tag.pattern.search(tag)
    assert m is not None, f"Tag did not match: {tag!r}"
    return mod.dispatch(m, [], "")


def test_create_module() -> None:
    mod = create_module()
    assert mod.name == "module_generator"
    assert mod.is_available() is True
    assert len(mod.skill_tags) == 1


def test_dispatch_generates_module_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from awfulclaw.modules.module_generator import _module_generator as mg

    monkeypatch.setattr(mg, "_MODULES_DIR", tmp_path)

    result = _dispatch(
        '<skill:create_module name="weather" description="fetch weather">'
        "gets weather data</skill:create_module>"
    )
    assert "created" in result.lower()
    assert "weather" in result

    pkg_dir = tmp_path / "weather"
    assert (pkg_dir / "__init__.py").exists()
    assert (pkg_dir / "_weather.py").exists()
    assert (pkg_dir / "test_weather.py").exists()


def test_dispatch_generated_files_have_substitutions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from awfulclaw.modules.module_generator import _module_generator as mg

    monkeypatch.setattr(mg, "_MODULES_DIR", tmp_path)

    _dispatch(
        '<skill:create_module name="mymod" description="my module">some docs</skill:create_module>'
    )

    init_content = (tmp_path / "mymod" / "__init__.py").read_text()
    assert "MymodModule" in init_content
    assert "mymod" in init_content

    impl_content = (tmp_path / "mymod" / "_mymod.py").read_text()
    assert "MYMOD" in impl_content
    assert "MymodModule" in impl_content

    test_content = (tmp_path / "mymod" / "test_mymod.py").read_text()
    assert "mymod" in test_content


def test_dispatch_generated_module_is_importable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generated __init__.py and impl can be imported as Python."""
    import ast

    from awfulclaw.modules.module_generator import _module_generator as mg

    monkeypatch.setattr(mg, "_MODULES_DIR", tmp_path)

    _dispatch('<skill:create_module name="testmod" description="test">docs</skill:create_module>')

    # Verify files are syntactically valid Python
    for fname in ["__init__.py", "_testmod.py", "test_testmod.py"]:
        source = (tmp_path / "testmod" / fname).read_text()
        ast.parse(source)  # raises SyntaxError if invalid


def test_dispatch_rejects_invalid_name() -> None:
    result = _dispatch('<skill:create_module name="123bad" description="x">y</skill:create_module>')
    assert "error" in result.lower() or "invalid" in result.lower()


def test_dispatch_rejects_existing_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from awfulclaw.modules.module_generator import _module_generator as mg

    monkeypatch.setattr(mg, "_MODULES_DIR", tmp_path)

    existing = tmp_path / "existing"
    existing.mkdir()

    result = _dispatch(
        '<skill:create_module name="existing" description="x">y</skill:create_module>'
    )
    assert "already exists" in result


def test_substitute() -> None:
    result = substitute("{{module_name}} {{ModuleName}} {{MODULE_NAME}}", "foo", "desc", "docs")
    assert result == "foo Foo FOO"


def test_is_available_true_when_template_exists() -> None:
    mod = ModuleGeneratorModule()
    assert mod.is_available() is True
