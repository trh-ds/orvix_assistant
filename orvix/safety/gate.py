"""Safety gate: every tool call passes through here before it executes."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from orvix.core.interfaces import Risk, State
from orvix.tools.base import BaseTool

ConfirmFn = Callable[[str], bool | Awaitable[bool]]


@dataclass
class Authorization:
    allowed: bool
    risk: Risk
    confirmed: bool | None  # None = confirmation was not needed
    reason: str = ""


def describe(tool: BaseTool, args: BaseModel) -> str:
    parts = ", ".join(f"{k}={v!r}" for k, v in args.model_dump().items())
    return f"{tool.name}({parts})"


class Gate:
    def __init__(self, confirm: ConfirmFn | None, timeout_s: float = 10) -> None:
        self._confirm = confirm
        self.timeout_s = timeout_s

    def assess(self, tool: BaseTool, args: BaseModel, state: State) -> tuple[Risk, str]:
        risk = tool.assess(args)
        reason = getattr(tool, "last_reason", "") if risk is not Risk.SAFE else ""
        return risk, reason

    async def authorize(self, tool: BaseTool, args: BaseModel, state: State) -> Authorization:
        risk, reason = self.assess(tool, args, state)
        if risk is Risk.BLOCKED:
            return Authorization(False, risk, None, reason or "blocked by policy")
        if risk is Risk.SAFE:
            return Authorization(True, risk, None)
        # CONFIRM. After web content, this can never be auto-approved (no confirm fn => deny).
        prompt = f"About to run {describe(tool, args)}"
        if reason:
            prompt += f" ({reason})"
        if state.web_content_seen:
            prompt += " [after reading web content]"
        ok = await self._ask(prompt + ". Proceed?")
        return Authorization(ok, risk, ok, "" if ok else "not confirmed")

    async def _ask(self, prompt: str) -> bool:
        if self._confirm is None:
            return False
        try:
            res = self._confirm(prompt)
            if inspect.isawaitable(res):
                res = await asyncio.wait_for(res, self.timeout_s)
            return bool(res)
        except TimeoutError:
            return False
