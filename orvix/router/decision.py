"""Deterministic fast-path rules. Highest precision, ~0 ms: a match skips the LLM entirely.

Only unambiguous phrasings belong here. Anything the rules do not match goes to the similarity
router, then the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FastRule:
    pattern: re.Pattern[str]
    tool: str
    args: dict[str, Any]


def _r(pattern: str, tool: str, **args: Any) -> FastRule:
    return FastRule(re.compile(rf"^(?:please\s+)?(?:{pattern})(?:\s+please)?$"), tool, args)


FAST_RULES: tuple[FastRule, ...] = (
    _r(r"(?:turn\s+(?:the\s+)?volume\s+up|volume\s+up|louder|raise\s+the\s+volume)", "volume", action="up"),
    _r(r"(?:turn\s+(?:the\s+)?volume\s+down|volume\s+down|quieter|lower\s+the\s+volume)", "volume", action="down"),
    _r(r"(?:mute|mute\s+(?:the\s+)?(?:sound|volume|audio))", "volume", action="mute"),
    _r(r"(?:unmute|unmute\s+(?:the\s+)?(?:sound|volume|audio))", "volume", action="unmute"),
    _r(r"(?:brightness\s+up|(?:turn\s+)?(?:the\s+)?brightness\s+up|brighter|increase\s+(?:the\s+)?brightness)", "brightness", action="up"),
    _r(r"(?:brightness\s+down|(?:turn\s+)?(?:the\s+)?brightness\s+down|dimmer|decrease\s+(?:the\s+)?brightness)", "brightness", action="down"),
    _r(r"(?:pause|pause\s+(?:the\s+)?(?:music|song|video|playback))", "media", action="pause"),
    _r(r"(?:play|resume|resume\s+(?:the\s+)?(?:music|song|video|playback))", "media", action="play"),
    _r(r"(?:next|skip|next\s+(?:song|track)|skip\s+(?:this\s+)?(?:song|track))", "media", action="next"),
    _r(r"(?:previous|previous\s+(?:song|track)|go\s+back)", "media", action="previous"),
    _r(r"(?:lock|lock\s+(?:the\s+)?(?:screen|laptop|computer)|lock\s+it)", "lock_screen"),
    _r(r"(?:take\s+a\s+screenshot|screenshot|capture\s+(?:the\s+)?screen)", "screenshot"),
    _r(r"(?:what(?:'s|\s+is)\s+the\s+time|what\s+time\s+is\s+it|(?:what(?:'s|\s+is)\s+)?(?:today's\s+date|the\s+date|the\s+time)|what\s+day\s+is\s+it|what\s+is\s+today)", "now"),
    _r(r"(?:wifi\s+off|turn\s+(?:the\s+)?wi-?fi\s+off|disable\s+wi-?fi)", "wifi", state="off"),
    _r(r"(?:wifi\s+on|turn\s+(?:the\s+)?wi-?fi\s+on|enable\s+wi-?fi)", "wifi", state="on"),
    _r(r"(?:bluetooth\s+off|turn\s+(?:the\s+)?bluetooth\s+off)", "bluetooth", state="off"),
    _r(r"(?:bluetooth\s+on|turn\s+(?:the\s+)?bluetooth\s+on)", "bluetooth", state="on"),
    _r(r"(?:how\s+much\s+battery(?:\s+do\s+i\s+have)?(?:\s+is\s+left)?|battery(?:\s+level)?|what(?:'s|\s+is)\s+my\s+battery(?:\s+(?:level|at))?)", "system_info", kind="battery"),
    _r(r"(?:how\s+much\s+(?:ram|memory)\s+(?:am\s+i\s+using|is\s+(?:used|free))|ram\s+usage|memory\s+usage)", "system_info", kind="ram"),
    _r(r"(?:how\s+much\s+disk\s+space(?:\s+is\s+left)?|disk\s+space|disk\s+usage)", "system_info", kind="disk"),
)  # fmt: skip

_PUNCT = re.compile(r"[^\w\s'\-]")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", text.lower())).strip()


def match_fast(text: str) -> FastRule | None:
    t = normalize(text)
    for rule in FAST_RULES:
        if rule.pattern.match(t):
            return rule
    return None
