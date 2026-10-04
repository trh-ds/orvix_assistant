"""Timers and reminders (category: info). Stored in SQLite, fired by core/reminders.py."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from orvix.core.interfaces import ToolResult
from orvix.tools.base import BaseTool

UNITS = {"s": 1, "sec": 1, "second": 1, "m": 60, "min": 60, "minute": 60, "h": 3600, "hr": 3600,
         "hour": 3600, "d": 86400, "day": 86400}  # fmt: skip


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    """Understands 'in 20 minutes', '18:30' / '6:30pm' (next occurrence), and ISO datetimes."""
    now = now or datetime.now()
    t = text.strip().lower()
    m = re.fullmatch(r"in\s+(\d+(?:\.\d+)?)\s*([a-z]+?)s?", t)
    if m and m.group(2) in UNITS:
        return now + timedelta(seconds=float(m.group(1)) * UNITS[m.group(2)])
    m = re.fullmatch(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m and (m.group(2) or m.group(3)):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if h > 23 or mi > 59:
            return None
        due = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        return due if due > now else due + timedelta(days=1)
    try:
        return datetime.fromisoformat(text.strip())
    except ValueError:
        return None


def human_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds >= 3600 and seconds % 3600 == 0:
        n, unit = seconds // 3600, "hour"
    elif seconds >= 60 and seconds % 60 == 0:
        n, unit = seconds // 60, "minute"
    else:
        n, unit = seconds, "second"
    return f"{n} {unit}{'' if n == 1 else 's'}"


class SetTimerArgs(BaseModel):
    seconds: int = Field(gt=0, le=7 * 86400, description="Duration in seconds")
    label: str = Field(default="Timer", description="What the timer is for")


class SetTimer(BaseTool):
    name = "set_timer"
    category = "info"
    description = "Set a countdown timer in seconds."
    params = SetTimerArgs

    def run(self, args: SetTimerArgs) -> ToolResult:
        self.ctx.store.add_reminder(time.time() + args.seconds, f"{args.label} is up")
        return self.ok(f"Timer set for {human_duration(args.seconds)}")


class SetReminderArgs(BaseModel):
    when: str = Field(description="e.g. 'in 20 minutes', '6:30pm', or an ISO datetime")
    text: str = Field(description="What to remind about")


class SetReminder(BaseTool):
    name = "set_reminder"
    category = "info"
    description = "Set a reminder for a time, e.g. 'in 20 minutes' or '6:30pm'."
    params = SetReminderArgs

    def run(self, args: SetReminderArgs) -> ToolResult:
        due = parse_when(args.when)
        if due is None:
            return self.fail(f"I couldn't understand the time '{args.when}'")
        if due <= datetime.now():
            return self.fail("That time is already in the past")
        self.ctx.store.add_reminder(due.timestamp(), args.text)
        return self.ok(f"Reminder set for {due:%a %H:%M}: {args.text}")


TOOLS = (SetTimer, SetReminder)
