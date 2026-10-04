"""Information tools (category: info)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import psutil
from pydantic import BaseModel, Field

from orvix.core.interfaces import ToolResult
from orvix.tools.base import BaseTool


class NoArgs(BaseModel):
    pass


class Now(BaseTool):
    name = "now"
    category = "info"
    description = "Get the current date and time."
    params = NoArgs

    def run(self, args: NoArgs) -> ToolResult:
        return self.ok(datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z"))


class SystemInfoArgs(BaseModel):
    kind: Literal["battery", "cpu", "ram", "disk", "processes"] = Field(
        description="What to report"
    )


class SystemInfo(BaseTool):
    name = "system_info"
    category = "info"
    description = "Report battery, cpu, ram, disk or top processes."
    params = SystemInfoArgs

    def run(self, args: SystemInfoArgs) -> ToolResult:
        k = args.kind
        if k == "battery":
            b = psutil.sensors_battery()
            if b is None:
                return self.fail("No battery found")
            state = "charging" if b.power_plugged else "on battery"
            return self.ok(f"{b.percent:.0f}% ({state})")
        if k == "cpu":
            return self.ok(
                f"CPU {psutil.cpu_percent(interval=0.3):.0f}% busy, {psutil.cpu_count()} cores"
            )
        if k == "ram":
            m = psutil.virtual_memory()
            return self.ok(
                f"RAM {m.percent:.0f}% used ({m.used / 2**30:.1f} of {m.total / 2**30:.1f} GB)"
            )
        if k == "disk":
            d = psutil.disk_usage("/")
            return self.ok(f"Disk {d.percent:.0f}% used ({d.free / 2**30:.0f} GB free)")
        procs = []
        for p in psutil.process_iter(["name", "memory_percent"]):
            procs.append((p.info["memory_percent"] or 0.0, p.info["name"] or "?"))
        procs.sort(reverse=True)
        return self.ok("\n".join(f"{n}: {m:.1f}% RAM" for m, n in procs[:5]))


TOOLS = (Now, SystemInfo)
