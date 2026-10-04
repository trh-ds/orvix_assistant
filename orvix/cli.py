"""`orvix` entry point: voice (later), --text, probe, bench, eval."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from orvix.core.config import ROOT, load_config
from orvix.core.reminders import ReminderPoller
from orvix.core.stop import StopController
from orvix.memory.store import Store
from orvix.router import build_router
from orvix.tools.base import ToolContext
from orvix.tools.registry import build_registry


def _context(config_path: Path | None):
    cfg = load_config(config_path)
    store = Store(cfg.paths.db_path)
    ctx = ToolContext(cfg=cfg, store=store)
    return cfg, store, build_registry(ctx)


async def _typed_confirm(prompt: str) -> bool:
    answer = await asyncio.to_thread(input, f"\n[confirm] {prompt} [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


async def run_text(config_path: Path | None) -> int:
    from orvix.core.loop import Orchestrator
    from orvix.llm.ollama_client import LLMError, OllamaClient
    from orvix.safety.gate import Gate

    cfg, store, registry = _context(config_path)
    llm = OllamaClient(cfg.llm)
    try:
        print(f"Loading {cfg.llm.model} ...", flush=True)
        await llm.warm()
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        await llm.aclose()
        return 1

    gate = Gate(_typed_confirm, cfg.loop.confirm_timeout_s)
    orch = Orchestrator(cfg, llm, registry, gate, store, router=build_router(cfg, registry))
    ctx = registry.all()[0].ctx
    stop = StopController(ctx.stop, registry.kill_all)
    stop.bind(asyncio.get_running_loop())
    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop.trigger)
    poller = asyncio.create_task(
        ReminderPoller(store, notify=lambda t: print(f"\n[reminder] {t}", flush=True)).run()
    )
    print("Orvix text mode. Type a command, or 'quit'. Ctrl+C stops the current turn.")
    try:
        while True:
            try:
                line = await asyncio.to_thread(input, "\n> ")
            except EOFError:
                break
            line = line.strip()
            if not line:
                continue
            if line.lower() in {"quit", "exit"}:
                break
            stop.reset()
            task = asyncio.create_task(orch.turn(line))
            stop.track(task)
            try:
                res = await task
            except asyncio.CancelledError:
                print("\nStopped.")
                continue
            finally:
                stop.track(None)
            print(f"\nOrvix: {res.reply}")
            shown = {k: v for k, v in res.timings.items() if k.startswith("mark:")}
            print(
                f"  [{', '.join(f'{k[5:]} {v:.0f} ms' for k, v in shown.items())}]" if shown else ""
            )
    finally:
        poller.cancel()
        await llm.aclose()
    return 0


async def run_bench(config_path: Path | None) -> int:
    from orvix import bench
    from orvix.llm.ollama_client import LLMError

    cfg, _, registry = _context(config_path)
    try:
        res = await bench.bench_llm(cfg, registry)
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Model: {cfg.llm.model}\n{bench.render(res)}")
    return 0


async def run_eval_cmd(config_path: Path | None, path: Path, router_only: bool = False) -> int:
    from orvix.evalrun import load_cases, run_eval, summarize
    from orvix.llm.ollama_client import LLMError, OllamaClient

    cfg, _, registry = _context(config_path)
    cases = load_cases(path)
    if router_only:
        from orvix.evalrun import route_only, summarize_route
        from orvix.router.embed_fallback import SimilarityRouter

        router = SimilarityRouter(registry, cfg.router, cfg.llm.top_k_tools)
        print(summarize_route(route_only(cases, router)))
        return 0
    llm = OllamaClient(cfg.llm)
    try:
        await llm.warm()
        results = await run_eval(cases, llm, registry)
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        await llm.aclose()
    print(f"Model: {cfg.llm.model}\n{summarize(results)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orvix", description="Local voice assistant")
    p.add_argument("--text", action="store_true", help="text mode (no microphone)")
    p.add_argument("--config", type=Path, default=None, help="path to config.toml")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("probe", help="detect RAM, GPU, session type and available backends")
    sub.add_parser("bench", help="latency benchmark")
    ev = sub.add_parser("eval", help="run the command eval set")
    ev.add_argument("--file", type=Path, default=ROOT / "evals" / "commands.jsonl")
    ev.add_argument("--router-only", action="store_true", help="score the router without an LLM")
    args = p.parse_args(argv)

    if args.cmd == "probe":
        from orvix import probe

        cfg = load_config(args.config)
        print(probe.render(probe.collect(cfg.llm.host)))
        return 0
    if args.cmd == "bench":
        return asyncio.run(run_bench(args.config))
    if args.cmd == "eval":
        return asyncio.run(run_eval_cmd(args.config, args.file, args.router_only))
    if args.text:
        return asyncio.run(run_text(args.config))
    print("Voice mode arrives in Phase 6. Use `orvix --text` for now.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
