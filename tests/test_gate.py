import asyncio

import pytest

from orvix.core.interfaces import Risk, State
from orvix.safety.gate import Gate
from orvix.tools import files, shell
from orvix.tools.base import Proc


def auth(gate, tool, args, state=None):
    return asyncio.run(gate.authorize(tool, args, state or State()))


def test_safe_runs_without_confirm(ctx):
    asked = []
    g = Gate(lambda p: asked.append(p) or True)
    a = auth(g, shell.RunShell(ctx), shell.RunShellArgs(cmd="ls"))
    assert a.allowed and a.confirmed is None and not asked


def test_blocked_never_asks_or_runs(ctx):
    asked = []
    g = Gate(lambda p: asked.append(p) or True)
    t = shell.RunShell(ctx)
    a = auth(g, t, shell.RunShellArgs(cmd="sudo rm -rf /"))
    assert not a.allowed and a.risk is Risk.BLOCKED and not asked
    r = t.run(shell.RunShellArgs(cmd="sudo ls"))
    assert not r.ok and ctx.runner.ran == []


def test_confirm_yes_and_no(ctx):
    t, args = shell.RunShell(ctx), shell.RunShellArgs(cmd="rm build -rf")
    assert auth(Gate(lambda p: True), t, args).allowed
    a = auth(Gate(lambda p: False), t, args)
    assert not a.allowed and a.confirmed is False


def test_no_confirm_fn_denies(ctx):
    assert not auth(Gate(None), shell.RunShell(ctx), shell.RunShellArgs(cmd="rm x")).allowed


def test_confirm_timeout_denies(ctx):
    async def slow(prompt):
        await asyncio.sleep(1)
        return True

    g = Gate(slow, timeout_s=0.05)
    assert not auth(g, shell.RunShell(ctx), shell.RunShellArgs(cmd="rm x")).allowed


def test_write_file_confirms_and_blocks_secrets(ctx, tmp_path):
    t = files.WriteFile(ctx)
    g = Gate(lambda p: True)
    assert auth(g, t, files.WriteFileArgs(path="~/n.txt", content="x")).confirmed is True
    a = auth(g, t, files.WriteFileArgs(path="~/.ssh/authorized_keys", content="x"))
    assert not a.allowed and a.risk is Risk.BLOCKED
    assert not t.run(files.WriteFileArgs(path="~/.env", content="x")).ok
    assert t.run(files.WriteFileArgs(path="~/n.txt", content="hi")).ok
    assert (tmp_path / "n.txt").read_text() == "hi"


def test_run_shell_output_and_errors(ctx):
    t = shell.RunShell(ctx)
    ctx.runner.next = Proc(0, "hello\n", "")
    assert t.run(shell.RunShellArgs(cmd="echo hello")).output == "hello"
    ctx.runner.next = Proc(2, "", "boom")
    r = t.run(shell.RunShellArgs(cmd="ls nope"))
    assert not r.ok and "exit 2" in r.error
    ctx.runner.next = Proc(124, "", "", timed_out=True)
    assert "Timed out" in t.run(shell.RunShellArgs(cmd="sleep 99")).error


@pytest.mark.parametrize("cmd", ["rm -rf ~", "git push", "chmod 777 x", "mv a b"])
def test_destructive_never_runs_unconfirmed(ctx, cmd):
    g = Gate(lambda p: False)
    t = shell.RunShell(ctx)
    assert not auth(g, t, shell.RunShellArgs(cmd=cmd)).allowed


def test_confirm_prompt_flags_web_content(ctx):
    seen = []
    g = Gate(lambda p: seen.append(p) or True)
    auth(g, shell.RunShell(ctx), shell.RunShellArgs(cmd="rm x"), State(web_content_seen=True))
    assert "web content" in seen[0]
