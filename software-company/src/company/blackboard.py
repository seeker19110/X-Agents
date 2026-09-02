"""Blackboard (`shared-context`): tri thức chung theo namespace, mỗi namespace một chủ.

Trước ADR-0012 blackboard chỉ giữ `content_ref` + `summary` — con trỏ tới một artifact không tồn tại ở đâu cả. Giờ mỗi
bản ghi mang `content` (toàn văn PRD, C4, OpenAPI, threat model...) đi qua bus (nguồn sự thật, replay dựng lại được)
và được mirror ra file trong artifact store `<store>/<namespace>/v<version>.<ext>` (+ `latest.<ext>`) để người đọc/diff.
Agent hạ nguồn nhận nội dung thật trong prompt (cắt theo hạn mức ngữ cảnh, xem `context.py`), không chỉ vài dòng tóm tắt.
"""
from __future__ import annotations

from pathlib import Path

from .bus import InMemoryBus
from .events import Envelope, SharedContext

EXT = {"api-contract": "yaml", "schema": "sql"}  # phần mở rộng file mirror theo namespace; còn lại markdown


class Blackboard:
    """Đọc/ghi shared-context. Ghi đi qua bus nên được kiểm quyền owner."""
    def __init__(self, bus: InMemoryBus, store: Path | None = None):
        self.bus = bus
        self.store = Path(store) if store else None
        self._latest: dict[str, SharedContext] = {}
        bus.subscribe("shared-context", self._on)

    def _on(self, env: Envelope) -> None:
        sc = SharedContext.model_validate(env.payload)
        cur = self._latest.get(sc.namespace)
        if cur is None or sc.version > cur.version:
            self._latest[sc.namespace] = sc
            if self.store is not None and sc.content is not None:
                self._mirror(sc)

    def path(self, namespace: str, version: int | None = None) -> Path | None:
        """Đường dẫn file mirror của một bản (mặc định bản mới nhất); None nếu không có store."""
        if self.store is None: return None
        ext = EXT.get(namespace, "md")
        return self.store / namespace / (f"v{version}.{ext}" if version else f"latest.{ext}")

    def _mirror(self, sc: SharedContext) -> None:
        for p in (self.path(sc.namespace, sc.version), self.path(sc.namespace)):
            assert p is not None
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(sc.content or "", encoding="utf-8", newline="\n")

    def write(self, actor: str, namespace: str, content_ref: str, summary: str = "",
              content: str | None = None) -> SharedContext:
        v = (self._latest[namespace].version + 1) if namespace in self._latest else 1
        sc = SharedContext(namespace=namespace, version=v, content_ref=content_ref, summary=summary, content=content)
        self.bus.publish(Envelope(topic="shared-context", key=namespace, actor=actor, payload=sc.model_dump()))
        return sc

    def read(self, namespace: str) -> SharedContext | None:
        return self._latest.get(namespace)

    def content(self, namespace: str) -> str | None:
        """Toàn văn bản mới nhất (None nếu chưa có hoặc chỉ có con trỏ)."""
        sc = self._latest.get(namespace)
        return sc.content if sc else None

    def snapshot(self) -> dict[str, SharedContext]:
        return dict(self._latest)

    def rehydrate(self) -> None:
        """Dựng lại từ bus (mở lại SQLite): áp mọi bản ghi theo thứ tự, mirror bản mới nhất."""
        for env in self.bus.replay(topic="shared-context"):
            self._on(env)
