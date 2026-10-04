# Implementation plan — Orvix Assistant

Build in order. Each phase ends with an acceptance check; do not start the next until it passes. After every phase, run `orvix bench` and `orvix eval` and append the numbers to `docs/DECISIONS.md`.

## Phase 0 — Probe the machine and the models

Purpose: replace every **VERIFY** in the docs with a measured fact before building on it.

- [ ] Scaffold: `pyproject.toml`, `uv`, `ruff`, `pytest`, `config.toml`, package skeleton, `.gitignore` (`data/`).
- [ ] `orvix probe`: print RAM, CPU cores, GPU + free VRAM, `XDG_SESSION_TYPE`, desktop environment, and which backends exist (`xdotool`, `ydotool`, `wmctrl`, `wpctl`, `pactl`, `playerctl`, `brightnessctl`, `fd`, `scrot`, `grim`, `xclip`, `wl-copy`).
- [ ] Get Nemotron-3-Nano-4B running in Ollama (find the tag or pull the GGUF from Hugging Face). Confirm a tool call round-trips. If it cannot be made to work, fall back to `qwen3.5:4b`.
- [ ] `orvix bench` v0: time to first token and tokens/s for the LLM; `faster-whisper` `base.en` vs `small.en` on a 3 s clip (CPU, int8); Piper time to first audio; router decision time for options 1–3 in `DESIGN.md`.
- [ ] Confirm the LLM sits 100% on GPU (`ollama ps`) with STT/TTS/router loaded at the same time.
- [ ] OpenJarvis spike, time-boxed to half a day: install it, check whether a custom router can sit in front of its LLM call and whether tools can be added over MCP. Record host decision.

**Accept when:** `docs/DECISIONS.md` has measured numbers for every budget line, a chosen router option, a chosen LLM, and the host-framework decision.

## Phase 1 — Text loop with core tools

- [ ] `interfaces.py`, `loop.py`, `timing.py`, `config.py`.
- [ ] Ollama client: streaming, `keep_alive: -1`, warm-up call at start, tool calling.
- [ ] Tool registry + `open_app`, `open_in_vscode`, `open_url`, `find_path`, `list_dir`, `read_file`, `now`, `system_info`.
- [ ] `orvix --text` chat loop.
- [ ] SQLite `turns` and `tool_calls` logging.

**Accept when:** "open VS Code in my orvix folder" and nine other phrasings of core commands succeed ≥ 9/10 in text mode.

## Phase 2 — Safety gate and shell

- [ ] `safety/policy.py` implementing the shell policy and risk levels in `TOOLS.md`.
- [ ] `safety/gate.py`: confirm flow (typed for now), timeouts, output caps, secret-path blocking.
- [ ] `run_shell`, `write_file`, `open_file`.
- [ ] Unit tests for every BLOCKED and CONFIRM pattern.

**Accept when:** the policy test suite passes and no destructive command in the tests runs without confirmation.

## Phase 3 — Eval set and model choice

- [ ] Write `evals/commands.jsonl`: 100 real commands with expected tool + arguments, including "should ask to clarify", "should confirm" and "should refuse" cases.
- [ ] `orvix eval`: accuracy on tool choice and on arguments, plus latency per case.
- [ ] Run for Nemotron-3-Nano-4B, `qwen3.5:4b`, Qwen2.5-7B-Instruct.
- [ ] Tune the system prompt and tool descriptions on failures (keep 20 cases held out).

**Accept when:** one model reaches ≥ 90% on the eval set within the LLM latency budget, and the choice is written to `DECISIONS.md`. If none does, record the best and continue; fine-tuning (Phase 9) closes the gap.

## Phase 4 — Router

- [ ] Implement the router option chosen in Phase 0 behind the `Router` interface.
- [ ] Categories → top-k tools passed to the LLM; fast path for zero-argument tools.
- [ ] Confidence threshold with fall-through to the LLM.
- [ ] Add router accuracy to `orvix eval`.

**Accept when:** eval accuracy does not drop versus Phase 3, and median latency for fast-path commands meets the 1.5 s target in text mode (measured from input to action).

## Phase 5 — System, desktop and info tools

- [ ] System group: `volume`, `brightness`, `media`, `wifi`, `bluetooth`, `lock_screen`, `suspend`, `notify`.
- [ ] Desktop group: `type_text`, `press_keys`, `screenshot`, clipboard, `focus_window`, `close_app` using the backends found in Phase 0.
- [ ] Global stop hotkey.
- [ ] Info group: `web_search`, `fetch_page`, with the untrusted-content rule.
- [ ] `set_timer`, `set_reminder`.
- [ ] Eval cases for each new tool.

**Accept when:** every tool has passing tests and eval cases, the stop hotkey interrupts `type_text` mid-string, and a web-search question is answered from fetched content.

## Phase 6 — Voice

- [ ] Audio capture, Silero VAD endpointing, `faster-whisper` on a CPU thread.
- [ ] Piper TTS with sentence-chunk streaming and interruptible playback (barge-in).
- [ ] Push-to-talk hotkey first, then openWakeWord.
- [ ] Spoken confirmations ("yes" / "no") for CONFIRM tools.
- [ ] Short spoken acks for fast-path actions.

**Accept when:** a full spoken command runs hands-free, and `orvix bench` end-to-end meets both headline targets (≤ 1.5 s to action, ≤ 2.5 s to first spoken word) at the median over 20 commands.

## Phase 7 — Memory

- [ ] `remember`, `recall`, `forget`; `facts` table.
- [ ] Alias resolution inside `find_path`.
- [ ] Fact retrieval and injection before LLM calls.

**Accept when:** "remember that my college folder is ~/clg" survives a restart and "open my college folder" works afterwards.

## Phase 8 — Always-on

- [ ] `systemd --user` service, starts at login, restarts on failure.
- [ ] Tray icon or notification for state (listening / thinking / speaking / muted).
- [ ] Mute toggle hotkey.
- [ ] MCP server exposing the tool registry (`orvix/mcp_server.py`).
- [ ] Log rotation.

**Accept when:** it survives a reboot and a full day of use without manual restarts.

## Phase 9 — Learn from traces (only after a few weeks of real use)

- [ ] Export corrected traces to a training file.
- [ ] Prompt/tool-description optimisation from failures.
- [ ] If still under 90%: QLoRA fine-tune of the chosen model (Unsloth), export GGUF, load into Ollama, re-run the eval set.

**Accept when:** the tuned model beats the base model on the held-out eval cases; otherwise keep the base model.

## Order of risk

The three things most likely to break the plan, all tested in Phase 0:

1. Router speed on CPU does not meet 300 ms.
2. Nemotron-3-Nano-4B tool calling is unreliable through Ollama.
3. Wayland blocks keyboard injection or window control for the chosen backends.
