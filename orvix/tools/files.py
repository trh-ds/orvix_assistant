"""Files (category: files)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from orvix.core.interfaces import Risk, ToolResult
from orvix.tools.base import BaseTool, ToolContext

KNOWN_DIRS = {
    "home": "",
    "downloads": "Downloads",
    "documents": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
}
FILLER = {"my", "the", "a", "folder", "directory", "dir", "file", "called", "named"}
SKIP_DIRS = {"node_modules", ".git", ".venv", "__pycache__", ".cache", ".npm", ".cargo", "venv"}


def _clean_query(q: str) -> str:
    return " ".join(w for w in q.lower().split() if w not in FILLER)


def resolve_alias(ctx: ToolContext, query: str) -> Path | None:
    """Alias table first (facts), then well-known folders. No LLM involved."""
    cleaned = _clean_query(query)
    variants = [query.strip().lower(), cleaned, f"{cleaned} folder", f"{cleaned} directory"]
    for v in variants:
        if not v:
            continue
        val = ctx.store.get_fact(v)
        if val and (val.startswith(("~", "/")) or Path(val).exists()):
            return ctx.resolve(val)
    if cleaned in KNOWN_DIRS:
        return ctx.home / KNOWN_DIRS[cleaned]
    return None


def _walk_search(
    root: Path, query: str, limit: int, ctx: ToolContext, max_depth: int = 6
) -> list[Path]:
    q = query.lower()
    hits: list[tuple[int, Path]] = []
    base_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - base_depth
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".") and depth < max_depth
        ]
        for n in (*dirnames, *filenames):
            if q in n.lower():
                p = Path(dirpath) / n
                if not ctx.is_secret(p):
                    hits.append((depth, p))
        if len(hits) > 200:
            break
    hits.sort(key=lambda h: (h[0], len(str(h[1]))))
    return [p for _, p in hits[:limit]]


class FindPathArgs(BaseModel):
    query: str = Field(description="Spoken name or alias of a file or folder")


class FindPath(BaseTool):
    name = "find_path"
    category = "files"
    description = "Resolve a spoken file or folder name to a real path."
    params = FindPathArgs

    def run(self, args: FindPathArgs) -> ToolResult:
        alias = resolve_alias(self.ctx, args.query)
        if alias is not None:
            return self.ok(str(alias))
        query = _clean_query(args.query) or args.query.strip()
        paths: list[Path] = []
        fd = shutil.which("fd") or shutil.which("fdfind")
        if fd:
            r = self.ctx.runner.run(
                [fd, "--max-results", "30", "--max-depth", "6", "-i", query, str(self.ctx.home)],
                timeout=10,
            )
            paths = [Path(line) for line in r.stdout.splitlines() if line.strip()]
            paths = [p for p in paths if not self.ctx.is_secret(p)][:5]
        if not paths:
            paths = _walk_search(self.ctx.home, query, 5, self.ctx)
        if not paths:
            return self.fail(f"Nothing found for '{args.query}'")
        return self.ok("\n".join(str(p) for p in paths))


class ListDirArgs(BaseModel):
    path: str = Field(description="Folder path")


class ListDir(BaseTool):
    name = "list_dir"
    category = "files"
    description = "List the contents of a folder."
    params = ListDirArgs

    def run(self, args: ListDirArgs) -> ToolResult:
        p = self.ctx.resolve(args.path)
        if self.ctx.is_secret(p):
            return self.fail("That path is protected")
        if not p.is_dir():
            return self.fail(f"Not a folder: {p}")
        try:
            entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError as e:
            return self.fail(str(e))
        lines = [
            f"{e.name}/" if e.is_dir() else e.name for e in entries if not self.ctx.is_secret(e)
        ]
        return self.ok("\n".join(lines) or "(empty)")


class ReadFileArgs(BaseModel):
    path: str = Field(description="Text file path")


class ReadFile(BaseTool):
    name = "read_file"
    category = "files"
    description = "Read a text file (first 2000 characters)."
    params = ReadFileArgs

    def run(self, args: ReadFileArgs) -> ToolResult:
        p = self.ctx.resolve(args.path)
        if self.ctx.is_secret(p):
            return self.fail("That path is protected")
        if not p.is_file():
            return self.fail(f"Not a file: {p}")
        try:
            with p.open("rb") as f:
                raw = f.read(self.ctx.cfg.loop.tool_output_cap * 4)
        except OSError as e:
            return self.fail(str(e))
        if b"\x00" in raw:
            return self.fail("Binary file, cannot read as text")
        text = raw.decode("utf-8", errors="replace")
        return self.ok(text)


class WriteFileArgs(BaseModel):
    path: str = Field(description="File path to create or overwrite")
    content: str = Field(description="Full file content")


class WriteFile(BaseTool):
    name = "write_file"
    category = "files"
    description = "Create or overwrite a text file."
    params = WriteFileArgs
    risk = Risk.CONFIRM
    last_reason = ""

    def assess(self, args: WriteFileArgs) -> Risk:
        p = self.ctx.resolve(args.path)
        if self.ctx.is_secret(p):
            self.last_reason = "protected path"
            return Risk.BLOCKED
        self.last_reason = "overwrites an existing file" if p.exists() else "creates a file"
        return Risk.CONFIRM

    def run(self, args: WriteFileArgs) -> ToolResult:
        p = self.ctx.resolve(args.path)
        if self.ctx.is_secret(p):
            return self.fail("That path is protected")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.content)
        except OSError as e:
            return self.fail(str(e))
        return self.ok(f"Wrote {len(args.content)} characters to {p}")


class OpenFileArgs(BaseModel):
    path: str = Field(description="File path to open with its default app")


class OpenFile(BaseTool):
    name = "open_file"
    category = "files"
    description = "Open a file with its default application."
    params = OpenFileArgs

    def run(self, args: OpenFileArgs) -> ToolResult:
        p = self.ctx.resolve(args.path)
        if self.ctx.is_secret(p):
            return self.fail("That path is protected")
        if not p.exists():
            return self.fail(f"Path does not exist: {p}")
        if not shutil.which("xdg-open"):
            return self.fail("xdg-open is not installed")
        self.ctx.runner.launch(["xdg-open", str(p)])
        return self.ok(f"Opened {p}")


TOOLS = (FindPath, ListDir, ReadFile, WriteFile, OpenFile)
