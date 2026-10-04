import pytest

from orvix.core.interfaces import Risk
from orvix.tools import memory, system
from orvix.tools.base import Proc
from orvix.tools.registry import build_registry


def have(*names):
    return lambda n: f"/usr/bin/{n}" if n in names else None


def test_memory_roundtrip(ctx):
    assert memory.Remember(ctx).run(memory.RememberArgs(key="College Folder", value="~/clg")).ok
    assert (
        memory.Recall(ctx).run(memory.RecallArgs(query="college folder")).output.endswith("~/clg")
    )
    assert "~/clg" in memory.Recall(ctx).run(memory.RecallArgs(query="where is my college")).output
    assert not memory.Recall(ctx).run(memory.RecallArgs(query="zzz unknown")).ok
    assert memory.Forget.risk is Risk.CONFIRM
    assert memory.Forget(ctx).run(memory.ForgetArgs(key="college folder")).ok
    assert not memory.Forget(ctx).run(memory.ForgetArgs(key="college folder")).ok
    assert not memory.Remember(ctx).run(memory.RememberArgs(key=" ", value="x")).ok


@pytest.mark.parametrize(
    "action,value,expected",
    [
        ("up", None, ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"]),
        ("down", None, ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"]),
        ("mute", None, ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"]),
        ("set", 30, ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "30%"]),
    ],
)
def test_volume_wpctl(ctx, monkeypatch, action, value, expected):
    monkeypatch.setattr("shutil.which", have("wpctl"))
    assert system.Volume(ctx).run(system.VolumeArgs(action=action, value=value)).ok
    assert ctx.runner.ran[-1] == expected


def test_volume_pactl_fallback_and_missing(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", have("pactl"))
    system.Volume(ctx).run(system.VolumeArgs(action="up"))
    assert ctx.runner.ran[-1] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"]
    monkeypatch.setattr("shutil.which", have())
    assert not system.Volume(ctx).run(system.VolumeArgs(action="up")).ok
    assert not system.Volume(ctx).run(system.VolumeArgs(action="set")).ok


def test_backend_error_is_reported(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", have("playerctl"))
    ctx.runner.next = Proc(1, "", "No players found")
    r = system.Media(ctx).run(system.MediaArgs(action="pause"))
    assert not r.ok and "No players" in r.error


def test_brightness_media_wifi_notify_lock(ctx, monkeypatch):
    monkeypatch.setattr(
        "shutil.which",
        have(
            "brightnessctl",
            "playerctl",
            "nmcli",
            "bluetoothctl",
            "notify-send",
            "loginctl",
            "systemctl",
        ),
    )
    system.Brightness(ctx).run(system.BrightnessArgs(action="up"))
    assert ctx.runner.ran[-1] == ["brightnessctl", "set", "10%+"]
    system.Brightness(ctx).run(system.BrightnessArgs(action="set", value=40))
    assert ctx.runner.ran[-1] == ["brightnessctl", "set", "40%"]
    system.Media(ctx).run(system.MediaArgs(action="next"))
    assert ctx.runner.ran[-1] == ["playerctl", "next"]
    system.Wifi(ctx).run(system.RadioArgs(state="off"))
    assert ctx.runner.ran[-1] == ["nmcli", "radio", "wifi", "off"]
    system.Bluetooth(ctx).run(system.RadioArgs(state="on"))
    assert ctx.runner.ran[-1] == ["bluetoothctl", "power", "on"]
    system.Notify(ctx).run(system.NotifyArgs(text="hi"))
    assert ctx.runner.ran[-1] == ["notify-send", "Orvix", "hi"]
    system.LockScreen(ctx).run(system.NoArgs())
    assert ctx.runner.ran[-1] == ["loginctl", "lock-session"]


def test_suspend_needs_confirmation_and_launches(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", have("systemctl"))
    assert system.Suspend.risk is Risk.CONFIRM
    assert system.Suspend(ctx).run(system.NoArgs()).ok
    assert ctx.runner.launched == [["systemctl", "suspend"]]


def test_registry_complete(ctx):
    names = set(build_registry(ctx).names())
    assert {"volume", "brightness", "media", "wifi", "bluetooth", "lock_screen", "suspend", "notify",
            "remember", "recall", "forget"} <= names  # fmt: skip
