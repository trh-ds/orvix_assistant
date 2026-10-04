"""Memory (category: memory): facts and folder aliases that survive restarts."""

from __future__ import annotations

from pydantic import BaseModel, Field

from orvix.core.interfaces import Risk, ToolResult
from orvix.tools.base import BaseTool


class RememberArgs(BaseModel):
    key: str = Field(description="Short name, e.g. 'college folder' or 'my email'")
    value: str = Field(description="What to remember, e.g. '~/clg'")


class Remember(BaseTool):
    name = "remember"
    category = "memory"
    description = "Store a fact or folder alias for later."
    params = RememberArgs

    def run(self, args: RememberArgs) -> ToolResult:
        if not args.key.strip() or not args.value.strip():
            return self.fail("Both a name and a value are needed")
        self.ctx.store.remember(args.key, args.value)
        return self.ok(f"Remembered {args.key.strip().lower()} = {args.value}")


class RecallArgs(BaseModel):
    query: str = Field(description="What to look up")


class Recall(BaseTool):
    name = "recall"
    category = "memory"
    description = "Look up stored facts and aliases."
    params = RecallArgs

    def run(self, args: RecallArgs) -> ToolResult:
        direct = self.ctx.store.get_fact(args.query)
        if direct is not None:
            return self.ok(f"{args.query.strip().lower()}: {direct}")
        found = self.ctx.store.search_facts(args.query)
        if not found:
            return self.fail(f"Nothing stored for '{args.query}'")
        return self.ok("\n".join(f"{k}: {v}" for k, v in found))


class ForgetArgs(BaseModel):
    key: str = Field(description="Name of the fact to delete")


class Forget(BaseTool):
    name = "forget"
    category = "memory"
    description = "Delete a stored fact."
    params = ForgetArgs
    risk = Risk.CONFIRM

    def run(self, args: ForgetArgs) -> ToolResult:
        if self.ctx.store.forget(args.key):
            return self.ok(f"Forgot {args.key.strip().lower()}")
        return self.fail(f"Nothing stored under '{args.key}'")


TOOLS = (Remember, Recall, Forget)
