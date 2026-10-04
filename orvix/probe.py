"""`orvix probe`: detect the machine facts that Phase 0 must record in docs/DECISIONS.md."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess

import httpx
import psutil

BACKENDS = [
    "xdotool", "ydotool", "wmctrl", "wpctl", "pactl", "playerctl", "brightnessctl",
    "fd", "fdfind", "scrot", "grim", "xclip", "wl-copy", "gtk-launch", "xdg-open",
    "notify-send", "nmcli", "bluetoothctl", "loginctl", "code", "ollama", "piper",
]  # fmt: skip


def gpu_info() -> dict:
    if not shutil.which("nvidia-smi"):
        return {"available": False}
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()[0]  # fmt: skip
        name, total, used, free, driver = [x.strip() for x in out.split(",")]
        return {
            "available": True, "name": name, "vram_total_mb": int(total),
            "vram_used_mb": int(used), "vram_free_mb": int(free), "driver": driver,
        }  # fmt: skip
    except (subprocess.SubprocessError, IndexError, ValueError):
        return {"available": False}


def ollama_info(host: str) -> dict:
    try:
        r = httpx.get(f"{host}/api/tags", timeout=2)
        models = [m["name"] for m in r.json().get("models", [])]
        ps = httpx.get(f"{host}/api/ps", timeout=2).json().get("models", [])
        loaded = [
            {
                "name": m["name"],
                "size_vram_mb": round(m.get("size_vram", 0) / 2**20),
                "size_mb": round(m.get("size", 0) / 2**20),
            }
            for m in ps
        ]
        return {"reachable": True, "models": models, "loaded": loaded}
    except (httpx.HTTPError, ValueError):
        return {"reachable": False}


def collect(host: str = "http://localhost:11434") -> dict:
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "ram_available_gb": round(psutil.virtual_memory().available / 2**30, 1),
        "cpu_physical_cores": psutil.cpu_count(logical=False),
        "cpu_logical_cores": psutil.cpu_count(),
        "gpu": gpu_info(),
        "session_type": os.environ.get("XDG_SESSION_TYPE", "unknown"),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
        "backends": {b: bool(shutil.which(b)) for b in BACKENDS},
        "ollama": ollama_info(host),
    }


def render(info: dict) -> str:
    g = info["gpu"]
    gpu = (
        f"{g['name']}  VRAM {g['vram_used_mb']}/{g['vram_total_mb']} MB used (driver {g['driver']})"
        if g["available"]
        else "none detected (nvidia-smi missing)"
    )
    o = info["ollama"]
    if o["reachable"]:
        loaded = ", ".join(
            f"{m['name']} ({m['size_vram_mb']}/{m['size_mb']} MB in VRAM)" for m in o["loaded"]
        )
        ollama = f"running; models: {', '.join(o['models']) or 'none'}; loaded: {loaded or 'none'}"
    else:
        ollama = "not reachable"
    have = [b for b, ok in info["backends"].items() if ok]
    miss = [b for b, ok in info["backends"].items() if not ok]
    return "\n".join(
        [
            f"OS:        {info['os']}",
            f"RAM:       {info['ram_gb']} GB ({info['ram_available_gb']} GB available)",
            f"CPU:       {info['cpu_physical_cores']} physical / {info['cpu_logical_cores']} logical cores",
            f"GPU:       {gpu}",
            f"Session:   {info['session_type']}   Desktop: {info['desktop']}",
            f"Ollama:    {ollama}",
            f"Backends:  have: {' '.join(have) or '-'}",
            f"           missing: {' '.join(miss) or '-'}",
        ]
    )
