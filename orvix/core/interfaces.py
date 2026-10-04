"""Protocols for every swappable stage. The loop depends only on these."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel


class Risk(StrEnum):
    SAFE = "SAFE"
    CONFIRM = "CONFIRM"
    BLOCKED = "BLOCKED"


_RISK_ORDER = {Risk.SAFE: 0, Risk.CONFIRM: 1, Risk.BLOCKED: 2}


def max_risk(*risks: Risk) -> Risk:
    return max(risks, key=_RISK_ORDER.__getitem__, default=Risk.SAFE)


@dataclass
class State:
    """Compact context handed to the router."""

    focused_app: str = ""
    last_tool: str = ""
    web_content_seen: bool = False


@dataclass
class Decision:
    kind: str  # FAST | LLM | MULTI | CHAT | UNSURE
    tool: str | None = None
    category: str | None = None
    confidence: float = 0.0


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class ToolResult:
    ok: bool
    output: str = ""
    error: str = ""

    def text(self) -> str:
        return self.output if self.ok else f"ERROR: {self.error}"


@dataclass
class Msg:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    name: str = ""


@dataclass
class Chunk:
    """One streamed piece of LLM output."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False
    stats: dict[str, Any] = field(default_factory=dict)  # final chunk: runtime timing counters


@runtime_checkable
class STT(Protocol):
    def transcribe(self, pcm: Any) -> str: ...


@runtime_checkable
class Router(Protocol):
    def decide(self, text: str, state: State) -> Decision: ...


@runtime_checkable
class LLM(Protocol):
    def chat(
        self, messages: list[Msg], tools: list[ToolSpec], think: bool
    ) -> AsyncIterator[Chunk]: ...


@runtime_checkable
class TTS(Protocol):
    def speak(self, text: str) -> None: ...


class Tool(Protocol):
    name: str
    category: str
    description: str  # one line, written for a 4B model
    params: ClassVar[type[BaseModel]]
    risk: Risk

    def run(self, args: BaseModel) -> ToolResult: ...
