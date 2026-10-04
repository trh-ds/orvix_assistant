import asyncio

from orvix.core.interfaces import Chunk, Decision, ToolCall
from orvix.core.loop import Orchestrator
from orvix.safety.gate import Gate
from orvix.tools.base import Proc
from orvix.tools.registry import build_registry


class ScriptedLLM:
    """Each chat() call pops one scripted response: str text or list[ToolCall]."""

    def __init__(self, *script):
        self.script = list(script)
        self.seen = []

    async def chat(self, messages, tools, think):
        self.seen.append((list(messages), [t.name for t in tools], think))
        step = self.script.pop(0)
        if isinstance(step, str):
            for i in range(0, len(step), 5):
                yield Chunk(text=step[i : i + 5])
            yield Chunk(done=True)
        else:
            yield Chunk(tool_calls=step, done=True)


def make(ctx, llm, confirm=lambda p: True, router=None):
    reg = build_registry(ctx)
    cfg = ctx.cfg
    return Orchestrator(cfg, llm, reg, Gate(confirm), ctx.store, router=router), reg


async def test_plain_chat_turn_logged(ctx):
    pieces = []
    o, _ = make(ctx, ScriptedLLM("It is fine."))
    o.on_text = pieces.append
    r = await o.turn("how are you")
    assert r.success and r.reply == "It is fine." and "".join(pieces) == "It is fine."
    row = ctx.store.turns()[0]
    assert row["transcript"] == "how are you" and row["reply"] == "It is fine."
    assert "mark:first_token" in r.timings


async def test_tool_call_roundtrip(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    llm = ScriptedLLM([ToolCall("open_url", {"url": "example.com"})], "Opened it.")
    o, _ = make(ctx, llm)
    r = await o.turn("open example.com")
    assert r.reply == "Opened it." and r.tool_calls == ["open_url"]
    assert ctx.runner.launched == [["xdg-open", "https://example.com"]]
    tc = ctx.store.tool_calls(r.turn_id)[0]
    assert tc["tool"] == "open_url" and tc["risk"] == "SAFE"
    # the tool result was fed back to the model
    assert llm.seen[1][0][-1].role == "tool"


async def test_invalid_args_retry_once_then_stop(ctx):
    bad = ToolCall("open_url", {})
    llm = ScriptedLLM([bad], [bad], "Sorry, I could not do that.")
    o, _ = make(ctx, llm)
    r = await o.turn("open")
    msgs = [m.content for m in llm.seen[2][0] if m.role == "tool"]
    assert "Fix them" in msgs[0] and "Tell the user" in msgs[1]
    assert r.reply.startswith("Sorry")
    assert ctx.runner.launched == []


async def test_unknown_tool_reported(ctx):
    llm = ScriptedLLM([ToolCall("hack_nasa", {})], "I can't do that.")
    o, _ = make(ctx, llm)
    await o.turn("x")
    assert "Unknown tool" in llm.seen[1][0][-1].content


async def test_confirm_denied_does_not_execute(ctx):
    llm = ScriptedLLM([ToolCall("run_shell", {"cmd": "rm -rf build"})], "Okay, cancelled.")
    o, _ = make(ctx, llm, confirm=lambda p: False)
    await o.turn("delete the build folder")
    assert ctx.runner.ran == []
    tc = ctx.store.tool_calls()[0]
    assert tc["risk"] == "CONFIRM" and tc["confirmed"] == 0 and "Not allowed" in tc["error"]


async def test_confirm_granted_executes_and_logs(ctx):
    ctx.runner.next = Proc(0, "", "")
    llm = ScriptedLLM([ToolCall("run_shell", {"cmd": "rm -rf build"})], "Deleted.")
    o, _ = make(ctx, llm)
    await o.turn("delete the build folder")
    assert ctx.runner.ran == ["rm -rf build"]
    assert ctx.store.tool_calls()[0]["confirmed"] == 1


async def test_blocked_never_runs_even_when_confirm_says_yes(ctx):
    llm = ScriptedLLM([ToolCall("run_shell", {"cmd": "sudo rm -rf /"})], "No.")
    o, _ = make(ctx, llm)
    await o.turn("wipe it")
    assert ctx.runner.ran == []


async def test_max_tool_calls_cap(ctx):
    ctx.runner.next = Proc(0, "x", "")
    call = [ToolCall("run_shell", {"cmd": "ls"})]
    llm = ScriptedLLM(*[call] * 10)
    o, _ = make(ctx, llm)
    r = await o.turn("loop")
    assert not r.success and len(ctx.runner.ran) == 5


async def test_fast_path_skips_llm(ctx):
    class R:
        def decide(self, text, state):
            return Decision("FAST", tool="now", confidence=0.99)

    llm = ScriptedLLM()
    o, _ = make(ctx, llm, router=R())
    r = await o.turn("what time is it")
    assert r.success and llm.seen == [] and "mark:action_start" in r.timings


async def test_fast_path_with_required_args_falls_to_llm(ctx):
    class R:
        def decide(self, text, state):
            return Decision("FAST", tool="open_url", confidence=0.9)

    llm = ScriptedLLM("Which site?")
    o, _ = make(ctx, llm, router=R())
    r = await o.turn("open it")
    assert r.reply == "Which site?"


async def test_category_limits_tools_sent(ctx):
    class R:
        def decide(self, text, state):
            return Decision("LLM", category="files", confidence=0.9)

    llm = ScriptedLLM("ok")
    o, _ = make(ctx, llm, router=R())
    await o.turn("x")
    assert set(llm.seen[0][1]) == {"find_path", "list_dir", "read_file", "write_file", "open_file"}


async def test_facts_injected_and_history_kept(ctx):
    ctx.store.remember("college folder", "~/clg")
    llm = ScriptedLLM("a", "b")
    o, _ = make(ctx, llm)
    await o.turn("open my college folder")
    assert any("college folder" in m.content for m in llm.seen[0][0] if m.role == "system")
    await o.turn("again")
    assert [m.content for m in llm.seen[1][0] if m.role in ("user", "assistant")][:2] == [
        "open my college folder",
        "a",
    ]


async def test_llm_down_reports_failure(ctx):
    from orvix.llm.ollama_client import LLMError

    class Down:
        async def chat(self, *a):
            raise LLMError("Cannot reach Ollama")
            yield

    o, _ = make(ctx, Down())
    r = await o.turn("hi")
    assert not r.success and "Cannot reach Ollama" in r.reply


async def test_tool_timeout_kills_and_reports(ctx, monkeypatch):
    import time

    ctx.cfg.loop.tool_timeout_s = 0.1
    reg_llm = ScriptedLLM([ToolCall("now", {})], "ok")
    o, reg = make(ctx, reg_llm)
    monkeypatch.setattr(reg.get("now"), "run", lambda a: time.sleep(0.5))
    r = await o.turn("time")
    assert "timed out" in reg_llm.seen[1][0][-1].content
    await asyncio.sleep(0.5)
    assert r.success


async def test_cancel_stops_turn(ctx):
    class Slow:
        async def chat(self, *a):
            await asyncio.sleep(5)
            yield Chunk(done=True)

    o, _ = make(ctx, Slow())
    task = asyncio.create_task(o.turn("x"))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert ctx.store.turns()[0]["reply"] == "Stopped."
