"""Ollama chat client: streaming, keep_alive=-1, tool calling."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from orvix.core.config import LLMConfig
from orvix.core.interfaces import Chunk, Msg, ToolCall, ToolSpec


class LLMError(RuntimeError):
    pass


def _msg_to_wire(m: Msg) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [
            {"function": {"name": c.name, "arguments": c.arguments}} for c in m.tool_calls
        ]
    if m.role == "tool" and m.name:
        d["tool_name"] = m.name
    return d


def _tool_to_wire(t: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
    }


class OllamaClient:
    def __init__(self, cfg: LLMConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.cfg = cfg
        self._http = httpx.AsyncClient(
            base_url=cfg.host, timeout=httpx.Timeout(120, connect=3), transport=transport
        )

    def _payload(
        self, messages: list[Msg], tools: list[ToolSpec], think: bool, stream: bool
    ) -> dict:
        p: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [_msg_to_wire(m) for m in messages],
            "stream": stream,
            "keep_alive": self.cfg.keep_alive,
            "think": think,
            "options": {
                "num_ctx": self.cfg.num_ctx,
                "temperature": self.cfg.temperature,
                "top_p": self.cfg.top_p,
            },
        }
        if tools:
            p["tools"] = [_tool_to_wire(t) for t in tools]
        return p

    async def chat(
        self, messages: list[Msg], tools: list[ToolSpec], think: bool = False
    ) -> AsyncIterator[Chunk]:
        payload = self._payload(messages, tools, think, stream=True)
        try:
            async with self._http.stream("POST", "/api/chat", json=payload) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode(errors="replace")[:300]
                    raise LLMError(f"Ollama returned {r.status_code}: {body}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise LLMError(data["error"])
                    msg = data.get("message") or {}
                    calls = [
                        ToolCall(
                            name=c["function"]["name"],
                            arguments=_as_dict(c["function"].get("arguments")),
                        )
                        for c in msg.get("tool_calls") or []
                    ]
                    yield Chunk(
                        text=msg.get("content") or "", tool_calls=calls, done=bool(data.get("done"))
                    )
        except httpx.ConnectError as e:
            raise LLMError(f"Cannot reach Ollama at {self.cfg.host}. Is it running?") from e
        except httpx.TimeoutException as e:
            raise LLMError("Ollama timed out") from e

    async def warm(self) -> None:
        """Load the model into VRAM and keep it there (empty chat request)."""
        try:
            r = await self._http.post(
                "/api/chat",
                json={"model": self.cfg.model, "messages": [], "keep_alive": self.cfg.keep_alive},
            )
        except httpx.HTTPError as e:
            raise LLMError(f"Cannot reach Ollama at {self.cfg.host}: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"Warm-up failed ({r.status_code}): {r.text[:200]}")

    async def aclose(self) -> None:
        await self._http.aclose()


def _as_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
