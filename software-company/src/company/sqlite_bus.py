"""Bus bền vững trên SQLite: cùng interface với InMemoryBus, đủ cho một máy.
Mọi envelope append vào bảng `events`; mở lại là replay được theo topic/key. Thay Kafka/Redis sau nếu cần."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from .bus import InMemoryBus
from .events import Envelope

_DDL = """
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT UNIQUE NOT NULL,
  topic TEXT NOT NULL, key TEXT NOT NULL, actor TEXT NOT NULL, ts TEXT NOT NULL,
  body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_topic_key ON events(topic, key);
"""


class SQLiteBus(InMemoryBus):
    def __init__(self, path: str | Path = "company.sqlite", enforce_owners: bool = True):
        super().__init__(enforce_owners=enforce_owners)
        self.path = Path(path)
        self._db = sqlite3.connect(self.path)
        self._db.executescript(_DDL)
        self._log = [Envelope.model_validate_json(row[0])
                     for row in self._db.execute("SELECT body FROM events ORDER BY seq")]

    def publish(self, env: Envelope) -> Envelope:
        # Lớp cha validate + kiểm quyền. Tạm tháo subscriber để ghi đĩa TRƯỚC khi báo, tránh mất event khi handler ném lỗi.
        subs, self._subs = self._subs, defaultdict(list)
        try:
            super().publish(env)
        finally:
            self._subs = subs
        with self._db:
            self._db.execute("INSERT INTO events(event_id, topic, key, actor, ts, body) VALUES (?,?,?,?,?,?)",
                             (env.event_id, env.topic, env.key, env.actor, env.ts.isoformat(), env.model_dump_json()))
        for fn in list(subs.get(env.topic, [])) + list(subs.get("*", [])):
            fn(env)
        return env

    def replay(self, topic: str | None = None, key: str | None = None) -> Iterable[Envelope]:
        q, args, conds = "SELECT body FROM events", [], []
        if topic: conds.append("topic = ?"); args.append(topic)
        if key: conds.append("key = ?"); args.append(key)
        if conds: q += " WHERE " + " AND ".join(conds)
        for (body,) in self._db.execute(q + " ORDER BY seq", args):
            yield Envelope.model_validate_json(body)

    def close(self) -> None:
        self._db.close()
