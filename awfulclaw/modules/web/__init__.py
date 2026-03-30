from awfulclaw.modules.base import Module
from awfulclaw.modules.web._web import WebModule


def create_module() -> Module:
    return WebModule()
