import time
from datetime import datetime

import httpx

from orvix.core.reminders import ReminderPoller
from orvix.tools import timers, web


def test_web_search_formats_and_marks_untrusted(ctx, monkeypatch):
    monkeypatch.setattr(
        web, "_ddgs_search", lambda q, n: [{"title": "T", "href": "http://a", "body": "B"}]
    )
    r = web.WebSearch(ctx).run(web.WebSearchArgs(query="llama.cpp"))
    assert r.ok and "untrusted" in r.output and "http://a" in r.output
    monkeypatch.setattr(web, "_ddgs_search", lambda q, n: [])
    assert not web.WebSearch(ctx).run(web.WebSearchArgs(query="x")).ok

    def boom(q, n):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(web, "_ddgs_search", boom)
    assert "rate limited" in web.WebSearch(ctx).run(web.WebSearchArgs(query="x")).error


def test_fetch_page_extracts_text(ctx, monkeypatch):
    monkeypatch.setattr(web, "is_public_host", lambda h: True)
    html = "<html><body><script>evil()</script><article><p>Hello release notes for v1.</p></article></body></html>"
    ctx.http_transport = httpx.MockTransport(lambda r: httpx.Response(200, text=html))
    r = web.FetchPage(ctx).run(web.FetchPageArgs(url="example.com/x"))
    assert r.ok and "release notes" in r.output and "evil" not in r.output


def test_fetch_page_blocks_private_and_bad_schemes(ctx):
    assert (
        "private" in web.FetchPage(ctx).run(web.FetchPageArgs(url="http://127.0.0.1:11434")).error
    )
    assert (
        "private" in web.FetchPage(ctx).run(web.FetchPageArgs(url="http://169.254.169.254/")).error
    )
    assert not web.FetchPage(ctx).run(web.FetchPageArgs(url="file:///etc/passwd")).ok


def test_fetch_page_redirect_to_private_is_blocked(ctx, monkeypatch):
    monkeypatch.setattr(web, "is_public_host", lambda h: h != "localhost")
    ctx.http_transport = httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"location": "http://localhost/admin"})
    )
    assert "private" in web.FetchPage(ctx).run(web.FetchPageArgs(url="http://evil.example/")).error


def test_fetch_page_http_error(ctx, monkeypatch):
    monkeypatch.setattr(web, "is_public_host", lambda h: True)
    ctx.http_transport = httpx.MockTransport(lambda r: httpx.Response(404))
    assert web.FetchPage(ctx).run(web.FetchPageArgs(url="https://x.test")).error == "HTTP 404"


def test_parse_when():
    now = datetime(2026, 10, 4, 12, 0, 0)
    assert timers.parse_when("in 20 minutes", now) == datetime(2026, 10, 4, 12, 20)
    assert timers.parse_when("in 1 hour", now) == datetime(2026, 10, 4, 13, 0)
    assert timers.parse_when("6:30pm", now) == datetime(2026, 10, 4, 18, 30)
    assert timers.parse_when("11:15", now) == datetime(2026, 10, 5, 11, 15)  # next occurrence
    assert timers.parse_when("12am", now) == datetime(2026, 10, 5, 0, 0)
    assert timers.parse_when("2026-10-05T09:00", now) == datetime(2026, 10, 5, 9, 0)
    assert timers.parse_when("whenever", now) is None
    assert timers.parse_when("25:99", now) is None


def test_timer_and_reminder_tools_store_and_poller_fires(ctx):
    r = timers.SetTimer(ctx).run(timers.SetTimerArgs(seconds=1200, label="Tea"))
    assert r.output == "Timer set for 20 minutes"
    assert ctx.store.due_reminders() == []
    ctx.store.add_reminder(time.time() - 1, "Tea is up")
    spoken, notified = [], []
    poller = ReminderPoller(ctx.store, notify=notified.append, speak=spoken.append)
    assert poller.fire_due() == ["Tea is up"] and spoken == notified == ["Tea is up"]
    assert poller.fire_due() == []  # never fires twice
    assert not timers.SetReminder(ctx).run(timers.SetReminderArgs(when="soonish", text="x")).ok
    assert (
        not timers.SetReminder(ctx)
        .run(timers.SetReminderArgs(when="2001-01-01T00:00", text="x"))
        .ok
    )
    assert (
        timers.SetReminder(ctx).run(timers.SetReminderArgs(when="in 5 minutes", text="stretch")).ok
    )
