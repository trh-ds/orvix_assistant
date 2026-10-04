"""System controls (category: system). Fast-path candidates; backends are detected at call time."""

from __future__ import annotations

import shutil
from typing import Literal

from pydantic import BaseModel, Field

from orvix.core.interfaces import Risk, ToolResult
from orvix.tools.base import BaseTool

STEP = 5


class SystemTool(BaseTool):
    def _cmd(self, argv: list[str], timeout: float = 5) -> ToolResult:
        p = self.ctx.runner.run(argv, timeout=timeout)
        if p.returncode != 0:
            return self.fail((p.stderr or p.stdout).strip() or f"{argv[0]} exited {p.returncode}")
        return self.ok(p.stdout.strip())


class VolumeArgs(BaseModel):
    action: Literal["up", "down", "mute", "unmute", "set"]
    value: int | None = Field(default=None, ge=0, le=100, description="Percent, for action=set")


class Volume(SystemTool):
    name = "volume"
    category = "system"
    description = "Change volume: up, down, mute, unmute, or set to a percent."
    params = VolumeArgs

    def run(self, args: VolumeArgs) -> ToolResult:
        a = args.action
        if a == "set" and args.value is None:
            return self.fail("Say what percent to set the volume to")
        if shutil.which("wpctl"):
            sink = "@DEFAULT_AUDIO_SINK@"
            argv = {
                "up": ["wpctl", "set-volume", "-l", "1.0", sink, f"{STEP}%+"],
                "down": ["wpctl", "set-volume", sink, f"{STEP}%-"],
                "mute": ["wpctl", "set-mute", sink, "1"],
                "unmute": ["wpctl", "set-mute", sink, "0"],
                "set": ["wpctl", "set-volume", sink, f"{args.value}%"],
            }[a]
        elif shutil.which("pactl"):
            sink = "@DEFAULT_SINK@"
            argv = {
                "up": ["pactl", "set-sink-volume", sink, f"+{STEP}%"],
                "down": ["pactl", "set-sink-volume", sink, f"-{STEP}%"],
                "mute": ["pactl", "set-sink-mute", sink, "1"],
                "unmute": ["pactl", "set-sink-mute", sink, "0"],
                "set": ["pactl", "set-sink-volume", sink, f"{args.value}%"],
            }[a]
        else:
            return self.fail("Neither wpctl nor pactl is installed")
        res = self._cmd(argv)
        return self.ok(f"Volume {a}" + (f" {args.value}%" if a == "set" else "")) if res.ok else res


class BrightnessArgs(BaseModel):
    action: Literal["up", "down", "set"]
    value: int | None = Field(default=None, ge=1, le=100, description="Percent, for action=set")


class Brightness(SystemTool):
    name = "brightness"
    category = "system"
    description = "Change screen brightness: up, down, or set to a percent."
    params = BrightnessArgs

    def run(self, args: BrightnessArgs) -> ToolResult:
        if not shutil.which("brightnessctl"):
            return self.fail("brightnessctl is not installed")
        if args.action == "set":
            if args.value is None:
                return self.fail("Say what percent to set the brightness to")
            spec = f"{args.value}%"
        else:
            spec = f"{STEP * 2}%{'+' if args.action == 'up' else '-'}"
        res = self._cmd(["brightnessctl", "set", spec])
        return self.ok(f"Brightness {args.action}") if res.ok else res


class MediaArgs(BaseModel):
    action: Literal["play", "pause", "play-pause", "next", "previous"]


class Media(SystemTool):
    name = "media"
    category = "system"
    description = "Control media playback: play, pause, next, previous."
    params = MediaArgs

    def run(self, args: MediaArgs) -> ToolResult:
        if not shutil.which("playerctl"):
            return self.fail("playerctl is not installed")
        res = self._cmd(["playerctl", args.action])
        return self.ok(f"Media {args.action}") if res.ok else res


class RadioArgs(BaseModel):
    state: Literal["on", "off"]


class Wifi(SystemTool):
    name = "wifi"
    category = "system"
    description = "Turn Wi-Fi on or off."
    params = RadioArgs

    def run(self, args: RadioArgs) -> ToolResult:
        if not shutil.which("nmcli"):
            return self.fail("nmcli is not installed")
        res = self._cmd(["nmcli", "radio", "wifi", args.state])
        return self.ok(f"Wi-Fi {args.state}") if res.ok else res


class Bluetooth(SystemTool):
    name = "bluetooth"
    category = "system"
    description = "Turn Bluetooth on or off."
    params = RadioArgs

    def run(self, args: RadioArgs) -> ToolResult:
        if not shutil.which("bluetoothctl"):
            return self.fail("bluetoothctl is not installed")
        res = self._cmd(["bluetoothctl", "power", args.state])
        return self.ok(f"Bluetooth {args.state}") if res.ok else res


class NoArgs(BaseModel):
    pass


class LockScreen(SystemTool):
    name = "lock_screen"
    category = "system"
    description = "Lock the screen."
    params = NoArgs

    def run(self, args: NoArgs) -> ToolResult:
        if not shutil.which("loginctl"):
            return self.fail("loginctl is not installed")
        res = self._cmd(["loginctl", "lock-session"])
        return self.ok("Locked") if res.ok else res


class Suspend(SystemTool):
    name = "suspend"
    category = "system"
    description = "Suspend the laptop."
    params = NoArgs
    risk = Risk.CONFIRM

    def run(self, args: NoArgs) -> ToolResult:
        if not shutil.which("systemctl"):
            return self.fail("systemctl is not installed")
        self.ctx.runner.launch(["systemctl", "suspend"])
        return self.ok("Suspending")


class NotifyArgs(BaseModel):
    text: str = Field(description="Notification text")


class Notify(SystemTool):
    name = "notify"
    category = "system"
    description = "Show a desktop notification."
    params = NotifyArgs

    def run(self, args: NotifyArgs) -> ToolResult:
        if not shutil.which("notify-send"):
            return self.fail("notify-send is not installed")
        res = self._cmd(["notify-send", "Orvix", args.text])
        return self.ok("Notified") if res.ok else res


TOOLS = (Volume, Brightness, Media, Wifi, Bluetooth, LockScreen, Suspend, Notify)
