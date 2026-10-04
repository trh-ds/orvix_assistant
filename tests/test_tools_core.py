from orvix.tools import apps, desktop_entries, files, info
from orvix.tools.registry import build_registry


def test_registry_has_core_tools(ctx):
    reg = build_registry(ctx)
    for n in [
        "open_app",
        "open_in_vscode",
        "open_url",
        "find_path",
        "list_dir",
        "read_file",
        "now",
        "system_info",
    ]:
        assert reg.get(n), n
    spec = reg.get("open_url").spec()
    assert spec.parameters["properties"]["url"]["type"] == "string"
    assert "title" not in spec.parameters


def test_every_tool_has_risk_and_category(ctx):
    for t in build_registry(ctx).all():
        assert t.risk is not None and t.category and t.description


def test_desktop_match():
    from pathlib import Path

    es = [
        desktop_entries.Entry("org.mozilla.firefox", "Firefox Web Browser", "firefox", Path("x")),
        desktop_entries.Entry("code", "Visual Studio Code", "code", Path("y")),
        desktop_entries.Entry("org.gnome.Terminal", "Terminal", "gnome-terminal", Path("z")),
    ]
    assert desktop_entries.match("firefox", es).stem == "org.mozilla.firefox"
    assert desktop_entries.match("visual studio code", es).stem == "code"
    assert desktop_entries.match("terminal", es).stem == "org.gnome.Terminal"
    assert desktop_entries.match("zzzz", es) is None


def test_open_url_launches_xdg_open(ctx, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    r = apps.OpenURL(ctx).run(apps.OpenURLArgs(url="example.com"))
    assert r.ok and ctx.runner.launched == [["xdg-open", "https://example.com"]]
    assert not apps.OpenURL(ctx).run(apps.OpenURLArgs(url="file:///etc/passwd")).ok


def test_open_in_vscode(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}" if n == "code" else None)
    (tmp_path / "orvix").mkdir()
    r = apps.OpenInVSCode(ctx).run(apps.OpenInVSCodeArgs(path="~/orvix"))
    assert r.ok and ctx.runner.launched == [["/usr/bin/code", str(tmp_path / "orvix")]]
    assert not apps.OpenInVSCode(ctx).run(apps.OpenInVSCodeArgs(path="~/missing")).ok


def test_find_path_alias_and_walk(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    (tmp_path / "projects" / "orvix_assistant").mkdir(parents=True)
    ctx.store.remember("college folder", "~/clg")
    t = files.FindPath(ctx)
    assert t.run(files.FindPathArgs(query="my college folder")).output == str(tmp_path / "clg")
    assert t.run(files.FindPathArgs(query="downloads")).output == str(tmp_path / "Downloads")
    r = t.run(files.FindPathArgs(query="orvix"))
    assert r.ok and str(tmp_path / "projects" / "orvix_assistant") in r.output
    assert not t.run(files.FindPathArgs(query="nonexistentthing")).ok


def test_list_and_read_respect_secrets(ctx, tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("KEY")
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / ".env").write_text("TOKEN=1")
    assert not files.ReadFile(ctx).run(files.ReadFileArgs(path="~/.ssh/id_rsa")).ok
    assert not files.ReadFile(ctx).run(files.ReadFileArgs(path="~/.env")).ok
    assert not files.ListDir(ctx).run(files.ListDirArgs(path="~/.ssh")).ok
    out = files.ListDir(ctx).run(files.ListDirArgs(path="~")).output
    assert "a.txt" in out and ".env" not in out and ".ssh" not in out
    assert files.ReadFile(ctx).run(files.ReadFileArgs(path="~/a.txt")).output == "hello"


def test_read_file_caps_and_rejects_binary(ctx, tmp_path):
    (tmp_path / "big.txt").write_text("x" * 10000)
    r = files.ReadFile(ctx).run(files.ReadFileArgs(path="~/big.txt"))
    assert len(r.output) < 2100 and "truncated" in r.output
    (tmp_path / "b.bin").write_bytes(b"\x00\x01")
    assert not files.ReadFile(ctx).run(files.ReadFileArgs(path="~/b.bin")).ok


def test_info_tools(ctx):
    assert info.Now(ctx).run(info.NoArgs()).ok
    assert info.SystemInfo(ctx).run(info.SystemInfoArgs(kind="ram")).output.startswith("RAM")
    assert info.SystemInfo(ctx).run(info.SystemInfoArgs(kind="processes")).ok


def test_every_tool_module_is_registered(ctx):
    import importlib
    import pkgutil

    import orvix.tools as pkg

    registered = {type(t) for t in build_registry(ctx).all()}
    for m in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"orvix.tools.{m.name}")
        for cls in getattr(mod, "TOOLS", ()):
            assert cls in registered, f"{cls.__name__} in {m.name}.TOOLS is not registered"
