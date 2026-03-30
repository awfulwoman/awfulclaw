"""Schedule module — create, delete, and run scheduled prompts."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timezone

from croniter import croniter  # type: ignore[import-untyped]

import awfulclaw.scheduler as scheduler
from awfulclaw.modules.base import Module, SkillTag

logger = logging.getLogger(__name__)

_SKILL_SCHEDULE_RE = re.compile(
    r"<skill:schedule\s+([^>]*?)(?:/>|>(.*?)</skill:schedule>)",
    re.DOTALL,
)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


class ScheduleModule(Module):
    @property
    def name(self) -> str:
        return "schedule"

    @property
    def skill_tags(self) -> list[SkillTag]:
        return [
            SkillTag(
                name="schedule",
                pattern=_SKILL_SCHEDULE_RE,
                description="Create or delete scheduled prompts",
                usage=(
                    '<skill:schedule action="create" name="..." cron="...">prompt</skill:schedule>'
                ),
            )
        ]

    @property
    def system_prompt_fragment(self) -> str:
        return """\
### Schedules
Create a recurring cron schedule:
```
<skill:schedule action="create" name="daily-briefing" cron="0 8 * * *">
Your prompt here
</skill:schedule>
```

Create a one-off reminder:
```
<skill:schedule action="create" name="reminder" at="2025-12-31T09:00:00Z">
Your prompt here
</skill:schedule>
```

Create with an optional wake condition (shell command returning `{"wakeAgent": true/false}`):
```
<skill:schedule action="create" name="conditional" cron="*/5 * * * *"
               condition="check-something.sh">
Your prompt here
</skill:schedule>
```

Delete a schedule:
```
<skill:schedule action="delete" name="daily-briefing"/>
```"""

    def dispatch(self, tag_match: re.Match[str], history: list[dict[str, str]], system: str) -> str:
        attrs_str = tag_match.group(1) or ""
        body = (tag_match.group(2) or "").strip()
        attrs = dict(_ATTR_RE.findall(attrs_str))
        action = attrs.get("action", "")
        name = attrs.get("name", "").strip()

        schedules = scheduler.load_schedules()

        if action == "create":
            cron = attrs.get("cron", "").strip()
            condition = attrs.get("condition", "").strip() or None
            at_str = attrs.get("at", "").strip()
            if at_str:
                try:
                    fire_at = datetime.fromisoformat(at_str)
                    if fire_at.tzinfo is None:
                        fire_at = fire_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    return f"[Schedule error: invalid datetime '{at_str}' for '{name}']"
                new_sched = scheduler.Schedule.create(
                    name=name, prompt=body, fire_at=fire_at, condition=condition
                )
            else:
                if not croniter.is_valid(cron):
                    return f"[Schedule error: invalid cron expression '{cron}' for '{name}']"
                new_sched = scheduler.Schedule.create(
                    name=name, cron=cron, prompt=body, condition=condition
                )
            idx = next(
                (i for i, s in enumerate(schedules) if s.name.lower() == name.lower()),
                None,
            )
            if idx is not None:
                schedules[idx] = new_sched
                scheduler.save_schedules(schedules)
                logger.info("Schedule updated: '%s'", name)
                return f"[Schedule '{name}' updated]"
            else:
                schedules.append(new_sched)
                scheduler.save_schedules(schedules)
                logger.info("Schedule created: '%s'", name)
                return f"[Schedule '{name}' created]"

        elif action == "delete":
            before = len(schedules)
            schedules[:] = [s for s in schedules if s.name.lower() != name.lower()]
            if len(schedules) < before:
                scheduler.save_schedules(schedules)
                logger.info("Schedule deleted: '%s'", name)
                return f"[Schedule '{name}' deleted]"
            else:
                logger.warning("Schedule delete: '%s' not found", name)
                return f"[Schedule '{name}' not found]"

        return f"[Schedule: unknown action '{action}']"

    def run_due(self) -> list[str]:
        """Check for due schedules and return their prompts.

        Returns a list of prompt strings for due schedules. The caller is
        responsible for invoking Claude and sending the replies.
        One-off schedules are removed from the file after being returned.
        """
        now = datetime.now(timezone.utc)
        schedules = scheduler.load_schedules()
        due = scheduler.get_due(schedules, now)
        prompts: list[str] = []
        one_off_ids: set[str] = set()

        for sched in due:
            if sched.condition is not None and not should_wake(sched.condition):
                logger.debug("Schedule '%s' suppressed by condition", sched.name)
                if sched.fire_at is None:
                    sched.last_run = now
                continue
            prompts.append(sched.prompt)
            if sched.fire_at is not None:
                one_off_ids.add(sched.id)
            else:
                sched.last_run = now

        if one_off_ids:
            schedules[:] = [s for s in schedules if s.id not in one_off_ids]
        if due:
            scheduler.save_schedules(schedules)

        return prompts

    def is_available(self) -> bool:
        return True


def should_wake(condition: str) -> bool:
    """Run condition command; return True if Claude should be invoked.

    Returns True (fail open) on command error, timeout, or invalid JSON.
    Returns False only when the command succeeds and wakeAgent is False.
    """
    import shlex

    try:
        result = subprocess.run(
            shlex.split(condition),
            shell=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(
                "Schedule condition exited %d — proceeding with Claude call", result.returncode
            )
            return True
        data = json.loads(result.stdout)
        wake = data.get("wakeAgent", True)
        return bool(wake)
    except subprocess.TimeoutExpired:
        logger.warning("Schedule condition timed out — proceeding with Claude call")
        return True
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Schedule condition error: %s — proceeding with Claude call", exc)
        return True
