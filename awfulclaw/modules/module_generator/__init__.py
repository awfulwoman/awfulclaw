from awfulclaw.modules.base import Module
from awfulclaw.modules.module_generator._module_generator import ModuleGeneratorModule


def create_module() -> Module:
    return ModuleGeneratorModule()
