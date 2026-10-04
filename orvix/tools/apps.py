"""Apps and windows (category: apps)."""

from __future__ import annotations

import shutil

from pydantic import BaseModel, Field

from orvix.core.interfaces import ToolResult
from orvix.tools import desktop_entries
from orvix.tools.base import BaseTool


class OpenAppArgs(BaseModel):
    name: str = Field(description="App name, e.g. firefox, terminal, spotify")


class OpenApp(BaseTool):
    name = "open_app"
    category = "apps"
    description = "Launch an application by name."
    params = OpenAppArgs

    def run(self, args: OpenAppArgs) -> ToolResult:
        entries = desktop_entries.load_entries(self.ctx.home)
        entry = desktop_entries.match(args.name, entries)
        if entry and shutil.which("gtk-launch"):
            self.ctx.runner.launch(["gtk-launch", entry.stem])
            return self.ok(f"Launched {entry.name}")
        if entry and shutil.which("gio"):
            self.ctx.runner.launch(["gio", "launch", str(entry.path)])
            return self.ok(f"Launched {entry.name}")
        exe = shutil.which(args.name.strip().lower().replace(" ", "-"))
        if exe:
            self.ctx.runner.launch([exe])
            return self.ok(f"Launched {exe}")
        return self.fail(f"No app found matching '{args.name}'")


class OpenInVSCodeArgs(BaseModel):
    path: str = Field(description="File or folder path, or a spoken alias")


class OpenInVSCode(BaseTool):
    name = "open_in_vscode"
    category = "apps"
    description = "Open a file or folder in VS Code."
    params = OpenInVSCodeArgs

    def run(self, args: OpenInVSCodeArgs) -> ToolResult:
        p = self.ctx.resolve(args.path)
        if self.ctx.is_secret(p):
            return self.fail("That path is protected")
        if not p.exists():
            return self.fail(f"Path does not exist: {p}")
        exe = shutil.which("code") or shutil.which("codium")
        if not exe:
            return self.fail("VS Code ('code') is not installed")
        self.ctx.runner.launch([exe, str(p)])
        return self.ok(f"Opened {p} in VS Code")


class OpenURLArgs(BaseModel):
    url: str = Field(description="Full URL, e.g. https://example.com")


class OpenURL(BaseTool):
    name = "open_url"
    category = "apps"
    description = "Open a URL in the default browser."
    params = OpenURLArgs

    def run(self, args: OpenURLArgs) -> ToolResult:
        url = args.url.strip()
        if "://" not in url:
            url = "https://" + url
        if not url.startswith(("http://", "https://")):
            return self.fail("Only http(s) URLs can be opened")
        if not shutil.which("xdg-open"):
            return self.fail("xdg-open is not installed")
        self.ctx.runner.launch(["xdg-open", url])
        return self.ok(f"Opened {url}")


TOOLS = (OpenApp, OpenInVSCode, OpenURL)
