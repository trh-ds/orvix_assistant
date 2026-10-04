import pytest

from orvix.core.config import RouterConfig
from orvix.core.interfaces import State
from orvix.router.decision import match_fast
from orvix.router.embed_fallback import SimilarityRouter
from orvix.tools.registry import build_registry


@pytest.fixture
def router(ctx):
    return SimilarityRouter(build_registry(ctx), RouterConfig(), top_k=4)


@pytest.mark.parametrize(
    "text,tool,args",
    [
        ("Turn the volume up", "volume", {"action": "up"}),
        ("volume down please", "volume", {"action": "down"}),
        ("mute", "volume", {"action": "mute"}),
        ("pause the music", "media", {"action": "pause"}),
        ("skip this song", "media", {"action": "next"}),
        ("lock the screen", "lock_screen", {}),
        ("Take a screenshot!", "screenshot", {}),
        ("what time is it?", "now", {}),
        ("what's today's date", "now", {}),
        ("turn the wifi off", "wifi", {"state": "off"}),
        ("how much battery do I have", "system_info", {"kind": "battery"}),
    ],
)
def test_fast_rules(router, text, tool, args):
    d = router.decide(text, State())
    assert d.kind == "FAST" and d.tool == tool and d.args == args


@pytest.mark.parametrize(
    "text",
    [
        "pause the build and then delete the folder",  # extra clauses must not fast-path
        "open the volume settings",
        "play some jazz",
        "lock my account on github",
        "set a timer for 20 minutes",
    ],
)
def test_fast_rules_do_not_overmatch(text):
    assert match_fast(text) is None


def test_chat_has_no_tools(router):
    assert router.decide("hello", State()).kind == "CHAT"


@pytest.mark.parametrize(
    "text,tool",
    [
        ("open VS Code in my orvix folder", "open_in_vscode"),
        ("set a timer for 20 minutes", "set_timer"),
        ("remind me at 6pm to call mom", "set_reminder"),
        ("search the web for the latest llama.cpp release", "web_search"),
        ("what's in my downloads folder", "list_dir"),
        ("remember that my college folder is ~/clg", "remember"),
        ("type my email address here", "type_text"),
        ("launch spotify", "open_app"),
    ],
)
def test_top_k_contains_expected_tool(router, text, tool):
    d = router.decide(text, State())
    assert d.kind in {"LLM", "MULTI", "UNSURE"} and tool in d.tools


def test_gibberish_is_unsure_and_offers_everything(router):
    d = router.decide("qwxz blorp", State())
    assert d.kind == "UNSURE" and d.tools == []


def test_multi_step_detected(router):
    assert router.decide("find my resume pdf and then open it", State()).kind == "MULTI"


def test_router_is_fast(router):
    import time

    t = time.perf_counter()
    for _ in range(200):
        router.decide("open VS Code in my orvix folder", State())
    assert (time.perf_counter() - t) / 200 < 0.005  # << the 300 ms budget


def test_build_router_switch(ctx):
    from orvix.router import build_router

    reg = build_registry(ctx)
    ctx.cfg.router.engine = "none"
    assert build_router(ctx.cfg, reg) is None
    ctx.cfg.router.engine = "similarity"
    assert isinstance(build_router(ctx.cfg, reg), SimilarityRouter)
    ctx.cfg.router.engine = "nope"
    with pytest.raises(ValueError):
        build_router(ctx.cfg, reg)
