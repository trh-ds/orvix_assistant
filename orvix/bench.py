"""`orvix bench`: per-stage latency against the budget in docs/DESIGN.md."""

from __future__ import annotations

import statistics
import time

from orvix.core.config import Config
from orvix.core.interfaces import Msg
from orvix.llm.ollama_client import OllamaClient
from orvix.llm.prompts import SYSTEM_PROMPT
from orvix.tools.registry import Registry

PROMPTS = [
    "open example dot com",
    "what time is it",
    "list my downloads folder",
    "how much ram am I using",
]
BUDGET_MS = {"llm_first_token": 400, "llm_tool_call": 800}


async def bench_llm(cfg: Config, registry: Registry, runs: int = 4) -> dict:
    client = OllamaClient(cfg.llm)
    specs = registry.specs()
    t0 = time.perf_counter()
    await client.warm()
    out: dict = {"warmup_ms": (time.perf_counter() - t0) * 1000}
    ttft, tool_ms, tps = [], [], []
    try:
        for text in (PROMPTS * ((runs // len(PROMPTS)) + 1))[:runs]:
            start = time.perf_counter()
            first = call = None
            stats: dict = {}
            async for ch in client.chat(
                [Msg("system", SYSTEM_PROMPT), Msg("user", text)], specs, False
            ):
                now = (time.perf_counter() - start) * 1000
                if first is None and (ch.text or ch.tool_calls):
                    first = now
                if call is None and ch.tool_calls:
                    call = now
                if ch.done:
                    stats = ch.stats
            if first is not None:
                ttft.append(first)
            if call is not None:
                tool_ms.append(call)
            if stats.get("eval_duration"):
                tps.append(stats["eval_count"] / (stats["eval_duration"] / 1e9))
    finally:
        await client.aclose()
    out["llm_first_token_ms"] = statistics.median(ttft) if ttft else None
    out["llm_tool_call_ms"] = statistics.median(tool_ms) if tool_ms else None
    out["llm_tokens_per_s"] = statistics.median(tps) if tps else None
    return out


def render(res: dict) -> str:
    def line(label: str, val, budget: int | None = None, unit: str = "ms") -> str:
        if val is None:
            return f"{label:<28} n/a"
        flag = ""
        if budget is not None:
            flag = "  OK" if val <= budget else f"  OVER BUDGET (target {budget} {unit})"
        return f"{label:<28} {val:8.0f} {unit}{flag}"

    return "\n".join(
        [
            line("LLM warm-up (load)", res.get("warmup_ms")),
            line(
                "LLM time to first token",
                res.get("llm_first_token_ms"),
                BUDGET_MS["llm_first_token"],
            ),
            line("LLM tool call complete", res.get("llm_tool_call_ms"), BUDGET_MS["llm_tool_call"]),
            line("LLM tokens/s", res.get("llm_tokens_per_s"), None, "tok/s"),
            "STT / TTS / router / wake      not implemented yet (Phase 0 spikes, Phase 4, Phase 6)",
        ]
    )
