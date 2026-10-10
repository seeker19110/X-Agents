"""Blackboard của `keeper` — cơ chế ở `xagents_core.blackboard`, hai dòng ở đây là lớp Envelope/SharedContext.

`keeper` chỉ có `keeper-supervisor` khai `context_namespace_write: [knowledge]` (`events.py`, `namespace_owners`);
9 agent còn lại `null`. Đường ghi blackboard vẫn KHÔNG chạy trong sản xuất vì orchestrator keeper không gọi LLM
ngoài eval (`AgentRunner` chỉ được dựng trong `evals.py`). Lớp này tồn tại vì `EvalSuite.run_eval` dựng một
blackboard cho mọi ca (hợp đồng của core), và vì `shared-context` là topic mở của `CORE` — ngày orchestrator
keeper chạy agent thật thì chỗ ấy đã đúng sẵn, không phải nhớ dựng.

`store=None`: `keeper` chưa có artifact store nên nhánh mirror ra đĩa không chạy (như studio).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from xagents_core.blackboard import Blackboard as CoreBlackboard

from .bus import KeeperMemoryBus
from .core import CORE
from .events import Envelope, SharedContext

__all__ = ["Blackboard"]


class Blackboard(CoreBlackboard[Envelope, SharedContext]):
    envelope_cls = Envelope
    context_cls = SharedContext

    def __init__(self, bus: KeeperMemoryBus, store: Path | None = None, cfg: Any = CORE):
        super().__init__(cfg, bus, store)
