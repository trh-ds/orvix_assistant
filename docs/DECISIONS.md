# Decisions, assumptions and open questions

Update this file whenever something is measured, decided or found to be wrong. Dates are the day the entry was made.

## Decided (2 Oct 2026)

| # | Decision | Reason |
| --- | --- | --- |
| 1 | Fully local; no cloud LLM, including NVIDIA-hosted Nemotron | Commands and file contents stay on the machine; works offline |
| 2 | Personal use only | Lets us use non-commercial-licensed components if needed |
| 3 | General-purpose voice agent with a broad tool set, not a fixed command list | Owner's requirement |
| 4 | One LLM on the GPU; speech and router on CPU | 6 GB VRAM holds one model; CPU speech keeps it free |
| 5 | Small fast LLM (Nemotron-3-Nano-4B) over a larger one | Latency is the main target |
| 6 | Jev-style decision router in front of the LLM | One forward pass picks the tool; LLM only sees a few tools |
| 7 | Python 3.11+, `uv`, `asyncio`, Ollama, SQLite | Best library support for local speech and LLM; owner's existing stack |
| 8 | No LangChain / LangGraph | Overhead and opacity with a 4B model |
| 9 | Safety gate with SAFE / CONFIRM / BLOCKED from day one | A small model with shell access will eventually be wrong |

## Build status (4 Oct 2026)

Code written in a cloud sandbox with no GPU, no Ollama, no audio and no desktop session. Everything below is covered by unit tests with fakes; **nothing here has been measured on `pipinstalltrh`**, so no phase acceptance check has been passed.

| Area | State |
| --- | --- |
| Scaffold, config, SQLite store, interfaces, timing | Done, tested |
| Ollama client, turn loop, `--text` mode | Done, tested against a mock and a fake Ollama server; never run against a real model |
| Safety policy + gate | Done; 70+ policy cases; destructive commands never run unconfirmed in tests |
| Tools: apps, files, shell, system, desktop, web, timers, memory | Done with mocked backends; real backends untested |
| Router | Fast rules + similarity top-k (option 3). Router-only eval on the seed set: ~95% tool offered, 17/17 fast-path correct, 0.05 ms/decision. Default stays `engine = "none"` until `orvix eval` on the real model shows no accuracy drop |
| Eval set | 106 seed cases written by the assistant, **not** the owner's real commands. Replace/extend with real ones in Phase 3 |
| Voice (STT, VAD, TTS, wake word), stop-hotkey listener, systemd, MCP server | Not started; need the laptop |

Next, on the laptop: `uv run orvix probe`, pull the model, `uv run orvix bench`, `uv run orvix eval`, then paste the numbers into the measurement log below.

## Assumptions not yet verified

Each of these came from a model card, README or tool output, not from a test on this machine. Phase 0 resolves them.

| # | Assumption | Source | Result |
| --- | --- | --- | --- |
| A1 | Nemotron-3-Nano-4B needs ~3 GB at 4-bit and supports tool calling | Unsloth run guide | |
| A2 | An Ollama tag or loadable GGUF exists for it and tool calls work through Ollama | Not confirmed | |
| A3 | The 4B model has a reasoning on/off switch | Not confirmed | |
| A4 | JEV-CPU / SemIf with Qwen3-0.6B gives ~1 s decisions on CPU for short inputs | JEV-CPU model card | |
| A5 | The same logit technique can run on the GPU LLM through the chosen runtime | Not confirmed | |
| A6 | `faster-whisper` small/base on CPU meets the 400 ms STT budget | Not measured | |
| A7 | OpenJarvis can host a custom router and external tools over MCP | Its docs list MCP and shell tools; router hook not confirmed | |
| A8 | `ddgs` works for keyless web search | Not confirmed | |
| A9 | Qwen2.5-7B-Instruct at Q3_K_M runs ~29 tok/s fully on GPU | `whichllm` estimate on this laptop | |

## Open questions for the owner

- [ ] X11 or Wayland (`orvix probe` prints it), and which desktop environment? (Phase 0 detects it; decides the keyboard and window backends.)
- [ ] How much system RAM? (Decides Whisper model size and whether the CPU router fits comfortably.)
- [ ] Wake word: "Orvix", "Jarvis", or something else?
- [ ] Should it speak every confirmation, or use a notification with a key press when you are in a call or playing audio?
- [ ] Which folders, if any, should be off limits beyond the secret paths in `TOOLS.md`?

## Considered and dropped

| Option | Why dropped |
| --- | --- |
| OpenJev (27B decision model) | Smallest build ~15 GB; does not fit 6 GB VRAM. Technique kept via SemIf / JEV-CPU. |
| isair/jarvis as base | Voice-only, no shell tool, default model wants 8 GB+ VRAM |
| novik133/jarvis | KDE Plasma 6 only, C++ |
| OpenClaw, Goose, Open Interpreter | Built around messaging or coding; too heavy for a 4B model |
| Qwen2.5-7B-Instruct as primary | Kept as fallback; uses 5.5 of 6 GB and is slower than a 4B model |

## Measurement log

Append `orvix bench` and `orvix eval` results here after every phase.

| Date | Phase | LLM | Router | Eval accuracy | End of speech → action (median) | End of speech → first word (median) | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |
