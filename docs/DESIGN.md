# Design — Orvix Assistant

## Shape

Three compute lanes, fixed:

| Lane | Runs | Why |
| --- | --- | --- |
| CPU threads | Wake word, VAD, speech-to-text, text-to-speech | Keeps the GPU free for the LLM |
| CPU | Decision router (tiny model, one forward pass, no text generation) | Picks the tool in one step |
| GPU (6 GB) | One LLM | Fills in arguments, reasons, writes replies |

## Pipeline

```
mic ─► wake word ─► VAD ─► STT ─► ROUTER ─┬─► fast path: zero-arg tool ─► safety gate ─► execute ─► short spoken ack
                                          │
                                          └─► LLM (with only the router's top-k tools)
                                                 │  tool call
                                                 ▼
                                             safety gate ─► execute ─► result back to LLM ─► … ─► reply
                                                                                                   │
                                                                         sentence chunks ─► TTS ─► speaker
```

Every stage emits a timing event and the whole turn is written to SQLite.

## Models

| Role | Choice | Notes |
| --- | --- | --- |
| LLM (GPU) | Nemotron-3-Nano-4B, 4-bit GGUF | About 3 GB at 4-bit, supports tool calling, model card suggests temperature 0.6 / top_p 0.95 for tool calls. **VERIFY** the exact Ollama tag or Hugging Face GGUF repo, and that tool calling works through Ollama. |
| LLM fallbacks | `qwen3.5:4b`, then Qwen2.5-7B-Instruct | Qwen2.5-7B was the top `whichllm` result for this laptop (5.5 GB at Q3_K_M, ~29 tok/s estimated). Use whichever wins the eval set in Phase 3. |
| Router (CPU) | Jev-style logit decision, using the SemIf engine as packaged in `Meanblock/JEV-CPU` (MIT), default model `Qwen/Qwen3-0.6B` | Model card: ~2.4 GB RAM, ~1 s per decision for short inputs on CPU. **VERIFY** speed and accuracy on this CPU. |
| STT (CPU) | `faster-whisper`, `base.en` or `small.en`, int8 | Pick the largest that meets the STT budget. |
| VAD | Silero VAD | End-of-speech detection. |
| Wake word | openWakeWord | Custom wake word "Orvix" later; start with a stock one. |
| TTS (CPU) | Piper | Stream sentence by sentence. |

OpenJev itself (27B, smallest build ~15 GB) does not fit this machine; only the technique is used.

## Latency budget

Targets for a short command, to be validated in Phase 0. Not measured yet.

| Stage | Target |
| --- | --- |
| End-of-speech detection (VAD hangover) | ≤ 400 ms |
| STT, 3-second utterance | ≤ 400 ms |
| Router decision | ≤ 300 ms |
| LLM time to first token | ≤ 400 ms |
| LLM tool call complete (short args) | ≤ 800 ms |
| TTS time to first audio | ≤ 300 ms |
| **Fast path: end of speech → action starts** | **≤ 1.5 s** |
| **LLM path: end of speech → first spoken word** | **≤ 2.5 s** |

The router's 300 ms target is tighter than the ~1 s its model card reports. Phase 0 measures the real number; see "Router options" for what to do if it misses.

### Latency rules

- LLM stays loaded permanently (`keep_alive: -1`); warm it at startup with a dummy request.
- Fixed system prompt and tool block at the front of every request so the runtime can reuse its prompt cache.
- Send the LLM only the router's top-k tools (k = 3–5), not the full catalogue.
- `num_ctx` 4096 by default; raise only for web-page summarisation.
- Reasoning/thinking off by default; on only when the router says "multi-step". **VERIFY** the 4B model exposes a reasoning toggle.
- Stream LLM output; start TTS on the first complete sentence.
- STT, TTS, router and wake word each own a worker thread and are loaded once.
- Cap tool output fed back to the model (2,000 characters).
- No blocking I/O on the event loop.

## Router

Input: the transcript plus a compact state line (focused app, last tool). Output: one decision.

Stage 1 — route:

- `FAST:<tool>` — a zero-argument or fixed-argument tool (volume up, pause, lock, screenshot). Execute directly.
- `LLM:<category>` — needs arguments or reasoning. Category selects the tool subset passed to the LLM.
- `MULTI` — multi-step; pass to LLM with reasoning on.
- `CHAT` — no tool; LLM answers.
- `UNSURE` — top probability below threshold; fall through to LLM with the top-k tools.

