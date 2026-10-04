"""Turn orchestration: router -> (fast path | LLM tool loop) -> gate -> execute -> reply."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError

from orvix.core.config import Config
from orvix.core.interfaces import LLM, Decision, Msg, Router, State, ToolCall, ToolResult
from orvix.core.timing import Timings
from orvix.llm.ollama_client import LLMError
from orvix.llm.prompts import SYSTEM_PROMPT, facts_block
from orvix.memory.store import Store
from orvix.safety.gate import Gate
from orvix.tools.registry import Registry

WEB_TOOLS = {"web_search", "fetch_page"}
MAX_HISTORY_MSGS = 8


@dataclass
class TurnResult:
    turn_id: int
    reply: str
    success: bool
    timings: dict[str, float]
    tool_calls: list[str] = field(default_factory=list)
    decision: Decision | None = None


class Orchestrator:
    def __init__(
        self,
        cfg: Config,
        llm: LLM,
        registry: Registry,
        gate: Gate,
        store: Store,
        router: Router | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.llm = llm
        self.registry = registry
        self.gate = gate
        self.store = store
        self.router = router
        self.on_text = on_text  # called with each streamed text piece (TTS hooks in here later)
        self.state = State()
        self.history: list[Msg] = []

    # ------------------------------------------------------------------
    async def turn(self, text: str) -> TurnResult:
        t = Timings()
        turn_id = self.store.start_turn(text)
        self.state.web_content_seen = False
        called: list[str] = []
        decision: Decision | None = None
        reply, success = "", False
        try:
            with t.stage("router"):
                decision = self.router.decide(text, self.state) if self.router else None
            if decision and decision.kind == "FAST" and decision.tool:
                reply, success = await self._fast_path(turn_id, decision, t, called)
            if not reply:
                reply, success = await self._llm_path(turn_id, text, decision, t, called)
        except asyncio.CancelledError:
            self.registry.kill_all()
            reply, success = "Stopped.", False
            self._finish(turn_id, reply, t, success, decision)
            raise
        except LLMError as e:
            reply, success = f"I can't reach my language model. {e}", False
        except Exception as e:  # never let a turn crash the loop
            reply, success = f"Something went wrong: {e}", False
        self._finish(turn_id, reply, t, success, decision)
        if success:
            self.history += [Msg("user", text), Msg("assistant", reply)]
            self.history = self.history[-MAX_HISTORY_MSGS:]
        return TurnResult(turn_id, reply, success, t.as_dict(), called, decision)

    def _finish(self, turn_id, reply, t, success, decision) -> None:
        self.store.finish_turn(
            turn_id,
            reply=reply,
            timings=t.as_dict(),
            success=success,
            decision=decision.kind if decision else None,
            confidence=decision.confidence if decision else None,
        )

    # ------------------------------------------------------------------
    async def _fast_path(self, turn_id, decision: Decision, t: Timings, called) -> tuple[str, bool]:
        tool = self.registry.get(decision.tool or "")
        if tool is None:
            return "", False
        try:
            args = tool.params()  # zero-argument tools only
        except ValidationError:
            return "", False  # needs arguments: fall through to the LLM
        res = await self._execute(turn_id, tool.name, args, t, called, mark="action_start")
        return ("Done." if res.ok else res.error), res.ok

    async def _llm_path(self, turn_id, text, decision, t: Timings, called) -> tuple[str, bool]:
        names = self._tool_names(decision)
        specs = self.registry.specs(names)
        think = bool(decision and decision.kind == "MULTI") or self.cfg.llm.think
        messages = [Msg("system", SYSTEM_PROMPT), *self.history]
        fb = facts_block(self.store.search_facts(text))
        if fb:
            messages.append(Msg("system", fb))
        messages.append(Msg("user", text))

        retried: set[str] = set()
        calls_made = 0
        while True:
            content, calls = await self._stream(messages, specs, think, t)
            if not calls:
                return content.strip() or "Done.", True
            messages.append(Msg("assistant", content, tool_calls=calls))
            for call in calls:
                calls_made += 1
                if calls_made > self.cfg.loop.max_tool_calls:
                    return "That took too many steps, so I stopped.", False
                result = await self._run_call(turn_id, call, t, called, retried)
                messages.append(Msg("tool", result.text(), name=call.name))

    def _tool_names(self, decision: Decision | None) -> list[str] | None:
        if decision and decision.category:
            names = [x.name for x in self.registry.by_category(decision.category)]
            return names or None
        return None

    async def _stream(self, messages, specs, think, t: Timings) -> tuple[str, list[ToolCall]]:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        with t.stage("llm"):
            async for chunk in self.llm.chat(messages, specs, think):
                if chunk.text:
                    t.mark("first_token")
                    text_parts.append(chunk.text)
                    if self.on_text:
                        self.on_text(chunk.text)
                calls.extend(chunk.tool_calls)
        return "".join(text_parts), calls

    async def _run_call(self, turn_id, call: ToolCall, t, called, retried: set[str]) -> ToolResult:
        tool = self.registry.get(call.name)
        if tool is None:
            return ToolResult(
                False,
                error=f"Unknown tool '{call.name}'. Available: {', '.join(self.registry.names())}",
            )
        try:
            args = tool.params.model_validate(call.arguments)
        except ValidationError as e:
            err = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
            if call.name in retried:
                return ToolResult(
                    False,
                    error=f"Invalid arguments again ({err}). Tell the user you could not do it.",
                )
            retried.add(call.name)
            return ToolResult(False, error=f"Invalid arguments: {err}. Fix them and call again.")
        return await self._execute(turn_id, call.name, args, t, called)

    async def _execute(
        self, turn_id, name, args, t: Timings, called, mark: str | None = None
    ) -> ToolResult:
        tool = self.registry.get(name)
        assert tool is not None
        auth = await self.gate.authorize(tool, args, self.state)
        started = time.perf_counter()
        if not auth.allowed:
            res = ToolResult(False, error=f"Not allowed: {auth.reason}")
        else:
            if mark:
                t.mark(mark)
            res = await self._run_tool(tool, args, t)
        called.append(name)
        self.state.last_tool = name
        if name in WEB_TOOLS and res.ok:
            self.state.web_content_seen = True
        self.store.log_tool_call(
            turn_id, name, args.model_dump(), auth.risk.value, auth.confirmed,
            res.output, res.error, (time.perf_counter() - started) * 1000,
        )  # fmt: skip
        return res

    async def _run_tool(self, tool, args, t: Timings) -> ToolResult:
        loop = asyncio.get_running_loop()
        with t.stage(f"tool:{tool.name}"):
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(None, tool.run, args), self.cfg.loop.tool_timeout_s
                )
            except TimeoutError:
                tool.ctx.runner.kill_all()
                return ToolResult(False, error=f"{tool.name} timed out")
            except Exception as e:
                return ToolResult(False, error=f"{tool.name} failed: {e}")
