"""Keyboard, screen and windows (category: desktop). Backend depends on X11 vs Wayland."""

from __future__ import annotations

import shutil
import time
from datetime import datetime

from pydantic import BaseModel, Field

from orvix.core.interfaces import Risk, ToolResult
from orvix.tools.base import BaseTool

TYPE_CHUNK = 20  # characters per backend call; the stop flag is checked between chunks
TYPE_DELAY_MS = 12

# ydotool wants Linux input keycodes
KEYCODES = {
    "ctrl": 29, "control": 29, "shift": 42, "alt": 56, "super": 125, "meta": 125, "win": 125,
    "enter": 28, "return": 28, "esc": 1, "escape": 1, "tab": 15, "space": 57, "backspace": 14,
    "delete": 111, "up": 103, "down": 108, "left": 105, "right": 106, "home": 102, "end": 107,
    "pageup": 104, "pagedown": 109,
    **{c: k for c, k in zip("1234567890", range(2, 12), strict=True)},
    **{c: k for c, k in zip("qwertyuiop", range(16, 26), strict=True)},
    **{c: k for c, k in zip("asdfghjkl", range(30, 39), strict=True)},
    **{c: k for c, k in zip("zxcvbnm", range(44, 51), strict=True)},
    **{f"f{i}": 58 + i for i in range(1, 11)},
}  # fmt: skip


def parse_combo(combo: str) -> list[str]:
    keys = [k.strip().lower() for k in combo.replace(" ", "").split("+") if k.strip()]
    return keys


def ydotool_args(keys: list[str]) -> list[str] | None:
    codes = [KEYCODES.get(k) for k in keys]
    if not keys or any(c is None for c in codes):
        return None
    return [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]


class DesktopTool(BaseTool):
    def _need(self, *names: str) -> str | None:
        for n in names:
            if shutil.which(n):
                return n
        return None


class TypeTextArgs(BaseModel):
    text: str = Field(description="Text to type into the focused window")


class TypeText(DesktopTool):
    name = "type_text"
    category = "desktop"
    description = "Type text into the focused window."
    params = TypeTextArgs
    risk = Risk.CONFIRM

    def run(self, args: TypeTextArgs) -> ToolResult:
        backend = self._need("ydotool" if self.ctx.wayland else "xdotool")
        if not backend:
            return self.fail(f"{'ydotool' if self.ctx.wayland else 'xdotool'} is not installed")
        text = args.text
        typed = 0
        for i in range(0, len(text), TYPE_CHUNK):
            if self.ctx.stop.is_set():
                return self.fail(f"Stopped after {typed} of {len(text)} characters")
            chunk = text[i : i + TYPE_CHUNK]
            if backend == "xdotool":
                argv = ["xdotool", "type", "--delay", str(TYPE_DELAY_MS), "--", chunk]
            else:
                argv = ["ydotool", "type", "--key-delay", str(TYPE_DELAY_MS), "--", chunk]
            p = self.ctx.runner.run(argv, timeout=self.ctx.cfg.loop.tool_timeout_s)
            if p.returncode != 0:
                return self.fail((p.stderr or "typing failed").strip())
            typed += len(chunk)
        return self.ok(f"Typed {typed} characters")


class PressKeysArgs(BaseModel):
    combo: str = Field(description="Key combo such as ctrl+s, alt+tab, enter")


class PressKeys(DesktopTool):
    name = "press_keys"
    category = "desktop"
    description = "Press a keyboard shortcut like ctrl+s."
    params = PressKeysArgs
    risk = Risk.CONFIRM

    def run(self, args: PressKeysArgs) -> ToolResult:
        keys = parse_combo(args.combo)
        if not keys:
            return self.fail("No keys given")
        if self.ctx.wayland:
            if not self._need("ydotool"):
                return self.fail("ydotool is not installed")
            codes = ydotool_args(keys)
            if codes is None:
                return self.fail(f"Unknown key in '{args.combo}'")
            argv = ["ydotool", "key", *codes]
        else:
            if not self._need("xdotool"):
                return self.fail("xdotool is not installed")
            argv = ["xdotool", "key", "+".join(keys)]
        p = self.ctx.runner.run(argv, timeout=5)
        return (
            self.ok(f"Pressed {args.combo}") if p.returncode == 0 else self.fail(p.stderr.strip())
        )


