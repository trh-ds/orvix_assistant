"""Shell (category: shell). Risk is decided per command by safety/policy.py."""

from __future__ import annotations

from pydantic import BaseModel, Field

from orvix.core.interfaces import Risk, ToolResult
from orvix.safety.policy import Verdict, classify_shell
from orvix.tools.base import BaseTool


class RunShellArgs(BaseModel):
    cmd: str = Field(description="Shell command line to run")


class RunShell(BaseTool):
    name = "run_shell"
    category = "shell"
    description = "Run a shell command and return its output."
    params = RunShellArgs
    risk = Risk.CONFIRM  # default; assess() refines it per command
    last_reason = ""

    def verdict(self, args: RunShellArgs) -> Verdict:
        return classify_shell(
            args.cmd, self.ctx.home, self.ctx.cfg.paths.blocked_paths, cwd=self.ctx.home
        )

    def assess(self, args: RunShellArgs) -> Risk:
        v = self.verdict(args)
        self.last_reason = v.reason
        return v.risk

    def run(self, args: RunShellArgs) -> ToolResult:
        # Defence in depth: never execute something the policy blocks, even if called directly.
        if self.verdict(args).risk is Risk.BLOCKED:
            return self.fail("Command blocked by safety policy")
        p = self.ctx.runner.run(
            args.cmd,
            timeout=self.ctx.cfg.loop.tool_timeout_s,
            cwd=str(self.ctx.home),
            shell=True,
        )
        if p.timed_out:
            return self.fail(f"Timed out after {self.ctx.cfg.loop.tool_timeout_s}s")
        out = p.stdout
        if p.stderr.strip():
            out += ("\n" if out else "") + "[stderr] " + p.stderr
        if p.returncode != 0:
            return ToolResult(
                False,
                error=f"exit {p.returncode}: "
                + (out.strip() or "no output")[: self.ctx.cfg.loop.tool_output_cap],
            )
        return self.ok(out.strip() or "(no output)")


TOOLS = (RunShell,)
