from awfulclaw.modules.base import Module
from awfulclaw.modules.schedule._schedule import ScheduleModule


def create_module() -> Module:
    return ScheduleModule()
