"""Blackboard (`shared-context`): tri thức chung theo namespace, mỗi namespace một chủ, phân vùng theo dự án.

Hai tính chất phải giữ cùng lúc:

- **Toàn văn, không phải con trỏ** (ADR-0012): mỗi bản ghi mang `content` (PRD, C4, OpenAPI, threat model...) đi qua
  bus (nguồn sự thật, replay dựng lại được) và được mirror ra file trong artifact store để người đọc và diff.
  Agent hạ nguồn nhận nội dung thật trong prompt, không chỉ vài dòng tóm tắt.
- **Phân vùng theo dự án** (ADR-0018): một artifact thuộc về một `project_id`. Chỉ `knowledge` là phạm vi toàn công ty
  (`project_id=None`): bài học estimate-vs-actual dùng chung. Không phân vùng thì hai khách chạy trên cùng bus sẽ
  ghi đè `prd`/`architecture` của nhau, và agent của dự án B đọc phải PRD của dự án A.

Key của event là `namespace` hoặc `project_id/namespace`, nên replay theo key vẫn lọc được; file mirror nằm ở
`<store>/<project>/<namespace>/v<version>.<ext>` (+ `latest.<ext>`), namespace toàn công ty thì không có tầng dự án.
"""
from __future__ import annotations

from pathlib import Path

from .bus import InMemoryBus
from .events import GLOBAL_NAMESPACES, Envelope, SharedContext

Scope = tuple[str | None, str]  # (project_id hoặc None nếu toàn công ty, namespace)

EXT = {"api-contract": "yaml", "schema": "sql"}  # phần mở rộng file mirror theo namespace; còn lại markdown


def scope_of(namespace: str, project_id: str | None) -> Scope:
    return (None if namespace in GLOBAL_NAMESPACES else project_id, namespace)


def context_key(namespace: str, project_id: str | None) -> str:
    """Key của event shared-context: namespace toàn công ty giữ nguyên tên, còn lại có tiền tố dự án."""
    pid, ns = scope_of(namespace, project_id)
    return ns if pid is None else f"{pid}/{ns}"


class Blackboard:
    """Đọc/ghi shared-context. Ghi đi qua bus nên được kiểm quyền owner. Trạng thái giữ theo (project_id, namespace)."""

    def __init__(self, bus: InMemoryBus, store: Path | None = None):
        self.bus = bus
        self.store = Path(store) if store else None
        self._latest: dict[Scope, SharedContext] = {}
        bus.subscribe("shared-context", self._on)

    @staticmethod
    def _scope(sc: SharedContext) -> Scope:
        return scope_of(sc.namespace, sc.project_id)

    def _on(self, env: Envelope) -> None:
        sc = SharedContext.model_validate(env.payload)
        cur = self._latest.get(self._scope(sc))
        if cur is None or sc.version > cur.version:
            self._latest[self._scope(sc)] = sc
            if self.store is not None and sc.content is not None:
                self._mirror(sc)

    def path(self, namespace: str, version: int | None = None, project_id: str | None = None) -> Path | None:
        """Đường dẫn file mirror của một bản (mặc định bản mới nhất); None nếu không có store."""
        if self.store is None: return None
        pid, ns = scope_of(namespace, project_id)
        ext = EXT.get(ns, "md")
        base = self.store if pid is None else self.store / pid
        return base / ns / (f"v{version}.{ext}" if version else f"latest.{ext}")

    def _mirror(self, sc: SharedContext) -> None:
        for p in (self.path(sc.namespace, sc.version, sc.project_id), self.path(sc.namespace, None, sc.project_id)):
            assert p is not None
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(sc.content or "", encoding="utf-8", newline="\n")

    def write(self, actor: str, namespace: str, content_ref: str, summary: str = "", content: str | None = None,
              project_id: str | None = None) -> SharedContext:
        scope = scope_of(namespace, project_id)
        v = (self._latest[scope].version + 1) if scope in self._latest else 1
        sc = SharedContext(namespace=namespace, version=v, content_ref=content_ref,  # type: ignore[arg-type]
                           summary=summary, content=content, project_id=scope[0])
        self.bus.publish(Envelope(topic="shared-context", key=context_key(namespace, project_id), actor=actor,
                                  payload=sc.model_dump()))
        return sc

    def read(self, namespace: str, project_id: str | None = None) -> SharedContext | None:
        return self._latest.get(scope_of(namespace, project_id))

    def content(self, namespace: str, project_id: str | None = None) -> str | None:
        """Toàn văn bản mới nhất (None nếu chưa có hoặc chỉ có con trỏ)."""
        sc = self.read(namespace, project_id)
        return sc.content if sc else None

    def all(self) -> dict[str, SharedContext]:
        """Mọi bản ghi mới nhất, khoá `<project>/<namespace>` (hoặc namespace trần nếu toàn công ty) — cho `status`."""
        return {f"{pid}/{ns}" if pid else ns: sc
                for (pid, ns), sc in sorted(self._latest.items(), key=lambda kv: (kv[0][0] or "", kv[0][1]))}

    def overview(self) -> dict[str, str]:
        """Toàn bộ blackboard cho lệnh `status`: khoá là `<project>/<namespace>` (hoặc namespace trần nếu toàn công ty)."""
        return {f"{pid}/{ns}" if pid else ns: sc.content_ref
                for (pid, ns), sc in sorted(self._latest.items(), key=lambda kv: (kv[0][0] or "", kv[0][1]))}

    def snapshot(self, project_id: str | None = None) -> dict[str, SharedContext]:
        """Bản mới nhất mỗi namespace TRONG phạm vi một dự án, cộng các namespace toàn công ty.
        `project_id=None` trả về mọi thứ không thuộc dự án nào (dùng cho demo/eval)."""
        return {ns: sc for (pid, ns), sc in self._latest.items() if pid is None or pid == project_id}

    def rehydrate(self) -> None:
        """Dựng lại từ bus (mở lại SQLite): áp mọi bản ghi theo thứ tự, mirror bản mới nhất."""
        for env in self.bus.replay(topic="shared-context"):
            self._on(env)
