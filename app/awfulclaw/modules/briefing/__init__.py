"""Daily briefing module."""

from awfulclaw.modules.base import Module
from awfulclaw.modules.briefing._briefing import BriefingModule

__all__ = ["BriefingModule", "create_module"]


def create_module() -> Module:
    return BriefingModule()
