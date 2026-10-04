"""SQLite storage: turns, tool_calls, facts, reminders (see docs/DESIGN.md, Storage)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    transcript TEXT NOT NULL,
    router_decision TEXT,
    router_confidence REAL,
    reply TEXT,
    timings TEXT,
    success INTEGER,
    correction TEXT
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id INTEGER REFERENCES turns(id),
    tool TEXT NOT NULL,
    args TEXT,
    risk TEXT,
    confirmed INTEGER,
    result TEXT,
    error TEXT,
    duration_ms REAL
);
CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created REAL NOT NULL,
    last_used REAL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    due REAL NOT NULL,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    # turns / tool_calls -------------------------------------------------
    def start_turn(self, transcript: str) -> int:
        cur = self._exec(
            "INSERT INTO turns (ts, transcript) VALUES (?, ?)", (time.time(), transcript)
        )
        return int(cur.lastrowid)

    def finish_turn(
        self,
        turn_id: int,
        *,
        reply: str,
        timings: dict,
        success: bool,
        decision: str | None = None,
        confidence: float | None = None,
    ) -> None:
        self._exec(
            "UPDATE turns SET reply=?, timings=?, success=?, router_decision=?, "
            "router_confidence=? WHERE id=?",
            (reply, json.dumps(timings), int(success), decision, confidence, turn_id),
        )

    def set_correction(self, turn_id: int, correction: str) -> None:
        self._exec("UPDATE turns SET correction=? WHERE id=?", (correction, turn_id))

    def log_tool_call(
        self,
        turn_id: int,
        tool: str,
        args: dict,
        risk: str,
        confirmed: bool | None,
        result: str,
        error: str,
        duration_ms: float,
    ) -> None:
        self._exec(
            "INSERT INTO tool_calls (turn_id, tool, args, risk, confirmed, result, error, "
            "duration_ms) VALUES (?,?,?,?,?,?,?,?)",
            (
                turn_id,
                tool,
                json.dumps(args),
                risk,
                None if confirmed is None else int(confirmed),
                result,
                error,
                duration_ms,
            ),
        )

    def turns(self) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM turns ORDER BY id")

    def tool_calls(self, turn_id: int | None = None) -> list[sqlite3.Row]:
        if turn_id is None:
            return self._query("SELECT * FROM tool_calls ORDER BY id")
        return self._query("SELECT * FROM tool_calls WHERE turn_id=? ORDER BY id", (turn_id,))

    # facts -------------------------------------------------------------
    def remember(self, key: str, value: str) -> None:
        now = time.time()
        self._exec(
            "INSERT INTO facts (key, value, created, last_used) VALUES (?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, last_used=excluded.last_used",
            (key.strip().lower(), value, now, now),
        )

    def get_fact(self, key: str) -> str | None:
        rows = self._query("SELECT value FROM facts WHERE key=?", (key.strip().lower(),))
        return rows[0]["value"] if rows else None

    def search_facts(self, query: str, limit: int = 5) -> list[tuple[str, str]]:
        words = [w for w in query.lower().split() if len(w) > 2]
        if not words:
            return []
        rows = self._query("SELECT key, value FROM facts")
        scored = []
        for r in rows:
            hay = f"{r['key']} {r['value']}".lower()
            score = sum(w in hay for w in words)
            if score:
                scored.append((score, r["key"], r["value"]))
        scored.sort(reverse=True)
        out = [(k, v) for _, k, v in scored[:limit]]
        for k, _ in out:
            self._exec("UPDATE facts SET last_used=? WHERE key=?", (time.time(), k))
        return out

    def forget(self, key: str) -> bool:
        return self._exec("DELETE FROM facts WHERE key=?", (key.strip().lower(),)).rowcount > 0

    # reminders ---------------------------------------------------------
    def add_reminder(self, due: float, text: str) -> int:
        return int(
            self._exec("INSERT INTO reminders (due, text) VALUES (?,?)", (due, text)).lastrowid
        )

    def due_reminders(self, now: float | None = None) -> list[sqlite3.Row]:
        return self._query(
            "SELECT * FROM reminders WHERE done=0 AND due<=? ORDER BY due", (now or time.time(),)
        )

    def complete_reminder(self, rid: int) -> None:
        self._exec("UPDATE reminders SET done=1 WHERE id=?", (rid,))
