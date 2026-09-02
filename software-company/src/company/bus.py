from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from pydantic import ValidationError

from .events import NAMESPACE_OWNERS, PAYLOAD_MODELS, Envelope

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "topics" / "schemas"

class BusError(Exception): ...
class PermissionDenied(BusError): ...

class InMemoryBus:
    """Bus tối giản: partition theo key, validate payload, subscriber theo topic.
    Thay bằng Redis Streams / Kafka bằng cách giữ nguyên interface publish/subscribe/replay."""

    def __init__(self, enforce_owners: bool = True):
        self._log: list[Envelope] = []
        self._subs: dict[str, list[Callable[[Envelope], None]]] = defaultdict(list)
        self.enforce_owners = enforce_owners
        self._schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in SCHEMA_DIR.glob("*.json")}

    def publish(self, env: Envelope) -> Envelope:
        model = PAYLOAD_MODELS.get(env.topic)
        if model is not None:
            try:
                model.model_validate(env.payload)
            except ValidationError as e:
                raise BusError(f"payload không hợp lệ cho {env.topic}: {e}") from e
        schema = self._schemas.get(env.topic)
        if schema is not None:
            missing = [k for k in schema["properties"]["payload"].get("required", []) if k not in env.payload]
            if missing:
                raise BusError(f"{env.topic} thiếu trường bắt buộc: {missing}")
        if env.topic == "shared-context" and self.enforce_owners:
            ns = env.payload["namespace"]
            if env.actor not in NAMESPACE_OWNERS.get(ns, set()):
                raise PermissionDenied(f"{env.actor} không được ghi namespace {ns}")
        self._log.append(env)
        for fn in list(self._subs.get(env.topic, [])) + list(self._subs.get("*", [])):
            fn(env)
        return env

    def subscribe(self, topic: str, fn: Callable[[Envelope], None]) -> None:
        self._subs[topic].append(fn)

    def replay(self, topic: str | None = None, key: str | None = None) -> Iterable[Envelope]:
        for e in self._log:
            if (topic is None or e.topic == topic) and (key is None or e.key == key):
                yield e

    def __len__(self) -> int:
        return len(self._log)
