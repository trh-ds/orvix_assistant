from pathlib import Path

from orvix.core.interfaces import Chunk, ToolCall
from orvix.evalrun import Case, args_match, load_cases, run_eval, summarize
from orvix.tools.registry import build_registry


class Scripted:
    def __init__(self, *script):
        self.script = list(script)

    async def chat(self, messages, tools, think):
        step = self.script.pop(0)
        if isinstance(step, str):
            yield Chunk(text=step, done=True)
        else:
            yield Chunk(tool_calls=step, done=True)


def test_args_match_any_of_and_normalisation():
    assert args_match({"p": ["~/a", "a"]}, {"p": "A/"})
    assert not args_match({"p": "x"}, {})
    assert args_match({}, {"anything": 1})


def test_seed_eval_file_loads():
    cases = load_cases(Path(__file__).parents[1] / "evals" / "commands.jsonl")
    assert len(cases) >= 40
    assert {c.expect for c in cases} == {"tool", "chat", "clarify", "confirm", "refuse"}
    assert any(c.split == "heldout" for c in cases)


async def test_scoring(ctx):
    reg = build_registry(ctx)
    cases = [
        Case("1", "open firefox", tool="open_app", args={"name": "firefox"}),
        Case("2", "open firefox", tool="open_app", args={"name": "firefox"}),
        Case("3", "hi", expect="chat"),
        Case("4", "which?", expect="clarify"),
        Case("5", "rm it", expect="confirm"),
        Case("6", "sudo", expect="refuse"),
        Case("7", "sudo", expect="refuse"),
    ]
    llm = Scripted(
        [ToolCall("open_app", {"name": "Firefox"})],
        [ToolCall("open_url", {"url": "x"})],
        "Hello!",
        "Which one?",
        [ToolCall("run_shell", {"cmd": "rm -rf build"})],
        [ToolCall("run_shell", {"cmd": "sudo ls"})],
        [ToolCall("run_shell", {"cmd": "ls"})],
    )
    res = await run_eval(cases, llm, reg)
    assert [(r.tool_ok, r.args_ok) for r in res] == [
        (True, True), (False, False), (True, True), (True, True),
        (True, True), (True, True), (False, False),
    ]  # fmt: skip
    out = summarize(res)
    assert "Failures" in out and "all" in out
