"""Blackboard của company — cơ chế ở `xagents_core.blackboard` (K3.6b của ADR gốc 0001).

Còn lại ở đây đúng ba thứ: hai lớp của company (`Envelope`, `SharedContext` — `SharedContext` mang `rulings`
mà core không được biết) và bảng `EXT`.

Hai hàm module `scope_of`/`context_key` **biến mất**, thành phương thức của `Blackboard`. Chúng đọc
`global_namespaces`, mà bảng ấy nay ở `CoreConfig` — giữ chúng là hàm module thì `cfg` phải lấy từ đâu đó
ngoài instance, tức hai nguồn cho một luật. Nơi duy nhất gọi chúng ngoài blackboard là một ca test, đã đổi
sang vá phương thức.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from xagents_core.blackboard import Blackboard as CoreBlackboard
from xagents_core.blackboard import Scope as Scope

from .bus import InMemoryBus
from .core import CORE
from .events import Envelope, SharedContext

EXT = {"api-contract": "yaml", "schema": "sql"}  # phần mở rộng file mirror theo namespace; còn lại markdown


_CR_REF = re.compile(r"/change/([^/]+)/")


class Blackboard(CoreBlackboard[Envelope, SharedContext]):
    envelope_cls = Envelope
    context_cls = SharedContext
    EXT = EXT

    def __init__(self, bus: InMemoryBus, store: Path | None = None, cfg: Any = CORE):
        # ADR-0007 bổ sung 2026-10-16 (b): bản thuộc kế hoạch của một CR ĐÃ BỊ BÁC (`void`) không phải bản hiện hành.
        # Đọc (`read`/`content`/`snapshot`) bỏ qua nó, rơi về bản hợp lệ gần nhất; bus và số bản không đổi. Chỉ giữ
        # (version, content_ref) mỗi bản — toàn văn bản cũ đọc lại từ bus khi thật sự phải lùi (hiếm).
        self._refs: dict[Scope, list[tuple[int, str]]] = {}
        super().__init__(cfg, bus, store)

    def _on(self, env: Envelope) -> None:
        super()._on(env)
        sc = self.context_cls.model_validate(env.payload)
        self._refs.setdefault(self._scope(sc), []).append((sc.version, sc.content_ref))

    def void(self, ref: str) -> bool:
        """`content_ref` dạng `…/change/<CR>/…` của một CR mà quyết định CUỐI trên bus là `rejected`."""
        m = _CR_REF.search(ref or "")
        cr = self.bus.latest("change-requests", m.group(1)) if m else None
        return cr is not None and cr.payload.get("decision") == "rejected"

    def _current(self, scope: Scope) -> SharedContext | None:
        cur = self._latest.get(scope)
        if cur is None or not self.void(cur.content_ref):
            return cur
        for v, ref in sorted(self._refs.get(scope, []), reverse=True):
            if v < cur.version and not self.void(ref):
                key = self.context_key(scope[1], scope[0])
                return next(self.context_cls.model_validate(e.payload) for e in self.bus.replay(topic="shared-context", key=key)
                            if int(e.payload.get("version") or 0) == v)
        return None

    def read(self, namespace: str, project_id: str | None = None) -> SharedContext | None:
        return self._current(self.scope_of(namespace, project_id))

    def snapshot(self, project_id: str | None = None) -> dict[str, SharedContext]:
        return {ns: sc for (pid, ns) in list(self._latest) if pid is None or pid == project_id
                if (sc := self._current((pid, ns))) is not None}
