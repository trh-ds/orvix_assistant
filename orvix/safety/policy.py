"""Shell risk policy and secret-path rules (docs/TOOLS.md, "Shell policy")."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from orvix.core.interfaces import Risk, max_risk

BLOCKED_CMDS = {
    "sudo", "su", "doas", "dd", "shutdown", "reboot", "poweroff", "halt", "init", "telinit",
}  # fmt: skip
BLOCKED_PREFIXES = ("mkfs",)
BLOCKED_DIRS = ("/etc", "/boot", "/usr", "/dev")

CONFIRM_CMDS = {
    "rm", "rmdir", "mv", "cp", "chmod", "chown", "chgrp", "kill", "pkill", "killall",
    "apt", "apt-get", "dpkg", "snap", "flatpak", "pacman", "dnf", "yum", "zypper",
    "ln", "truncate", "shred", "tee", "xargs", "crontab", "systemctl", "mount", "umount",
}  # fmt: skip
SAFE_CMDS = {
    "ls", "cat", "head", "tail", "pwd", "whoami", "date", "df", "du", "free", "uptime", "ps",
    "which", "grep", "find", "fd", "wc",
}  # fmt: skip
SAFE_GIT = {"status", "log", "diff", "branch"}
SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh"}
WRAPPERS = {"env", "nohup", "time", "command", "nice", "ionice", "timeout", "stdbuf"}
WRITE_CMDS = {"cp", "mv", "tee", "ln", "touch", "mkdir", "install", "rsync", "truncate"}
FIND_DANGER = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf"}
CONTROL = {"&&", "||", ";", "|", "&", "|&", ";;"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}

FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{")
PIPE_TO_SHELL = re.compile(
    r"\b(curl|wget|fetch)\b[^|;&]*\|\s*(sudo\s+)?(sh|bash|zsh|dash|python\d*|perl|ruby)\b"
)
SUBST = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


@dataclass(frozen=True)
class Verdict:
    risk: Risk
    reason: str = ""


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip("/") + "/")


def _norm(token: str, home: Path, cwd: Path | None = None) -> str:
    p = token
    if p == "~" or p.startswith("~/"):
        p = str(home) + p[1:]
    if not os.path.isabs(p):
        p = os.path.join(str(cwd or home), p)
    return os.path.normpath(p)


def is_secret_path(path: str | Path, blocked: list[Path] | None = None) -> bool:
    """Secrets the assistant must never read: ssh/gpg keys, browser profiles, .env, pass store."""
    p = Path(os.path.expanduser(str(path)))
    try:
        p = p.resolve()
    except OSError:
        pass
    s = str(p)
    for b in blocked or []:
        if _under(s, str(b)):
            return True
    parts = p.parts
    name = p.name
    if name == ".env" or name.startswith(".env."):
        return True
    if name in {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}:
        return True
    return any(x in {".ssh", ".gnupg", ".password-store"} for x in parts)


def _looks_like_path(tok: str) -> bool:
    return tok.startswith(("/", "~", "./", "../")) or tok == ".."


def classify_shell(
    cmd: str,
    home: Path | str = "~",
    blocked_paths: list[Path] | None = None,
    cwd: Path | None = None,
) -> Verdict:
    """Classify a shell command line. Chained commands take the highest risk."""
    home = Path(home).expanduser()
    raw = cmd.strip()
    if not raw:
        return Verdict(Risk.CONFIRM, "empty command")
    if FORK_BOMB.search(raw):
        return Verdict(Risk.BLOCKED, "fork bomb")
    if PIPE_TO_SHELL.search(raw):
        return Verdict(Risk.BLOCKED, "pipes a download into a shell")

    risk, reason = Risk.SAFE, ""

    def bump(r: Risk, why: str) -> None:
        nonlocal risk, reason
        if max_risk(risk, r) is not risk:
            risk, reason = r, why

    for m in SUBST.finditer(raw):
        inner = m.group(1) or m.group(2) or ""
        v = classify_shell(inner, home, blocked_paths, cwd)
        bump(max_risk(v.risk, Risk.CONFIRM), f"command substitution: {v.reason or inner}")

    try:
        lex = shlex.shlex(raw, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError as e:
        return Verdict(Risk.CONFIRM, f"unparseable command ({e})")

    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok in CONTROL:
            segments.append([])
        else:
            segments[-1].append(tok)

    for seg in segments:
        v = _classify_segment(seg, home, blocked_paths or [], cwd)
        bump(v.risk, v.reason)
        if risk is Risk.BLOCKED:
            break
    return Verdict(risk, reason)


def _classify_segment(seg: list[str], home: Path, blocked: list[Path], cwd: Path | None) -> Verdict:
    if not seg:
        return Verdict(Risk.SAFE)

    risk, reason = Risk.SAFE, ""

    def bump(r: Risk, why: str) -> None:
        nonlocal risk, reason
        if max_risk(risk, r) is not risk:
            risk, reason = r, why

    # redirects: find targets, strip them from the argv
    argv: list[str] = []
    i = 0
    while i < len(seg):
        tok = seg[i]
        base = tok.lstrip("0123456789")
        if base in REDIRECTS or tok in REDIRECTS:
            target = seg[i + 1] if i + 1 < len(seg) else ""
            if target:
                t = _norm(target, home, cwd)
                if t != "/dev/null" and any(_under(t, d) for d in BLOCKED_DIRS):
                    return Verdict(Risk.BLOCKED, f"writes to {t}")
                if target != "/dev/null":
                    bump(Risk.CONFIRM, "redirect writes a file")
                if is_secret_path(t, blocked):
                    return Verdict(Risk.BLOCKED, "touches a secret path")
            i += 2
            continue
        if base in {"<", "<<", "<<<"}:
            i += 2
            continue
        argv.append(tok)
        i += 1

    # drop env assignments and transparent wrappers
    while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
        argv.pop(0)
    while argv and os.path.basename(argv[0]) in WRAPPERS:
        bump(Risk.CONFIRM, f"wrapper {argv[0]}")
        argv.pop(0)
        while argv and (argv[0].startswith("-") or re.match(r"^\d+[smhd]?$", argv[0])):
            argv.pop(0)
    if not argv:
        return Verdict(risk, reason)

    name = os.path.basename(argv[0])
    args = argv[1:]

    if name in BLOCKED_CMDS or name.startswith(BLOCKED_PREFIXES):
        return Verdict(Risk.BLOCKED, f"{name} is not allowed")
    if name in {"systemctl", "loginctl"} and any(
        a in {"poweroff", "reboot", "halt", "kexec"} for a in args
    ):
        return Verdict(Risk.BLOCKED, "power control via shell")

    if name in SHELLS:
        if "-c" in args and args.index("-c") + 1 < len(args):
            inner = classify_shell(args[args.index("-c") + 1], home, blocked, cwd)
            bump(max_risk(inner.risk, Risk.CONFIRM), f"nested shell: {inner.reason}")
        else:
            bump(Risk.CONFIRM, "runs a shell")
        if risk is Risk.BLOCKED:
            return Verdict(risk, reason)

    # path checks
    path_args = [a for a in args if _looks_like_path(a)]
    if name in {"cd"}:
        path_args = args[:1]
    for a in args:
        if a.startswith("-") and "=" in a and _looks_like_path(a.split("=", 1)[1]):
            path_args.append(a.split("=", 1)[1])
    for a in path_args:
        p = _norm(a, home, cwd)
        if is_secret_path(p, blocked):
            return Verdict(Risk.BLOCKED, "touches a secret path")
        if name in WRITE_CMDS | {"rm", "rmdir", "chmod", "chown", "chgrp", "shred"} and any(
            _under(p, d) for d in BLOCKED_DIRS
        ):
            return Verdict(Risk.BLOCKED, f"modifies {p}")
        if not _under(p, str(home)) and not _under(p, "/dev/null"):
            bump(Risk.CONFIRM, f"path outside home: {p}")
    # a bare filename can still be a secret (e.g. `cat .env`)
    for a in args:
        if not a.startswith("-") and is_secret_path(_norm(a, home, cwd), blocked):
            return Verdict(Risk.BLOCKED, "touches a secret path")

    if name in CONFIRM_CMDS:
        bump(Risk.CONFIRM, f"{name} can change or remove things")
    elif name == "git":
        sub = next((a for a in args if not a.startswith("-")), "")
        if sub in SAFE_GIT and not (
            sub == "branch" and any(a in {"-d", "-D", "-m", "-M", "--delete"} for a in args)
        ):
            pass
        else:
            bump(Risk.CONFIRM, f"git {sub or '?'} is not read-only")
    elif name in {"pip", "pip3", "npm", "pnpm", "yarn", "uv", "cargo", "gem"}:
        bump(Risk.CONFIRM, f"{name} installs or changes packages")
    elif name in SAFE_CMDS:
        if name == "find" and any(a in FIND_DANGER for a in args):
            bump(Risk.CONFIRM, "find with an action")
    else:
        bump(Risk.CONFIRM, f"{name} is not on the allowlist")

    return Verdict(risk, reason)
