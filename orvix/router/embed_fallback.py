"""Similarity router (option 3 in docs/DESIGN.md): rank tools against the transcript.

Stage 1: deterministic fast rules. Stage 2: score every tool with a hashed bag-of-words vector over
its name, description and trigger words; offer the LLM only the top-k. `embed` can be swapped for a
real sentence embedder later without touching the loop.
"""

from __future__ import annotations

import math
import re
import zlib
from collections import Counter
from collections.abc import Callable

from orvix.core.config import RouterConfig
from orvix.core.interfaces import Decision, State
from orvix.router.decision import match_fast, normalize
from orvix.tools.registry import Registry

DIM = 1 << 16
STOP = {
    "a", "an", "the", "to", "of", "in", "on", "my", "me", "i", "it", "is", "and", "for", "please",
    "can", "you", "what", "whats", "how", "do", "does", "this", "that", "with", "at", "up", "some",
}  # fmt: skip

# Spoken words that signal a tool but are not in its description.
TRIGGERS: dict[str, str] = {
    "open_app": "open launch start run fire up app application program",
    "close_app": "close quit exit kill app window",
    "focus_window": "focus switch window front show go to",
    "open_in_vscode": "vscode vs code visual studio editor project open code",
    "open_url": "open url website site browser go to visit link http https github youtube google",
    "find_path": "find where locate search look for path file folder directory",
    "list_dir": "list show contents inside folder directory ls what's in files",
    "read_file": "read cat show contents file text says",
    "write_file": "write create make save file called says content",
    "open_file": "open file document pdf with default app",
    "run_shell": "run command shell terminal execute git status df du free uptime grep python script",
    "now": "time date day today clock",
    "system_info": "battery cpu ram memory disk space processes using busy storage",
    "web_search": "search google web internet latest news look up online find out",
    "fetch_page": "fetch page url article read website summarise summarize",
    "set_timer": "timer countdown minutes seconds hours alarm",
    "set_reminder": "remind reminder reminder me later tomorrow at",
    "remember": "remember store save note that is my alias",
    "recall": "recall what did i tell you remember lookup",
    "forget": "forget delete remove stored fact",
    "volume": "volume sound louder quieter mute unmute audio",
    "brightness": "brightness screen dimmer brighter display",
    "media": "music song play pause next previous track playback spotify video",
    "wifi": "wifi wi-fi wireless network internet",
    "bluetooth": "bluetooth devices pair",
    "lock_screen": "lock screen secure",
    "suspend": "suspend sleep standby",
    "notify": "notify notification alert popup message",
    "type_text": "type typing write keyboard text into here",
    "press_keys": "press key keys shortcut combo keyboard ctrl alt enter tab",
    "screenshot": "screenshot capture screen picture snapshot",
    "clipboard_get": "clipboard paste copied read",
    "clipboard_set": "clipboard copy put text",
}  # fmt: skip

CHAT_RE = re.compile(
    r"^(?:hi|hello|hey|thanks|thank you|good (?:morning|evening|night)|tell me a joke|who are you|"
    r"how are you|what can you do)$"
)


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'\-]*", text.lower()) if w not in STOP]


def hash_embed(text: str) -> dict[int, float]:
    """Sparse L2-normalised hashed bag-of-words (unigrams + bigrams)."""
    toks = tokens(text)
    feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
    counts = Counter(zlib.crc32(f.encode()) % DIM for f in feats)
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


class SimilarityRouter:
    def __init__(
        self,
        registry: Registry,
        cfg: RouterConfig,
        top_k: int = 4,
        embed: Callable[[str], dict[int, float]] = hash_embed,
    ) -> None:
        self.cfg, self.top_k, self.embed = cfg, top_k, embed
        self._vecs: dict[str, dict[int, float]] = {}
        self._category: dict[str, str] = {}
        for t in registry.all():
            doc = f"{t.name.replace('_', ' ')} {t.description} {TRIGGERS.get(t.name, '')}"
            self._vecs[t.name] = embed(doc)
            self._category[t.name] = t.category

    def rank(self, text: str) -> list[tuple[str, float]]:
        q = self.embed(text)
        scored = [(n, cosine(q, v)) for n, v in self._vecs.items()]
        scored.sort(key=lambda x: -x[1])
        return scored

    def decide(self, text: str, state: State) -> Decision:
        norm = normalize(text)
        rule = match_fast(norm)
        if rule:
            return Decision("FAST", tool=rule.tool, args=dict(rule.args), confidence=1.0,
                            category=self._category.get(rule.tool))  # fmt: skip
        if CHAT_RE.match(norm):
            return Decision("CHAT", confidence=1.0)
        ranked = self.rank(norm)
        top = [(n, s) for n, s in ranked[: self.top_k] if s > 0]
        if not top:
            return Decision("UNSURE", confidence=0.0)  # no signal: LLM sees the full catalogue
        best = top[0][1]
        names = [n for n, _ in top]
        # the LLM always gets a few candidates; low confidence just means "do not trust the order"
        conf = min(1.0, best / max(self.cfg.confidence_threshold, 1e-6)) * 0.99
        kind = "MULTI" if re.search(r"\b(?:and then|then|after that)\b", norm) else "LLM"
        if best < 0.15:
            return Decision("UNSURE", confidence=best, tools=names)
        return Decision(kind, category=self._category[names[0]], confidence=conf, tools=names)
