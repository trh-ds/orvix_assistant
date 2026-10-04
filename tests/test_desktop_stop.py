import asyncio
import threading

from orvix.core.stop import StopController
from orvix.tools import desktop
from orvix.tools.base import Proc


def have(*names):
    return lambda n: f"/usr/bin/{n}" if n in names else None


def test_type_text_x11_chunks(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", have("xdotool"))
    ctx.session_type = "x11"
    r = desktop.TypeText(ctx).run(desktop.TypeTextArgs(text="a" * 45))
    assert r.ok and len(ctx.runner.ran) == 3
    assert ctx.runner.ran[0][:2] == ["xdotool", "type"]


def test_type_text_wayland_uses_ydotool(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", have("ydotool"))
    ctx.session_type = "wayland"
    assert desktop.TypeText(ctx).run(desktop.TypeTextArgs(text="hi")).ok
    assert ctx.runner.ran[0][0] == "ydotool"
    monkeypatch.setattr("shutil.which", have())
    assert not desktop.TypeText(ctx).run(desktop.TypeTextArgs(text="hi")).ok


def test_stop_interrupts_type_text_mid_string(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", have("xdotool"))
    ctx.session_type = "x11"
    orig = ctx.runner.run

    def run_and_stop(argv, **kw):
        res = orig(argv, **kw)
        if len(ctx.runner.ran) == 2:
            ctx.stop.set()  # hotkey pressed while typing
        return res

    ctx.runner.run = run_and_stop
    r = desktop.TypeText(ctx).run(desktop.TypeTextArgs(text="b" * 100))
    assert not r.ok and "Stopped after 40 of 100" in r.error
    assert len(ctx.runner.ran) == 2


def test_press_keys_both_backends(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", have("xdotool", "ydotool"))
    ctx.session_type = "x11"
    desktop.PressKeys(ctx).run(desktop.PressKeysArgs(combo="Ctrl + S"))
    assert ctx.runner.ran[-1] == ["xdotool", "key", "ctrl+s"]
    ctx.session_type = "wayland"
    desktop.PressKeys(ctx).run(desktop.PressKeysArgs(combo="ctrl+s"))
    assert ctx.runner.ran[-1] == ["ydotool", "key", "29:1", "31:1", "31:0", "29:0"]
    assert not desktop.PressKeys(ctx).run(desktop.PressKeysArgs(combo="ctrl+banana")).ok


def test_screenshot_and_clipboard_get(ctx, monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", have("scrot", "xclip"))
    ctx.session_type = "x11"
    r = desktop.Screenshot(ctx).run(desktop.NoArgs())
    assert r.ok and r.output.startswith(str(tmp_path / "Pictures" / "Screenshots"))
    assert ctx.runner.ran[-1][0] == "scrot"
    ctx.runner.next = Proc(0, "copied text", "")
    assert desktop.ClipboardGet(ctx).run(desktop.NoArgs()).output == "copied text"
    monkeypatch.setattr("shutil.which", have())
    assert not desktop.Screenshot(ctx).run(desktop.NoArgs()).ok


def test_window_tools(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", have("wmctrl"))
    ctx.session_type = "x11"
    assert desktop.FocusWindow(ctx).run(desktop.WindowArgs(name="firefox")).ok
    assert ctx.runner.ran[-1] == ["wmctrl", "-a", "firefox"]
    ctx.runner.next = Proc(1, "", "")
    assert not desktop.CloseApp(ctx).run(desktop.WindowArgs(name="nothing")).ok
    ctx.session_type = "wayland"
    assert "Wayland" in desktop.FocusWindow(ctx).run(desktop.WindowArgs(name="x")).error


async def test_stop_controller_cancels_task_kills_and_runs_hooks():
    ev, killed, hooked = threading.Event(), [], []
    sc = StopController(ev, lambda: killed.append(1))
    sc.on_stop(lambda: hooked.append(1))
    sc.bind(asyncio.get_running_loop())
    task = asyncio.create_task(asyncio.sleep(5))
    sc.track(task)
    await asyncio.to_thread(sc.trigger)  # as the hotkey thread would
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.cancelled() and ev.is_set() and killed == [1] and hooked == [1]
    sc.reset()
    assert not ev.is_set()
