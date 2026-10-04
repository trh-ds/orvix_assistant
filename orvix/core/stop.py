"""Global stop: cancels the current turn, kills subprocesses and silences TTS.

The hotkey listener itself is session-specific (X11 vs Wayland, VERIFY in Phase 0); it only has to
call `StopController.trigger()`. Everything else lives here so it can be tested without a desktop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable


class StopController:
    def __init__(self, event: threading.Event, kill: Callable[[], None]) -> None:
        self.event = event
        self._kill = kill
        self._hooks: list[Callable[[], None]] = []
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def on_stop(self, hook: Callable[[], None]) -> None:
        """Register extra cleanup, e.g. TTS.stop."""
        self._hooks.append(hook)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def track(self, task: asyncio.Task | None) -> None:
        self._task = task

    def trigger(self) -> None:
        """Safe to call from any thread (hotkey listener)."""
        self.event.set()
        self._kill()
        for h in self._hooks:
            h()
        task, loop = self._task, self._loop
        if task and loop and not task.done():
            loop.call_soon_threadsafe(task.cancel)

    def reset(self) -> None:
        self.event.clear()
