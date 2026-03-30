"""Startup self-briefing module."""

from awfulclaw.modules.base import Module
from awfulclaw.modules.startup_briefing._startup_briefing import StartupBriefingModule

__all__ = ["StartupBriefingModule", "create_module"]


def create_module() -> Module:
    return StartupBriefingModule()
