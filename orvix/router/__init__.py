"""Router factory: picks the engine named in config.toml ([router] engine)."""

from __future__ import annotations

from orvix.core.config import Config
from orvix.core.interfaces import Router
from orvix.tools.registry import Registry


def build_router(cfg: Config, registry: Registry) -> Router | None:
    engine = cfg.router.engine
    if engine == "none":
        return None
    if engine == "similarity":
        from orvix.router.embed_fallback import SimilarityRouter

        return SimilarityRouter(registry, cfg.router, cfg.llm.top_k_tools)
    raise ValueError(f"unknown router engine {engine!r} (use 'none' or 'similarity')")
