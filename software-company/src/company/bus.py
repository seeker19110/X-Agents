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

    def publish(self, env: Envelope) -> Envelope:
        self.validate(env.topic, env.payload)
        self.validate_envelope(env)
        if env.topic == "shared-context" and self.enforce_owners:
            ns = env.payload["namespace"]
            if env.actor not in NAMESPACE_OWNERS.get(ns, set()):
                raise PermissionDenied(f"{env.actor} không được ghi namespace {ns}")
        with self._lock:
            self._log.append(env)
            for fn in list(self._subs.get(env.topic, [])) + list(self._subs.get("*", [])):
                fn(env)
        return env

    def subscribe(self, topic: str, fn: Callable[[Envelope], None]) -> None:
        self._subs[topic].append(fn)

    def replay(self, topic: str | None = None, key: str | None = None) -> Iterable[Envelope]:
        with self._lock:
            snapshot = list(self._log)  # thread khác có thể publish trong lúc duyệt
        for e in snapshot:
            if (topic is None or e.topic == topic) and (key is None or e.key == key):
                yield e

    def __len__(self) -> int:
        return len(self._log)
