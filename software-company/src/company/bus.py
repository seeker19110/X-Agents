from __future__ import annotations

import json
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from .events import NAMESPACE_OWNERS, PAYLOAD_MODELS, Envelope

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "topics" / "schemas"

class BusError(Exception): ...
class PermissionDenied(BusError): ...


# Producer hợp lệ của mỗi topic — rút từ bảng topic trong docs/architecture.md và front matter `writes` của agent.
# Người (`human` / `human:<tên>`) chỉ được phát các topic đầu vào của khách/người duyệt (HUMAN_TOPICS); agent chỉ phát
# topic mình khai `writes`. `audit-log` ai cũng ghi; `shared-context` kiểm theo NAMESPACE_OWNERS. Bus là chốt chặn
# cuối: runner đã kiểm `writes`, nhưng CLI `publish` hay code gọi thẳng `bus.publish` cũng không được vượt quyền.
ENGINEERING_ACTORS = frozenset({"backend", "frontend", "mobile", "database", "platform", "data"})
REVIEW_PRODUCERS = frozenset({"reviewer", "qa-debugger", "security-engineer", "qa", "security"})  # tên agent hoặc `source`
TOPIC_PRODUCERS: dict[str, frozenset[str]] = {
    "research-requests": frozenset({"support-docs", "account-manager"}),
    "research-findings": frozenset({"intake", "researcher"}),
    "requirements-draft": frozenset({"synthesizer", "risk"}),
    "clarification-questions": frozenset({"clarifier"}),
    "clarification-answers": frozenset(),
    "approved-specs": frozenset({"spec-writer"}),
    "tasks": frozenset({"delivery-lead"}),
    "pull-requests": ENGINEERING_ACTORS,
    "review-results": REVIEW_PRODUCERS,
    "release-candidates": frozenset({"delivery-lead"}),
    "release-events": frozenset({"release-engineer"}),
    "incidents": frozenset({"support-docs"}),
    "external-feedback": frozenset(),
    "change-requests": frozenset({"account-manager"}),
    "acceptance-results": frozenset({"account-manager"}),
    "supervisor-actions": frozenset({"supervisor"}),
}
# Topic người được phát: đầu vào của khách (`orchestrator publish`), quyết định change request (`decide-change`),
# PR khi tiếp quản ticket (`takeover`), resume sau gate escalation (supervisor-actions).
HUMAN_TOPICS = frozenset({"research-requests", "clarification-answers", "external-feedback", "acceptance-results",
                          "change-requests", "pull-requests", "supervisor-actions"})
OPEN_TOPICS = frozenset({"audit-log", "shared-context"})  # audit: ai cũng ghi; shared-context: kiểm theo namespace


def is_human(actor: str) -> bool:
    return actor == "human" or actor.startswith("human:")


def producer_allowed(topic: str, actor: str) -> bool:
    if topic in OPEN_TOPICS: return True
    if is_human(actor): return topic in HUMAN_TOPICS
    return actor in TOPIC_PRODUCERS.get(topic, frozenset())

