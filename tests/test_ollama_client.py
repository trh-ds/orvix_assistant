import json

import httpx
import pytest

from orvix.core.config import LLMConfig
from orvix.core.interfaces import Msg, ToolSpec
from orvix.llm.ollama_client import LLMError, OllamaClient


def ndjson(*objs):
    return "\n".join(json.dumps(o) for o in objs).encode()


async def collect(client, **kw):
    return [c async for c in client.chat([Msg("user", "hi")], kw.get("tools", []))]


async def test_streams_text_and_sends_keepalive():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(
            200,
            content=ndjson(
                {"message": {"content": "Hel"}, "done": False},
                {"message": {"content": "lo."}, "done": False},
                {"message": {"content": ""}, "done": True},
            ),
        )

    c = OllamaClient(LLMConfig(), transport=httpx.MockTransport(handler))
    chunks = await collect(c)
    assert "".join(x.text for x in chunks) == "Hello." and chunks[-1].done
    assert seen["keep_alive"] == -1 and seen["stream"] is True and seen["think"] is False
    assert seen["options"]["num_ctx"] == 4096


async def test_tool_calls_parsed_and_tools_sent():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(
            200,
            content=ndjson(
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": "open_url", "arguments": {"url": "x.com"}}},
                            {"function": {"name": "now", "arguments": "{}"}},
                        ]
                    },
                    "done": True,
                }
            ),
        )

    c = OllamaClient(LLMConfig(), transport=httpx.MockTransport(handler))
    spec = ToolSpec("open_url", "d", {"type": "object", "properties": {}})
    chunks = await collect(c, tools=[spec])
    calls = chunks[0].tool_calls
    assert [(x.name, x.arguments) for x in calls] == [("open_url", {"url": "x.com"}), ("now", {})]
    assert seen["tools"][0]["function"]["name"] == "open_url"


async def test_http_error_and_connect_error():
    c = OllamaClient(
        LLMConfig(), transport=httpx.MockTransport(lambda r: httpx.Response(404, text="no model"))
    )
    with pytest.raises(LLMError, match="404"):
        await collect(c)

    def boom(req):
        raise httpx.ConnectError("refused")

    c = OllamaClient(LLMConfig(), transport=httpx.MockTransport(boom))
    with pytest.raises(LLMError, match="Is it running"):
        await collect(c)


async def test_warm_sends_empty_messages():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"done": True})

    await OllamaClient(LLMConfig(), transport=httpx.MockTransport(handler)).warm()
    assert seen["messages"] == [] and seen["keep_alive"] == -1
