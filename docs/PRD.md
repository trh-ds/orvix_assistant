# PRD — Orvix Assistant

## Intent

Build a personal voice assistant that lives on one Linux laptop and does things on it, the way Jarvis does for Tony Stark. You say what you want; it carries it out and tells you what happened. Everything runs on the laptop.

## Why

- Existing local assistants are either chat-only, tied to one desktop, built for macOS/Windows, or too heavy for a 6 GB GPU.
- Cloud assistants send every command and file off the machine and stop working offline.
- A small local model is fast enough for command-style requests if the pipeline is built around latency from the start.

## User

One user: the laptop's owner, a developer. No accounts, no multi-user, no commercial use.

## Goals

1. **General purpose.** Not a fixed command list. Any request that maps to the available tools should work, including multi-step ones ("find my resume PDF and open it").
2. **Fast.** A simple command starts executing within about 1.5 s of the user finishing speaking. See the latency budget in `DESIGN.md`.
3. **Local.** LLM, speech and decisions all run on-device.
4. **Safe.** Nothing destructive runs without a spoken or typed confirmation.
5. **Extensible.** Adding a tool is one file and one registry entry.
6. **Improves with use.** Every turn is logged so the model can be prompt-tuned or fine-tuned later on the user's own commands.

## Non-goals (v1)

- Cloud LLM fallback
- Vision / screen understanding (screenshots are captured but not interpreted)
- Mobile app, remote access, messaging integrations
- Smart-home control
- Acting autonomously without a direct request (no proactive agents in v1)

## What it must do

### Interaction

- Wake word, then free-form speech. Also a push-to-talk hotkey.
- Text mode in a terminal for development and silent use.
- Spoken replies, short by default. Barge-in: speaking over it stops playback.
- A global stop hotkey that halts the current action immediately.

### Capabilities (full list in `TOOLS.md`)

- Open and close apps, open folders/files in VS Code, open URLs
- Run shell commands and report the result
- Find, read and write files
- Type text and press keyboard shortcuts in the focused window
- Clipboard, screenshots, window focus
- Volume, brightness, media playback, Wi-Fi/Bluetooth, lock/suspend, battery and system info
- Web search and page fetch, summarised by the local model
- Time, timers, reminders
- Remember and recall facts and folder aliases across restarts

### Behaviour

- Asks one short clarifying question when a request is ambiguous instead of guessing at a risky action.
- Says what it is about to do before any confirmed action, and what happened after.
- Fails out loud: if a tool errors, it reports the error in one sentence.

## Success criteria

| Measure | Target |
| --- | --- |
| Correct tool + arguments on the eval set (100 real commands) | ≥ 90% |
| End of speech → action starts (simple command) | ≤ 1.5 s median |
| End of speech → first spoken word (reply needing the LLM) | ≤ 2.5 s median |
| Destructive commands executed without confirmation | 0 |
| Works with networking disabled (except web tools) | Yes |
| Idle VRAM use | One LLM only, under 6 GB |

Latency targets are goals to validate in Phase 0, not measured results.

## Example requests

- "Open VS Code in my orvix folder."
- "What's using all my RAM?"
- "Search the web for the latest llama.cpp release and tell me what changed."
- "Type my email address here."
- "Set a timer for 20 minutes."
- "Remember that my college folder is ~/clg."
- "Turn the volume down and pause the music."
- "Delete the build folder in this project." → must ask for confirmation first.
