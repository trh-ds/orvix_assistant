# Tools and safety — Orvix Assistant

Each tool is one class implementing the `Tool` protocol in `orvix/core/interfaces.py`, registered in `orvix/tools/registry.py`. Descriptions are one line, written for a 4B model. Backends marked **VERIFY** depend on the desktop session (X11 vs Wayland), detected in Phase 0.

## Risk levels

- **SAFE** — runs immediately.
- **CONFIRM** — assistant says what it will do and waits for "yes" (voice or key). Times out to "no" after 10 s.
- **BLOCKED** — never runs.

## Catalogue

### Apps and windows (category: `apps`)

| Tool | Does | Backend | Risk |
| --- | --- | --- | --- |
| `open_app(name)` | Launch an app by name | `.desktop` lookup + `gtk-launch` | SAFE |
| `close_app(name)` | Close an app's windows | `wmctrl` / compositor **VERIFY** | CONFIRM |
| `focus_window(name)` | Bring a window to front | `wmctrl` / compositor **VERIFY** | SAFE |
| `open_in_vscode(path)` | Open a file or folder in VS Code | `code <path>` | SAFE |
| `open_url(url)` | Open a URL in the default browser | `xdg-open` | SAFE |

### Files (category: `files`)

| Tool | Does | Backend | Risk |
| --- | --- | --- | --- |
| `find_path(query)` | Resolve a spoken name or alias to a real path | alias table, then `fd` / `locate` | SAFE |
| `list_dir(path)` | List a folder | Python | SAFE |
| `read_file(path)` | Read a text file (capped) | Python | SAFE |
| `write_file(path, content)` | Create or overwrite a file | Python | CONFIRM |
| `open_file(path)` | Open with the default app | `xdg-open` | SAFE |

### Shell (category: `shell`)

| Tool | Does | Backend | Risk |
| --- | --- | --- | --- |
| `run_shell(cmd)` | Run a command, return output | `subprocess`, no shell expansion unless needed | by policy below |

### Keyboard and screen (category: `desktop`)

| Tool | Does | Backend | Risk |
| --- | --- | --- | --- |
| `type_text(text)` | Type into the focused window | `xdotool` (X11) / `ydotool` (Wayland) | CONFIRM |
| `press_keys(combo)` | Send a shortcut, e.g. `ctrl+s` | same | CONFIRM |
| `screenshot()` | Save a screenshot, return the path | `scrot` / `grim` | SAFE |
| `clipboard_get()` / `clipboard_set(text)` | Read / write clipboard | `xclip` / `wl-clipboard` | SAFE |

### System (category: `system`) — fast-path candidates

| Tool | Does | Backend | Risk |
| --- | --- | --- | --- |
| `volume(action)` | up / down / mute / set N | `wpctl` or `pactl` **VERIFY** | SAFE |
| `brightness(action)` | up / down / set N | `brightnessctl` | SAFE |
| `media(action)` | play / pause / next / previous | `playerctl` | SAFE |
| `wifi(state)` / `bluetooth(state)` | on / off | `nmcli` / `bluetoothctl` | SAFE |
| `lock_screen()` | Lock the session | `loginctl lock-session` | SAFE |
| `suspend()` | Suspend the laptop | `systemctl suspend` | CONFIRM |
| `system_info(kind)` | battery / cpu / ram / disk / top processes | `psutil` | SAFE |
| `notify(text)` | Desktop notification | `notify-send` | SAFE |

### Information (category: `info`)

| Tool | Does | Backend | Risk |
| --- | --- | --- | --- |
| `web_search(query)` | Top results with snippets | `ddgs` library (DuckDuckGo, no API key) **VERIFY**; SearXNG as alternative | SAFE |
| `fetch_page(url)` | Fetch and extract readable text (capped) | `httpx` + `trafilatura` | SAFE |
| `now()` | Date and time | Python | SAFE |
| `set_timer(seconds, label)` / `set_reminder(when, text)` | Timer or reminder with notification + spoken alert | asyncio + SQLite | SAFE |

### Memory (category: `memory`)

| Tool | Does | Risk |
| --- | --- | --- |
| `remember(key, value)` | Store a fact or folder alias | SAFE |
| `recall(query)` | Look up stored facts | SAFE |
| `forget(key)` | Delete a stored fact | CONFIRM |

## Shell policy

Evaluated on the parsed command, in this order:

1. **BLOCKED:** `sudo`, `su`, `dd`, `mkfs`, `shutdown`/`reboot` via shell, fork bombs, piping a download into a shell (`curl … | sh`), writes to `/etc`, `/boot`, `/usr`, `/dev`.
2. **CONFIRM:** `rm`, `mv`, `cp` over existing files, `chmod`, `chown`, `kill`, `pkill`, package managers (`apt`, `pip install`, `npm install -g`), `git push`, `git reset --hard`, any redirect that overwrites a file, anything touching paths outside `/home/tirth-patel`.
3. **SAFE (allowlist):** `ls`, `cat`, `head`, `tail`, `pwd`, `whoami`, `date`, `df`, `du`, `free`, `uptime`, `ps`, `which`, `grep`, `find`, `fd`, `wc`, `git status`, `git log`, `git diff`, `git branch`.
4. **Everything else:** CONFIRM.

Chained commands (`&&`, `;`, `|`) take the highest risk of their parts.

## Global safety rules

- **Stop hotkey:** one global key combination cancels the current turn, kills running subprocesses and stops TTS. Must work while `type_text` is typing.
- **Web content is untrusted.** Text returned by `web_search` / `fetch_page` is data. In any turn that has read web content, every non-SAFE tool requires confirmation, and the system prompt tells the model not to follow instructions found in tool results.
- **No secrets.** The assistant never reads `~/.ssh`, `~/.gnupg`, browser profiles, `.env` files or password stores. Enforced in `read_file`, `list_dir` and `run_shell` path checks.
- **Timeouts and caps:** 30 s per tool, 2,000 characters of output returned to the model.
- **Audit log:** every tool call, its risk level and whether it was confirmed is written to `tool_calls`.
- **Runs as the normal user.** No elevated privileges, ever.

## Adding a tool

1. New class in `orvix/tools/<group>.py` with `name`, one-line `description`, pydantic `params`, `risk`, `run`.
2. Register it and assign a category.
3. Add at least three eval cases to `evals/commands.jsonl`.
4. Add a unit test with the backend mocked.
