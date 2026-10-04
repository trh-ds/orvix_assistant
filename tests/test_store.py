import time

from orvix.memory.store import Store


def test_turn_and_tool_call_roundtrip():
    s = Store(":memory:")
    tid = s.start_turn("open code")
    s.log_tool_call(tid, "open_app", {"name": "code"}, "SAFE", None, "ok", "", 12.5)
    s.finish_turn(
        tid, reply="done", timings={"a": 1}, success=True, decision="FAST", confidence=0.9
    )
    t = s.turns()[0]
    assert t["reply"] == "done" and t["success"] == 1
    assert s.tool_calls(tid)[0]["tool"] == "open_app"


def test_facts_persist_and_search(tmp_path):
    p = tmp_path / "t.db"
    Store(p).remember("College Folder", "~/clg")
    s2 = Store(p)
    assert s2.get_fact("college folder") == "~/clg"
    assert s2.search_facts("open my college folder") == [("college folder", "~/clg")]
    assert s2.forget("college folder") and s2.get_fact("college folder") is None


def test_reminders():
    s = Store(":memory:")
    rid = s.add_reminder(time.time() - 1, "tea")
    assert len(s.due_reminders()) == 1
    s.complete_reminder(rid)
    assert s.due_reminders() == []
