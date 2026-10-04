"""Tool registry: one entry per tool, grouped by category."""

from __future__ import annotations

from orvix.core.interfaces import ToolSpec
from orvix.tools.base import BaseTool, ToolContext


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> BaseTool:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def kill_all(self) -> None:
        """Kill every subprocess any tool started (stop hotkey, cancelled turn)."""
        for runner in {id(t.ctx.runner): t.ctx.runner for t in self._tools.values()}.values():
            runner.kill_all()

    def by_category(self, category: str) -> list[BaseTool]:
        return [t for t in self._tools.values() if t.category == category]

    def categories(self) -> list[str]:
        return sorted({t.category for t in self._tools.values()})

    def specs(self, names: list[str] | None = None) -> list[ToolSpec]:
        tools = (
            self._tools.values()
            if names is None
            else (self._tools[n] for n in names if n in self._tools)
        )
        return [t.spec() for t in tools]


def build_registry(ctx: ToolContext) -> Registry:
    """Register every shipped tool. New tool = one class + one line here."""
    from orvix.tools import apps, files, info, shell

    reg = Registry()
    for cls in (*apps.TOOLS, *files.TOOLS, *info.TOOLS, *shell.TOOLS):
        reg.register(cls(ctx))
    return reg