The decision engine reads option-letter probabilities from one forward pass, so keep each decision to at most 26 options. Use categories first, then tools within a category if needed.

### Router options (decide in Phase 0 by measurement)

1. Qwen3-0.6B on CPU via JEV-CPU's engine (default).
2. Same technique on the GPU LLM itself, if the runtime exposes token logprobs. One model does both jobs and removes the CPU model. **VERIFY** feasibility.
3. No separate router: embedding similarity against tool descriptions for top-k selection, LLM does the rest.

Pick the fastest option that keeps eval accuracy; record the numbers in `DECISIONS.md`.

## Host framework

OpenJarvis (Stanford, Apache-2.0) is the intended outer framework: it already provides an agent loop, Ollama integration, speech modules, MCP support and a trace-based learning loop. Whether it can host a custom router in front of the LLM and still meet the latency budget is **unverified**.

So the code is written as a standalone package with clean interfaces, and tools are also exposed through an MCP server. Phase 0 includes a time-boxed spike:

- If OpenJarvis can run this pipeline within budget → use it as the host, plug the tools in over MCP.
- If not → keep our own thin loop and reuse OpenJarvis only for its learning loop on our traces, or not at all.

## Package layout

```
orvix_assistant/
├── CLAUDE.md
├── config.toml
├── pyproject.toml
├── docs/
├── data/                  # SQLite db, models cache (gitignored)
├── evals/commands.jsonl   # the 100-command eval set
├── orvix/
│   ├── cli.py             # orvix, orvix --text, bench, eval
│   ├── core/
│   │   ├── interfaces.py  # STT, TTS, Router, LLM, Tool protocols
│   │   ├── loop.py        # turn orchestration
│   │   ├── timing.py      # per-stage timers
│   │   └── config.py
│   ├── audio/             # wake.py, vad.py, stt.py, tts.py, playback.py
│   ├── router/            # decision.py, embed_fallback.py
│   ├── llm/               # ollama_client.py, prompts.py
│   ├── tools/             # registry.py + one file per tool group
│   ├── safety/            # gate.py, policy.py
│   ├── memory/            # store.py (facts, aliases), traces.py
│   └── mcp_server.py      # exposes tools over MCP
└── tests/
```

## Interfaces (sketch)

```python
class STT(Protocol):
    def transcribe(self, pcm: np.ndarray) -> str: ...

class Router(Protocol):
    def decide(self, text: str, state: State) -> Decision: ...   # Decision(kind, tool, category, confidence)

class LLM(Protocol):
    def chat(self, messages: list[Msg], tools: list[ToolSpec], think: bool) -> AsyncIterator[Chunk]: ...

class Tool(Protocol):
    name: str
    description: str          # one line, written for a 4B model
    params: type[BaseModel]   # pydantic schema
    risk: Risk                # SAFE | CONFIRM | BLOCKED
    def run(self, args: BaseModel) -> ToolResult: ...

class TTS(Protocol):
    def speak(self, text: str) -> None: ...      # non-blocking, interruptible
```

## Agent loop limits

- Maximum 5 tool calls per turn.
- 30-second timeout per tool.
- On invalid tool JSON: one retry with the validation error, then a spoken failure.

## Storage (SQLite)

- `turns` — id, timestamp, transcript, router decision + confidence, final reply, per-stage timings (JSON), success flag, user correction
- `tool_calls` — turn id, tool, args JSON, risk, confirmed, result, error, duration
- `facts` — key, value, created, last used (folder aliases, preferences)
- `reminders` — due time, text, done

`turns` + `tool_calls` are the fine-tuning dataset later.

## Memory

Before each LLM call, retrieve up to 5 relevant `facts` (keyword match first; embeddings only if needed) and inject them as one short block. Folder aliases resolve in `find_path` without the LLM.

## Later: improving the model

Not in v1 scope, but the traces are designed for it:

1. Prompt and tool-description tuning from failed eval cases.
2. QLoRA fine-tune of the chosen 4B model on corrected traces (Unsloth; a 4B model trains in roughly 4 GB VRAM), export to GGUF, re-run the eval set, keep it only if it scores higher.
