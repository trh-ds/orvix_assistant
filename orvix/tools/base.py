"""Tool base class, shared context, and the process helpers tools use (mockable in tests)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

from orvix.core.config import Config
from orvix.core.interfaces import Risk, ToolResult, ToolSpec
from orvix.memory.store import Store
from orvix.safety.policy import is_secret_path


@dataclass
class Proc:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class Runner:
    """Thin wrapper over subprocess so tests can swap in a fake."""

    def __init__(self) -> None:
        self.active: set[subprocess.Popen] = set()

    def launch(self, argv: list[str], cwd: str | None = None) -> None:
        """Start a detached GUI/background process and return immediately."""
        subprocess.Popen(  # noqa: S603
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def run(
        self,
        argv: list[str] | str,
        timeout: float = 30,
        cwd: str | None = None,
        shell: bool = False,
    ) -> Proc:
        try:
            p = subprocess.Popen(  # noqa: S603
                argv,
                cwd=cwd,
                shell=shell,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                start_new_session=True,
            )
        except FileNotFoundError as e:
            return Proc(127, "", str(e))
        self.active.add(p)
        try:
            out, err = p.communicate(timeout=timeout)
            return Proc(p.returncode, out, err)
        except subprocess.TimeoutExpired:
            self.kill(p)
            out, err = p.communicate()
            return Proc(124, out or "", err or "", timed_out=True)
        finally:
            self.active.discard(p)

    @staticmethod
    def kill(p: subprocess.Popen) -> None:
        import signal

        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def kill_all(self) -> None:
        for p in list(self.active):
            self.kill(p)


@dataclass
class ToolContext:
    cfg: Config
    store: Store
    runner: Runner = field(default_factory=Runner)

    @property
    def home(self) -> Path:
        return self.cfg.paths.home_path

    def resolve(self, raw: str) -> Path:
        """Expand ~ against the configured home and make absolute."""
        raw = raw.strip()
        if raw == "~" or raw.startswith("~/"):
            p = self.home / raw[2:]
        else:
            p = Path(raw)
            if not p.is_absolute():
                p = self.home / p
        return Path(os.path.normpath(p))

    def is_secret(self, path: Path | str) -> bool:
        return is_secret_path(path, self.cfg.paths.blocked_paths)


def cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


class BaseTool:
    name: ClassVar[str]
    category: ClassVar[str]
    description: ClassVar[str]
    params: ClassVar[type[BaseModel]]
    risk: ClassVar[Risk] = Risk.SAFE

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx

    def assess(self, args: BaseModel) -> Risk:
        """Per-call risk; override when it depends on the arguments."""
        return self.risk

    def run(self, args: BaseModel) -> ToolResult:
        raise NotImplementedError

    def spec(self) -> ToolSpec:
        schema = self.params.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return ToolSpec(self.name, self.description, schema)

    def ok(self, output: str = "") -> ToolResult:
        return ToolResult(True, cap(output, self.ctx.cfg.loop.tool_output_cap))

    def fail(self, error: str) -> ToolResult:
        return ToolResult(False, error=error)
