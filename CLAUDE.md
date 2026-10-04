# Orvix Assistant

A fully local, general-purpose voice assistant for one user's Linux laptop. Think Jarvis: you speak, it acts on the machine (apps, shell, keyboard, files, web search) and answers out loud. Personal use only.

## Read these before writing code, in this order

1. `docs/PRD.md` — what we are building and why
2. `docs/DESIGN.md` — architecture, latency budget, interfaces
3. `docs/TOOLS.md` — tool catalogue and safety policy
4. `docs/IMPLEMENTATION_PLAN.md` — phases and acceptance checks
5. `docs/DECISIONS.md` — what is decided, what is unverified, what is open

## Non-negotiables

* Local only. No cloud LLM, no cloud speech. The only network use is the `web_search` / `fetch_page` tools and model downloads.
* Low latency is the main target. Every phase measures latency against the budget in `docs/DESIGN.md`. A feature that breaks the budget is not done.
* One model on the GPU. The 6 GB of VRAM holds exactly one LLM. Speech-to-text, text-to-speech, wake word and the decision router run on CPU threads.
* The LLM never touches the machine directly. It picks a tool and arguments; Python executes after the safety gate.
* Safety gate is not optional. No tool ships without a risk level from `docs/TOOLS.md`.

## Target machine

* Linux x64, device name `pipinstalltrh`, user home `/home/tirth-patel`
* GPU: NVIDIA RTX 4050, 6 GB VRAM
* Unknown, detect in Phase 0 and record in `docs/DECISIONS.md`: system RAM, CPU core count, X11 vs Wayland, desktop environment
* Project root: `/home/tirth-patel/survival/orvix_assistant`

## Stack

* Python 3.11+, `uv` for environments and dependencies, `asyncio` for the pipeline
* LLM runtime: Ollama, model kept loaded (`keep_alive: -1`), streaming on
* Storage: SQLite (one file under `data/`)
* Tests: `pytest`; lint/format: `ruff`
* No LangChain / LangGraph. A plain loop is easier to keep fast and to debug with a 4B model.

## Commands

```bash
uv sync                       # install
uv run orvix --text           # text mode (no mic), for development
uv run orvix                  # full voice mode
uv run orvix bench            # latency benchmark, prints per-stage timings
uv run orvix eval             # run the command eval set, prints accuracy
uv run pytest                 # tests
uv run ruff check . && uv run ruff format .
```

## Working rules

* Build phase by phase. Do not start a phase until the previous one passes its acceptance check.
* Every stage sits behind an interface in `orvix/core/interfaces.py` so a model or engine can be swapped without touching the loop.
* Model names, tags and thresholds live in `config.toml`, never hard-coded.
* Log every turn to SQLite (see `docs/DESIGN.md`, Storage). These traces are the future fine-tuning dataset.
* Anything marked VERIFY in the docs is an assumption taken from a model card or README, not something tested on this machine. Check it before relying on it and write the result into `docs/DECISIONS.md`.
* Do not add `sudo` handling, and never store or ask for the sudo password.
* When a library or model does not behave as these docs assume, stop and record it in `docs/DECISIONS.md` rather than working around it silently.
