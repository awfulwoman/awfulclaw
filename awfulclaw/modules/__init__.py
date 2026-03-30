"""Module registry for awfulclaw — auto-discovers modules under awfulclaw/modules/."""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from awfulclaw.modules.base import Module, SkillTag

__all__ = ["Module", "ModuleRegistry", "SkillTag", "get_registry"]

logger = logging.getLogger(__name__)

_SKIP_NAMES = {"base", "__pycache__"}


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, Module] = {}

    def register(self, module: Module) -> None:
        self._modules[module.name] = module

    def discover(self) -> None:
        modules_dir = Path(__file__).parent
        for path in sorted(modules_dir.iterdir()):
            if not path.is_dir():
                continue
            name = path.name
            if name.startswith("_") or name in _SKIP_NAMES:
                continue
            if not (path / "__init__.py").exists():
                continue
            pkg = f"awfulclaw.modules.{name}"
            try:
                mod = importlib.import_module(pkg)
            except Exception as exc:
                logger.warning("Failed to import module package %s: %s", pkg, exc)
                continue
            if not hasattr(mod, "create_module"):
                logger.warning("Module package %s has no create_module(), skipping", pkg)
                continue
            try:
                instance: Module = mod.create_module()
                self.register(instance)
                logger.debug("Registered module: %s", instance.name)
            except Exception as exc:
                logger.warning("create_module() failed for %s: %s", pkg, exc)

    def get(self, name: str) -> Module | None:
        return self._modules.get(name)

    def get_all(self) -> list[Module]:
        return list(self._modules.values())

    def get_available(self) -> list[Module]:
        return [m for m in self._modules.values() if m.is_available()]

    def get_all_skill_tags(self) -> list[tuple[Module, SkillTag]]:
        result: list[tuple[Module, SkillTag]] = []
        for module in self.get_available():
            for tag in module.skill_tags:
                result.append((module, tag))
        return result

    def get_system_prompt_fragments(self) -> list[str]:
        return [m.system_prompt_fragment for m in self.get_available()]

    def reload(self) -> None:
        self._modules.clear()
        self.discover()


_registry: ModuleRegistry | None = None


def get_registry() -> ModuleRegistry:
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
        _registry.discover()
    return _registry
