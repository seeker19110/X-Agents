"""Bus bền vững SQLite của company — cơ chế ở `xagents_core.sqlite_bus` (K3.5c của ADR gốc 0001).

Còn lại ở đây đúng hai thứ: lớp `Envelope` của company (qua `bus.InMemoryBus`, để giữ luật riêng
`gate.decide`), và tên file bus mặc định — nay đọc từ `CORE.db_name` chứ không viết cứng `"company.sqlite"`.

`SQLiteBus` kế thừa HAI lớp: cơ chế đĩa của core và bus company. MRO là
`SQLiteBus → CoreSQLiteBus → company.bus.InMemoryBus → CoreInMemoryBus`, nên `_extra_publish_checks` của
company vẫn chạy trong `_check_publish` mà core gọi.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from xagents_core.sqlite_bus import BUSY_TIMEOUT_S as BUSY_TIMEOUT_S
from xagents_core.sqlite_bus import DDL as DDL
from xagents_core.sqlite_bus import Lease as Lease
from xagents_core.sqlite_bus import LeaseError as LeaseError
from xagents_core.sqlite_bus import SQLiteBus as CoreSQLiteBus

from .bus import InMemoryBus
from .core import CORE
from .events import Envelope

_DDL = DDL  # tên cũ (có gạch dưới) mà test và script cũ nhập


class SQLiteBus(CoreSQLiteBus[Envelope], InMemoryBus):
    def __init__(self, path: str | Path | None = None, enforce_owners: bool = True, cfg: Any = CORE):
        super().__init__(cfg, path, enforce_owners=enforce_owners)


def missing_bus(path: Path) -> str | None:
    """Câu lỗi khi lệnh cần bus ĐÃ CÓ mà `path` chưa tồn tại; `None` nếu file có (audit 2026-09-27 B3).

    `--db` mặc định là `company.sqlite` theo cwd; mở `SQLiteBus` trên đường chưa có là TẠO một bus rỗng mới, và lệnh
    chỉ đọc in mọi chỉ số 0 như thể công ty không có gì (`TRAPS.md` §4)."""
    if path.exists():
        return None
    return (f"{path}: chưa có file bus — lệnh này chỉ đọc/sửa bus đã có, không tạo bus mới. Chạy trong "
            "companies/software-company/ (nơi có company.sqlite thật) hoặc truyền --db <đường dẫn>")


def backup_database(source: Path, target: Path) -> None:
    """Sao lưu nhất quán cả WAL; chỉ công bố bản đích khi SQLite xác nhận toàn vẹn, không ghi đè bản cũ."""
    if source.resolve() == target.resolve():
        raise ValueError("đích backup trùng file bus nguồn")
    if target.exists():
        raise FileExistsError(f"đích backup đã tồn tại: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temp = Path(tmp_name)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(temp)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise sqlite3.DatabaseError("bản backup không qua integrity_check")
        os.link(temp, target)
    finally:
        temp.unlink(missing_ok=True)
