"""Fires due timers/reminders: desktop notification plus a spoken alert."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import Callable

from orvix.memory.store import Store


def desktop_notify(text: str) -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(  # noqa: S603
            ["notify-send", "Orvix", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


class ReminderPoller:
    def __init__(
        self,
        store: Store,
        notify: Callable[[str], None] = desktop_notify,
        speak: Callable[[str], None] | None = None,
        interval_s: float = 1.0,
    ) -> None:
        self.store, self.notify, self.speak, self.interval_s = store, notify, speak, interval_s

    def fire_due(self) -> list[str]:
        fired = []
        for r in self.store.due_reminders():
            self.store.complete_reminder(r["id"])  # mark first so a crash never re-fires it
            self.notify(r["text"])
            if self.speak:
                self.speak(r["text"])
            fired.append(r["text"])
        return fired

    async def run(self) -> None:
        while True:
            await asyncio.to_thread(self.fire_due)
            await asyncio.sleep(self.interval_s)