class InMemoryBus:
    """Bus tối giản: partition theo key, validate payload, subscriber theo topic.
    Thay bằng Redis Streams / Kafka bằng cách giữ nguyên interface publish/subscribe/replay.

    `publish` giữ một RLock: subscriber (delivery-lead, supervisor, orchestrator) chạy tuần tự dù nhiều thread gọi
    model song song (ADR-0012); handler được phép publish lồng nhau (RLock)."""

    def __init__(self, enforce_owners: bool = True):
        self._lock = threading.RLock()
        self._log: list[Envelope] = []
        self._subs: dict[str, list[Callable[[Envelope], None]]] = defaultdict(list)
        self.enforce_owners = enforce_owners
        self._schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in SCHEMA_DIR.glob("*.json")}
        self._validators = {t: Draft202012Validator(s, format_checker=FormatChecker()) for t, s in self._schemas.items()}
        self._payload_validators = {t: Draft202012Validator(s["properties"]["payload"], format_checker=FormatChecker())
                                    for t, s in self._schemas.items()}

    def _check(self, topic: str, validator: Draft202012Validator | None, data: dict) -> None:
        if validator is None:
            raise BusError(f"không có schema cho topic {topic}")
        errs = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        if errs:
            detail = "; ".join(f"{'/'.join(str(x) for x in e.absolute_path) or '$'}: {e.message}" for e in errs[:5])
            raise BusError(f"{topic} không hợp lệ theo JSON Schema: {detail}")

    def validate(self, topic: str, payload: dict) -> None:
        """Kiểm payload theo pydantic model (nếu có) và TOÀN BỘ JSON Schema của topic (type, enum, required...);
        ném BusError. Schema là nguồn sự thật; pydantic là lớp tiện dụng cho code."""
        model = PAYLOAD_MODELS.get(topic)
        if model is not None:
            try:
                model.model_validate(payload)
            except ValidationError as e:
                raise BusError(f"payload không hợp lệ cho {topic}: {e}") from e
        self._check(topic, self._payload_validators.get(topic), payload)

    def validate_envelope(self, env: Envelope) -> None:
        """Kiểm cả envelope (event_id, key, actor, ts, schema_version, correlation/causation) theo schema topic."""
        self._check(env.topic, self._validators.get(env.topic), json.loads(env.model_dump_json()))

    def _deny(self, env: Envelope, reason: str) -> None:
        """Từ chối publish: ghi audit (actor=bus) rồi ném PermissionDenied — vượt quyền phải hiện ra, không im lặng."""
        self.publish(Envelope(topic="audit-log", key="bus", actor="bus", payload={
            "actor": "bus", "action": "publish_denied",
            "evidence": json.dumps({"topic": env.topic, "key": env.key, "actor": env.actor, "reason": reason}, ensure_ascii=False)}))
        raise PermissionDenied(reason)

    def _check_publish(self, env: Envelope) -> None:
        """Validate payload + envelope và kiểm quyền producer; dùng chung cho mọi bus (bộ nhớ, SQLite)."""
        self.validate(env.topic, env.payload)
        self.validate_envelope(env)
        if not self.enforce_owners: return
        if env.topic == "shared-context":
            ns = env.payload["namespace"]
            if env.actor not in NAMESPACE_OWNERS.get(ns, set()):
                raise PermissionDenied(f"{env.actor} không được ghi namespace {ns}")
        elif not producer_allowed(env.topic, env.actor):
            who = "người" if is_human(env.actor) else "agent"
            self._deny(env, f"{who} {env.actor} không được phát topic {env.topic} "
                            f"(producer hợp lệ: {sorted(HUMAN_TOPICS) if is_human(env.actor) else sorted(TOPIC_PRODUCERS.get(env.topic, ()))})")

    def _notify(self, subs: dict[str, list[Callable[[Envelope], None]]], env: Envelope) -> None:
        for fn in list(subs.get(env.topic, [])) + list(subs.get("*", [])):
            fn(env)

    def publish(self, env: Envelope) -> Envelope:
        self._check_publish(env)
        with self._lock:
            self._log.append(env)
            self._notify(self._subs, env)
        return env

    def subscribe(self, topic: str, fn: Callable[[Envelope], None]) -> None:
        self._subs[topic].append(fn)

    def replay(self, topic: str | None = None, key: str | None = None) -> Iterable[Envelope]:
        with self._lock:
            snapshot = list(self._log)  # thread khác có thể publish trong lúc duyệt
        for e in snapshot:
            if (topic is None or e.topic == topic) and (key is None or e.key == key):
                yield e

    def latest(self, topic: str, key: str) -> Envelope | None:
        """Event mới nhất của một (topic, key). Tách riêng khỏi `replay` vì đây là đường nóng: orchestrator hỏi
        "bản draft/PR/RC gần nhất" cho gần như mọi event, và dựng cả danh sách chỉ để lấy phần tử cuối là O(N)
        mỗi lần — trên bus bền vững còn kèm parse lại từng envelope."""
        with self._lock:
            for e in reversed(self._log):
                if e.topic == topic and e.key == key:
                    return e
        return None

    def __len__(self) -> int:
        return len(self._log)
