"""Per-stage timers. Every stage emits a timing; the turn stores them as JSON."""

from __future__ import annotations

import time
from contextlib import contextmanager


class Timings:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self.stages: dict[str, float] = {}
        self.marks: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0.0) + (time.perf_counter() - start) * 1000

    def mark(self, name: str) -> None:
        """Record ms since the turn began (e.g. first_token, action_start)."""
        self.marks.setdefault(name, (time.perf_counter() - self._t0) * 1000)

    def as_dict(self) -> dict[str, float]:
        return {
            **{f"stage:{k}": round(v, 1) for k, v in self.stages.items()},
            **{f"mark:{k}": round(v, 1) for k, v in self.marks.items()},
        }
