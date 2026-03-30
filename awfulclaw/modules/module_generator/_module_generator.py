"""Module generator — creates new modules from templates."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from awfulclaw.modules.base import Module, SkillTag

logger = logging.getLogger(__name__)

_SKILL_CREATE_MODULE_RE = re.compile(
    r'<skill:create_module\s+name="([^"]+)"\s+description="([^"]*)"[^>]*>(.*?)</skill:create_module>',
    re.DOTALL,
)

_TEMPLATE_DIR = Path(__file__).parent.parent / "_template"
_MODULES_DIR = Path(__file__).parent.parent


def _pascal_case(name: str) -> str:
    """Convert snake_case or lowercase to PascalCase."""
    return "".join(word.capitalize() for word in re.split(r"[_\-\s]+", name))


def substitute(template: str, module_name: str, description: str, documentation: str) -> str:
    module_upper = module_name.upper()
    module_pascal = _pascal_case(module_name)
    return (
        template.replace("{{MODULE_NAME}}", module_upper)
        .replace("{{module_name}}", module_name)
        .replace("{{ModuleName}}", module_pascal)
        .replace("{{description}}", description)
        .replace("{{documentation}}", documentation)
    )


class ModuleGeneratorModule(Module):
    @property
    def name(self) -> str:
        return "module_generator"

    @property
    def skill_tags(self) -> list[SkillTag]:
        return [
            SkillTag(
                name="create_module",
                pattern=_SKILL_CREATE_MODULE_RE,
                description="Generate a new module from the template",
                usage=(
                    '<skill:create_module name="..." description="...">'
                    "implementation details</skill:create_module>"
                ),
            )
        ]

    @property
    def system_prompt_fragment(self) -> str:
        return """\
### Module Generator
Create a new module from the built-in template with:
```
<skill:create_module name="module_name" description="one-line description">
implementation details / documentation
</skill:create_module>
```
This writes `awfulclaw/modules/<name>/` with `__init__.py`, `_<name>.py`, and `test_<name>.py`.
The module is hot-reloaded on the next idle tick."""

    def dispatch(self, tag_match: re.Match[str], history: list[dict[str, str]], system: str) -> str:
        module_name = tag_match.group(1).strip().lower().replace("-", "_").replace(" ", "_")
        description = tag_match.group(2).strip()
        documentation = tag_match.group(3).strip()

        if not re.match(r"^[a-z][a-z0-9_]*$", module_name):
            return f"[Module generator error: invalid module name '{module_name}']"

        target_dir = _MODULES_DIR / module_name
        if target_dir.exists():
            return f"[Module generator: '{module_name}' already exists at {target_dir}]"

        # Read templates
        init_template = (_TEMPLATE_DIR / "__init__.py.template").read_text(encoding="utf-8")
        impl_template = (_TEMPLATE_DIR / "_impl.py.template").read_text(encoding="utf-8")
        test_template = (_TEMPLATE_DIR / "test.py.template").read_text(encoding="utf-8")

        # Substitute placeholders
        init_content = substitute(init_template, module_name, description, documentation)
        impl_content = substitute(impl_template, module_name, description, documentation)
        test_content = substitute(test_template, module_name, description, documentation)

        # Write files
        target_dir.mkdir(parents=True)
        (target_dir / "__init__.py").write_text(init_content, encoding="utf-8")
        (target_dir / f"_{module_name}.py").write_text(impl_content, encoding="utf-8")
        (target_dir / f"test_{module_name}.py").write_text(test_content, encoding="utf-8")

        logger.info("Module '%s' created at %s", module_name, target_dir)
        return (
            f"[Module '{module_name}' created at awfulclaw/modules/{module_name}/]\n"
            f"Files: __init__.py, _{module_name}.py, test_{module_name}.py\n"
            f"It will be hot-reloaded on the next idle tick."
        )

    def is_available(self) -> bool:
        return _TEMPLATE_DIR.exists()
