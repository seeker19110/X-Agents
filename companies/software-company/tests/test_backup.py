"""Sao lưu bus đang ở WAL bằng SQLite backup API, không sửa DB nguồn."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import company.sqlite_bus as sqlite_bus
from company.events import AuditLog, Envelope
from company.orchestrator import main as orch_main
from company.sqlite_bus import SQLiteBus


def test_backup_lay_ca_event_trong_wal_khi_orchestrator_con_mo(tmp_path, capsys):
    source = tmp_path / "company.sqlite"
    target = tmp_path / "backups" / "company-copy.sqlite"
    bus = SQLiteBus(source)
    bus.publish(Envelope(topic="audit-log", key="human:ops", actor="human:ops",
                         payload=AuditLog(actor="human:ops", action="backup.test").model_dump()))
    assert orch_main(["--db", str(source), "backup", "--out", str(target)]) == 0
    assert target.exists() and "backup" in capsys.readouterr().out
    with closing(sqlite3.connect(target)) as copy:
        assert copy.execute("SELECT count(*) FROM events").fetchone() == (1,)
        assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    bus.close()


def test_backup_khong_tao_nguon_hay_ghi_de_ban_cu(tmp_path, capsys):
    source = tmp_path / "missing.sqlite"
    target = tmp_path / "old.sqlite"
    target.write_bytes(b"old")
    assert orch_main(["--db", str(source), "backup", "--out", str(target)]) == 2
    assert not source.exists() and target.read_bytes() == b"old"
    assert "chưa có file bus" in capsys.readouterr().err

    SQLiteBus(source).close()
    assert orch_main(["--db", str(source), "backup", "--out", str(target)]) == 2
    assert target.read_bytes() == b"old"
    assert orch_main(["--db", str(source), "backup", "--out", str(source)]) == 2
    assert source.exists()


def test_backup_bus_hong_khong_de_lai_ban_sao_hay_temp(tmp_path, capsys):
    source = tmp_path / "broken.sqlite"
    target = tmp_path / "copy.sqlite"
    source.write_bytes(b"not sqlite")
    assert orch_main(["--db", str(source), "backup", "--out", str(target)]) == 2
    assert "backup lỗi" in capsys.readouterr().err
    assert not target.exists() and not list(tmp_path.glob(".copy.sqlite.*.tmp"))


def test_backup_integrity_hong_khong_cong_bo_file_dich(tmp_path, monkeypatch, capsys):
    source = tmp_path / "company.sqlite"
    target = tmp_path / "copy.sqlite"
    SQLiteBus(source).close()
    real_connect = sqlite3.connect

    class BadIntegrity(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == "PRAGMA integrity_check":
                return SimpleNamespace(fetchone=lambda: ("corrupt",))
            return super().execute(sql, *args)

    def connect(path, *args, **kwargs):
        if isinstance(path, Path):
            kwargs["factory"] = BadIntegrity
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite_bus.sqlite3, "connect", connect)
    assert orch_main(["--db", str(source), "backup", "--out", str(target)]) == 2
    assert "integrity_check" in capsys.readouterr().err
    assert not target.exists() and not list(tmp_path.glob(".copy.sqlite.*.tmp"))
