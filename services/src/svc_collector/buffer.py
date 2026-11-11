"""Store-and-forward buffer: durable local queue (SQLite, WAL) between OPC UA and the historian.

Points are appended on arrival and deleted only after the historian commit succeeds, so a
historian outage, restart or network partition loses no data (at-least-once delivery; the
historian insert is idempotent on (tag, ts), which makes it effectively exactly-once).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

Row = tuple[int, str, float, str, float, str, float | None]  # id, table, ts, tag, value, quality, server_ts


class Buffer:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS q (id INTEGER PRIMARY KEY AUTOINCREMENT, tbl TEXT, ts REAL, "
            "tag TEXT, value REAL, quality TEXT, server_ts REAL)"
        )

    def put(self, tbl: str, ts: float, tag: str, value: float, quality: str, server_ts: float | None) -> None:
        self.db.execute(
            "INSERT INTO q (tbl, ts, tag, value, quality, server_ts) VALUES (?,?,?,?,?,?)",
            (tbl, ts, tag, value, quality, server_ts),
        )

    def peek(self, n: int) -> list[tuple[int, str, float, str, float, str, float | None]]:
        return list(self.db.execute("SELECT id, tbl, ts, tag, value, quality, server_ts FROM q ORDER BY id LIMIT ?", (n,)))

    def ack(self, max_id: int) -> None:
        self.db.execute("DELETE FROM q WHERE id <= ?", (max_id,))

    def depth(self) -> int:
        return int(self.db.execute("SELECT count(*) FROM q").fetchone()[0])
