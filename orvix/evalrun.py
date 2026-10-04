"""`orvix eval`: score tool choice and arguments on evals/commands.jsonl without executing anything."""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from orvix.core.interfaces import LLM, Msg, Risk
from orvix.llm.prompts import SYSTEM_PROMPT
from orvix.tools.registry import Registry

EXPECTS = {"tool", "chat", "clarify", "confirm", "refuse"}


@dataclass
class Case:
    id: str
    input: str
    expect: str = "tool"
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    split: str = "dev"


@dataclass
class CaseResult:
    case: Case
    tool_ok: bool
    args_ok: bool
    latency_ms: float
    got: str


def load_cases(path: Path) -> list[Case]:
    cases = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        d = json.loads(line)
        c = Case(**d)
        if c.expect not in EXPECTS:
            raise ValueError(f"line {n}: bad expect {c.expect!r}")
        cases.append(c)
    return cases


def _norm(v: Any) -> str:
    return str(v).strip().lower().rstrip("/")


def args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Every expected key must match. A list of values means any of them is accepted."""
    for k, want in expected.items():
        if k not in actual:
            return False
        options = want if isinstance(want, list) else [want]
        if _norm(actual[k]) not in {_norm(o) for o in options}:
            return False
    return True


async def run_case(case: Case, llm: LLM, registry: Registry, gate_risk) -> CaseResult:
    messages = [Msg("system", SYSTEM_PROMPT), Msg("user", case.input)]
    start = time.perf_counter()
    text, calls = [], []
    async for ch in llm.chat(messages, registry.specs(), False):
        text.append(ch.text)
        calls.extend(ch.tool_calls)
    latency = (time.perf_counter() - start) * 1000
    reply = "".join(text).strip()
    first = calls[0] if calls else None

    if case.expect == "tool":
        tool_ok = bool(first and first.name == case.tool)
        args_ok = tool_ok and args_match(case.args, first.arguments)
        got = f"{first.name}({first.arguments})" if first else f"text: {reply[:60]}"
    elif case.expect in ("chat", "clarify"):
        tool_ok = first is None and bool(reply)
        args_ok = tool_ok and (case.expect == "chat" or reply.endswith("?"))
        got = f"{first.name}(...)" if first else f"text: {reply[:60]}"
    else:  # confirm / refuse: judged by the risk the gate would assign
        risk = gate_risk(first) if first else Risk.SAFE
        want = Risk.CONFIRM if case.expect == "confirm" else Risk.BLOCKED
        refused_in_words = case.expect == "refuse" and first is None and bool(reply)
        tool_ok = args_ok = (
            risk is want
            or refused_in_words
            or (case.expect == "confirm" and first is None and bool(reply))
        )
        got = f"{first.name}({first.arguments}) -> {risk}" if first else f"text: {reply[:60]}"
    return CaseResult(case, tool_ok, args_ok, latency, got)


def gate_risk_fn(registry: Registry):
    def risk(call) -> Risk:
        tool = registry.get(call.name)
        if tool is None:
            return Risk.SAFE
        try:
            return tool.assess(tool.params.model_validate(call.arguments))
        except ValidationError:
            return Risk.SAFE

    return risk


async def run_eval(cases: list[Case], llm: LLM, registry: Registry) -> list[CaseResult]:
    risk = gate_risk_fn(registry)
    return [await run_case(c, llm, registry, risk) for c in cases]


def summarize(results: list[CaseResult]) -> str:
    def pct(rs, f):
        return f"{100 * sum(f(r) for r in rs) / len(rs):5.1f}%" if rs else "  n/a"

    lines = []
    for split in ("dev", "heldout", "all"):
        rs = results if split == "all" else [r for r in results if r.case.split == split]
        if rs:
            lines.append(
                f"{split:<8} n={len(rs):<4} tool={pct(rs, lambda r: r.tool_ok)}  "
                f"args={pct(rs, lambda r: r.args_ok)}"
            )
    if results:
        lats = [r.latency_ms for r in results]
        lines.append(f"latency  median={statistics.median(lats):.0f} ms  max={max(lats):.0f} ms")
    fails = [r for r in results if not (r.tool_ok and r.args_ok)]
    if fails:
        lines.append("\nFailures:")
        lines += [
            f"  [{r.case.id}] {r.case.input!r}\n      expected {r.case.expect} {r.case.tool or ''} {r.case.args or ''}\n      got      {r.got}"
            for r in fails
        ]
    return "\n".join(lines)
