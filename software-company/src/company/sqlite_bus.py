"""Bus bền vững trên SQLite: cùng interface với InMemoryBus, đủ cho một máy.
Mọi envelope append vào bảng `events`; mở lại là replay được theo topic/key. Thay Kafka/Redis sau nếu cần."""
from __future__ import annotations

import json
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
        # check_same_thread=False + RLock của lớp cha: nhiều thread của orchestrator dùng chung một kết nối, tuần tự hoá.
        # timeout=30: tiến trình khác (gate CLI, publish) đang ghi thì chờ thay vì "database is locked" ngay.
        # WAL: đọc không chặn ghi giữa các tiến trình (orchestrator watch + CLI cùng một file).
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_DDL)
        self._seq = 0
        self._log = []
        self._seen: set[str] = set()  # event_id đã có trong _log (tự ghi hoặc poll về) — poll không nạp lại
        for seq, body in self._db.execute("SELECT seq, body FROM events ORDER BY seq"):
            env = Envelope.model_validate_json(body)
            self._log.append(env); self._seen.add(env.event_id); self._seq = seq

    def publish(self, env: Envelope) -> Envelope:
        # Lớp cha validate + kiểm quyền; ghi đĩa TRƯỚC khi vào log bộ nhớ và báo subscriber: handler ném lỗi thì event
        # vẫn đã bền vững. KHÔNG nhảy `_seq` tới lastrowid: tiến trình khác có thể đã chèn hàng có seq nhỏ hơn (giữa
        # hai lần poll) — poll đọc từ `_seq` cũ và bỏ qua hàng đã thấy theo event_id.
        self._check_publish(env)
        with self._lock:
            with self._db:
                self._db.execute("INSERT INTO events(event_id, topic, key, actor, ts, body) VALUES (?,?,?,?,?,?)",
                                 (env.event_id, env.topic, env.key, env.actor, env.ts.isoformat(), env.model_dump_json()))
            self._log.append(env); self._seen.add(env.event_id)
            self._notify(self._subs, env)
        return env

    def _notify_safely(self, env: Envelope) -> None:
        """Như `_notify` nhưng một handler ném lỗi không làm mất event cho handler khác: ghi audit rồi đi tiếp."""
        for fn in list(self._subs.get(env.topic, [])) + list(self._subs.get("*", [])):
            try:
                fn(env)
            except Exception as e:  # mọi lỗi handler đều phải hiện ra audit, không nuốt im lặng
                self._persist_only(Envelope(topic="audit-log", key="bus", actor="bus", payload={
                    "actor": "bus", "action": "subscriber_error",
                    "evidence": json.dumps({"event_id": env.event_id, "topic": env.topic, "key": env.key,
                                            "handler": getattr(fn, "__qualname__", repr(fn)), "error": str(e)[:300]},
                                           ensure_ascii=False)}))

    def _persist_only(self, env: Envelope) -> Envelope:
        """Ghi đĩa + log nhưng không báo subscriber: audit về handler hỏng không được đi qua chính handler đó."""
        with self._lock:
            subs, self._subs = self._subs, defaultdict(list)
            try:
                return self.publish(env)
            finally:
                self._subs = subs

    def poll(self) -> list[Envelope]:
        """Nạp event do tiến trình KHÁC ghi vào cùng file (gate CLI, human publish) và báo subscriber như event mới.
        Hàng do chính tiến trình này ghi (đã có trong _log) chỉ đẩy `_seq` lên, không báo lại."""
        with self._lock:
            rows = self._db.execute("SELECT seq, body FROM events WHERE seq > ? ORDER BY seq", (self._seq,)).fetchall()
            new: list[Envelope] = []
            for seq, body in rows:
                self._seq = seq
                env = Envelope.model_validate_json(body)
                if env.event_id in self._seen: continue
                self._log.append(env); self._seen.add(env.event_id); new.append(env)
                self._notify_safely(env)
        return new

    def replay(self, topic: str | None = None, key: str | None = None) -> Iterable[Envelope]:
        q, args, conds = "SELECT body FROM events", [], []
        if topic: conds.append("topic = ?"); args.append(topic)
        if key: conds.append("key = ?"); args.append(key)
        if conds: q += " WHERE " + " AND ".join(conds)
        with self._lock:
            rows = self._db.execute(q + " ORDER BY seq", args).fetchall()
        for (body,) in rows:
            yield Envelope.model_validate_json(body)

    def latest(self, topic: str, key: str) -> Envelope | None:
        """Như lớp cha nhưng để SQLite tìm: `ORDER BY seq DESC LIMIT 1` trên index (topic, key), không quét log."""
        with self._lock:
            row = self._db.execute("SELECT body FROM events WHERE topic = ? AND key = ? ORDER BY seq DESC LIMIT 1",
                                   (topic, key)).fetchone()
        return Envelope.model_validate_json(row[0]) if row else None

    def close(self) -> None:
        self._db.close()
