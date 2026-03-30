"""Module registry for awfulclaw — auto-discovers modules under awfulclaw/modules/."""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from types import ModuleType

from awfulclaw.modules.base import Module, SkillTag, SkillTagMatcher, ToolMatcher

__all__ = [
    "Module",
    "ModuleRegistry",
    "SkillTag",
    "SkillTagMatcher",
    "ToolMatcher",
    "get_registry",
]

logger = logging.getLogger(__name__)

_SKIP_NAMES = {"base", "__pycache__"}


def _module_files(pkg_path: Path) -> list[Path]:
    """Return tracked source files for a module package: __init__.py + _*.py."""
    files: list[Path] = []
    init = pkg_path / "__init__.py"
    if init.exists():
        files.append(init)
    for f in sorted(pkg_path.glob("_*.py")):
        if f.name != "__init__.py":
            files.append(f)
    return files


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, Module] = {}
        # pkg_name -> {file_path -> mtime}
        self.mtimes: dict[str, dict[Path, float]] = {}

    def register(self, module: Module) -> None:
        self._modules[module.name] = module

    def _pkg_name(self, dir_name: str) -> str:
        return f"awfulclaw.modules.{dir_name}"

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
            self._load_pkg(name, path)

    def _load_pkg(self, dir_name: str, pkg_path: Path) -> None:
        pkg = self._pkg_name(dir_name)
        try:
            mod = importlib.import_module(pkg)
        except Exception as exc:
            logger.warning("Failed to import module package %s: %s", pkg, exc)
            return
        if not hasattr(mod, "create_module"):
            logger.warning("Module package %s has no create_module(), skipping", pkg)
            return
        try:
            instance: Module = mod.create_module()
            self.register(instance)
            self.mtimes[pkg] = {f: _mtime(f) for f in _module_files(pkg_path)}
            logger.debug("Registered module: %s", instance.name)
        except Exception as exc:
            logger.warning("create_module() failed for %s: %s", pkg, exc)

    def check_for_changes(self) -> bool:
        """Check if any module files have changed or new modules were added.

        Reloads the registry if changes are detected. Returns True if reloaded.
        """
        modules_dir = Path(__file__).parent
        changed = False

        # Check existing modules for mtime changes
        for pkg, file_mtimes in list(self.mtimes.items()):
            for fpath, old_mtime in file_mtimes.items():
                if _mtime(fpath) != old_mtime:
                    logger.info("Module file changed: %s — reloading", fpath.name)
                    changed = True
                    break

        # Check for new module subdirectories
        for path in sorted(modules_dir.iterdir()):
            if not path.is_dir():
                continue
            name = path.name
            if name.startswith("_") or name in _SKIP_NAMES:
                continue
            if not (path / "__init__.py").exists():
                continue
            pkg = self._pkg_name(name)
            if pkg not in self.mtimes:
                logger.info("New module directory detected: %s", name)
                changed = True
                break

        if changed:
            self.reload()
        return changed

    def reload(self) -> None:
        """Re-discover all modules, using importlib.reload() for already-imported packages."""
        modules_dir = Path(__file__).parent
        old_names = set(self._modules.keys())
        self._modules.clear()
        self.mtimes.clear()

        for path in sorted(modules_dir.iterdir()):
            if not path.is_dir():
                continue
            name = path.name
            if name.startswith("_") or name in _SKIP_NAMES:
                continue
            if not (path / "__init__.py").exists():
                continue
            pkg = self._pkg_name(name)
            # Reload already-imported packages; import fresh otherwise
            if pkg in sys.modules:
                try:
                    existing: ModuleType = sys.modules[pkg]
                    importlib.reload(existing)
                    # Also reload submodules so _impl changes are picked up
                    for mod_name in list(sys.modules):
                        if mod_name.startswith(pkg + "."):
                            try:
                                importlib.reload(sys.modules[mod_name])
                            except Exception as sub_exc:
                                logger.warning(
                                    "Failed to reload submodule %s: %s", mod_name, sub_exc
                                )
                except Exception as exc:
                    logger.warning("Failed to reload %s: %s", pkg, exc)
            self._load_pkg(name, path)

        new_names = set(self._modules.keys())
        added = new_names - old_names
        removed = old_names - new_names
        if added:
            logger.info("Modules added after reload: %s", ", ".join(sorted(added)))
        if removed:
            logger.info("Modules removed after reload: %s", ", ".join(sorted(removed)))

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

    def get_all_tool_matchers(self) -> list[ToolMatcher]:
        """Return all skill tags wrapped as ToolMatcher instances."""
        return [SkillTagMatcher(module, tag) for module, tag in self.get_all_skill_tags()]

    def get_system_prompt_fragments(self) -> list[str]:
        return [m.system_prompt_fragment for m in self.get_available()]


_registry: ModuleRegistry | None = None


def get_registry() -> ModuleRegistry:
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
        _registry.discover()
    return _registry
