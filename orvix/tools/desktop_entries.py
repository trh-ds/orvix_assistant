"""Find .desktop launchers by spoken app name."""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    stem: str  # file name without .desktop, what gtk-launch wants
    name: str
    exec: str
    path: Path


def search_dirs(home: Path) -> list[Path]:
    dirs = [home / ".local/share/applications"]
    for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if d:
            dirs.append(Path(d) / "applications")
    dirs += [
        Path("/var/lib/flatpak/exports/share/applications"),
        home / ".local/share/flatpak/exports/share/applications",
        Path("/var/lib/snapd/desktop/applications"),
    ]
    return [d for d in dirs if d.is_dir()]


def parse_desktop(path: Path) -> Entry | None:
    name = exec_ = ""
    in_entry = False
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                in_entry = line == "[Desktop Entry]"
                continue
            if not in_entry or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k == "Name" and not name:
                name = v
            elif k == "Exec" and not exec_:
                exec_ = v
            elif k in {"NoDisplay", "Hidden"} and v.lower() == "true":
                return None
            elif k == "Type" and v != "Application":
                return None
    except OSError:
        return None
    if not name or not exec_:
        return None
    return Entry(path.stem, name, exec_, path)


def load_entries(home: Path) -> list[Entry]:
    seen: dict[str, Entry] = {}
    for d in search_dirs(home):
        for f in sorted(d.glob("*.desktop")):
            if f.stem in seen:
                continue
            e = parse_desktop(f)
            if e:
                seen[f.stem] = e
    return list(seen.values())


def _norm(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum() or c == " ").strip()


def match(query: str, entries: list[Entry]) -> Entry | None:
    q = _norm(query)
    if not q:
        return None
    best: tuple[float, Entry] | None = None
    for e in entries:
        names = {_norm(e.name), _norm(e.stem), _norm(e.stem.split(".")[-1])}
        if q in names:
            score = 3.0
        elif any(n.startswith(q) for n in names):
            score = 2.0 + len(q) / 100
        elif any(q in n for n in names):
            score = 1.0 + len(q) / 100
        else:
            score = max((difflib.SequenceMatcher(None, q, n).ratio() for n in names), default=0)
            if score < 0.8:
                continue
        if best is None or score > best[0]:
            best = (score, e)
    return best[1] if best else None