class NoArgs(BaseModel):
    pass


class Screenshot(DesktopTool):
    name = "screenshot"
    category = "desktop"
    description = "Take a screenshot and return the saved path."
    params = NoArgs

    def run(self, args: NoArgs) -> ToolResult:
        out_dir = self.ctx.home / "Pictures" / "Screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"orvix-{datetime.now():%Y%m%d-%H%M%S}.png"
        if self.ctx.wayland:
            argv = ["grim", str(path)] if self._need("grim") else None
        else:
            argv = ["scrot", str(path)] if self._need("scrot") else None
        if argv is None:
            return self.fail("No screenshot tool installed (grim on Wayland, scrot on X11)")
        p = self.ctx.runner.run(argv, timeout=10)
        if p.returncode != 0:
            return self.fail((p.stderr or "screenshot failed").strip())
        return self.ok(str(path))


class ClipboardGet(DesktopTool):
    name = "clipboard_get"
    category = "desktop"
    description = "Read the clipboard text."
    params = NoArgs

    def run(self, args: NoArgs) -> ToolResult:
        if self.ctx.wayland:
            argv = ["wl-paste", "--no-newline"] if self._need("wl-paste") else None
        else:
            argv = ["xclip", "-selection", "clipboard", "-o"] if self._need("xclip") else None
        if argv is None:
            return self.fail("No clipboard tool installed (wl-clipboard or xclip)")
        p = self.ctx.runner.run(argv, timeout=5)
        return (
            self.ok(p.stdout)
            if p.returncode == 0
            else self.fail(p.stderr.strip() or "clipboard empty")
        )


class ClipboardSetArgs(BaseModel):
    text: str = Field(description="Text to put on the clipboard")


class ClipboardSet(DesktopTool):
    name = "clipboard_set"
    category = "desktop"
    description = "Copy text to the clipboard."
    params = ClipboardSetArgs

    def run(self, args: ClipboardSetArgs) -> ToolResult:
        import subprocess

        if self.ctx.wayland:
            argv = ["wl-copy"] if self._need("wl-copy") else None
        else:
            argv = ["xclip", "-selection", "clipboard"] if self._need("xclip") else None
        if argv is None:
            return self.fail("No clipboard tool installed (wl-clipboard or xclip)")
        try:
            # feed stdin; xclip/wl-copy stay alive to serve the selection, so don't wait for exit
            proc = subprocess.Popen(  # noqa: S603
                argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )  # fmt: skip
            assert proc.stdin is not None
            proc.stdin.write(args.text.encode())
            proc.stdin.close()
            time.sleep(0.05)
        except OSError as e:
            return self.fail(str(e))
        return self.ok(f"Copied {len(args.text)} characters")


class WindowArgs(BaseModel):
    name: str = Field(description="Window title or app name")


class FocusWindow(DesktopTool):
    name = "focus_window"
    category = "apps"
    description = "Bring a window to the front."
    params = WindowArgs

    def run(self, args: WindowArgs) -> ToolResult:
        if self.ctx.wayland:
            return self.fail("Window control is not supported on this Wayland session yet")
        if not self._need("wmctrl"):
            return self.fail("wmctrl is not installed")
        p = self.ctx.runner.run(["wmctrl", "-a", args.name], timeout=5)
        return (
            self.ok(f"Focused {args.name}")
            if p.returncode == 0
            else self.fail(f"No window matching '{args.name}'")
        )


class CloseApp(DesktopTool):
    name = "close_app"
    category = "apps"
    description = "Close an application's windows."
    params = WindowArgs
    risk = Risk.CONFIRM

    def run(self, args: WindowArgs) -> ToolResult:
        if self.ctx.wayland:
            return self.fail("Window control is not supported on this Wayland session yet")
        if not self._need("wmctrl"):
            return self.fail("wmctrl is not installed")
        p = self.ctx.runner.run(["wmctrl", "-c", args.name], timeout=5)
        return (
            self.ok(f"Closed {args.name}")
            if p.returncode == 0
            else self.fail(f"No window matching '{args.name}'")
        )


TOOLS = (TypeText, PressKeys, Screenshot, ClipboardGet, ClipboardSet, FocusWindow, CloseApp)
