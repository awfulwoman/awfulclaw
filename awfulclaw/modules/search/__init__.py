from awfulclaw.modules.base import Module
from awfulclaw.modules.search._search import SearchModule


def create_module() -> Module:
    return SearchModule()
