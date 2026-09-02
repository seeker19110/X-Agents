"""Blackboard `shared-context`, phân vùng theo dự án.

Mỗi artifact thuộc một `project_id` (PRD, C4, API contract, threat model... của dự án nào). Chỉ `knowledge`
là phạm vi toàn công ty (`project_id=None`): bài học estimate-vs-actual dùng chung cho mọi dự án.
Không phân vùng thì hai khách chạy trên cùng bus sẽ ghi đè `prd`/`architecture` của nhau — và agent của dự án B
đọc phải PRD của dự án A. Key của event là `namespace` hoặc `project_id/namespace`, nên replay theo key vẫn lọc được.
"""
from __future__ import annotations

from .bus import InMemoryBus
from .events import GLOBAL_NAMESPACES, Envelope, SharedContext


def context_key(namespace: str, project_id: str | None) -> str:
    """Key của event shared-context: namespace toàn công ty giữ nguyên tên, còn lại có tiền tố dự án."""
    return namespace if namespace in GLOBAL_NAMESPACES or not project_id else f"{project_id}/{namespace}"


class Blackboard:
    """Đọc/ghi shared-context. Ghi đi qua bus nên được kiểm quyền owner. Trạng thái giữ theo (project_id, namespace)."""
    def __init__(self, bus: InMemoryBus):
        self.bus = bus
        self._latest: dict[tuple[str | None, str], SharedContext] = {}
        bus.subscribe("shared-context", self._on)

    @staticmethod
    def _scope(sc: SharedContext) -> tuple[str | None, str]:
        return (None if sc.namespace in GLOBAL_NAMESPACES else sc.project_id, sc.namespace)

    def _on(self, env: Envelope) -> None:
        sc = SharedContext.model_validate(env.payload)
        cur = self._latest.get(self._scope(sc))
        if cur is None or sc.version > cur.version:
            self._latest[self._scope(sc)] = sc

    def write(self, actor: str, namespace: str, content_ref: str, summary: str = "",
              project_id: str | None = None) -> SharedContext:
        scope = (None if namespace in GLOBAL_NAMESPACES else project_id, namespace)
        v = (self._latest[scope].version + 1) if scope in self._latest else 1
        sc = SharedContext(namespace=namespace, version=v, content_ref=content_ref,  # type: ignore[arg-type]
                           summary=summary, project_id=None if namespace in GLOBAL_NAMESPACES else project_id)
        self.bus.publish(Envelope(topic="shared-context", key=context_key(namespace, project_id), actor=actor,
                                  payload=sc.model_dump()))
        return sc

    def read(self, namespace: str, project_id: str | None = None) -> SharedContext | None:
        return self._latest.get((None if namespace in GLOBAL_NAMESPACES else project_id, namespace))

    def overview(self) -> dict[str, str]:
        """Toàn bộ blackboard cho lệnh `status`: khoá là `<project>/<namespace>` (hoặc namespace trần nếu toàn công ty)."""
        return {f"{pid}/{ns}" if pid else ns: sc.content_ref for (pid, ns), sc in sorted(self._latest.items(),
                                                                                         key=lambda kv: (kv[0][0] or "", kv[0][1]))}

    def snapshot(self, project_id: str | None = None) -> dict[str, SharedContext]:
        """Bản mới nhất mỗi namespace TRONG phạm vi một dự án, cộng các namespace toàn công ty.
        `project_id=None` trả về mọi thứ không thuộc dự án nào (dùng cho demo/eval)."""
        return {ns: sc for (pid, ns), sc in self._latest.items() if pid is None or pid == project_id}
