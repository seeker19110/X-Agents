"""ADR-0064: orchestrator tự chạy phép đo NFR (perf/a11y) đã khai, trên môi trường staging đã deploy.

Hub thật 2026-10-17 (QLKH-DD-CSV, UAT-REL-126): Gate 3 ký với perf DD-N4 và a11y DD-N6 "CHƯA ĐO". Sandbox của agent không
có node/k6/docker và không ra được staging. Chủ dự án chọn "hub tự đo". Lệnh đo là script CÓ SẴN của khách
(`tests/perf/export_p95.py`, `npm run a11y`), người vận hành khai trong `<project>.measure.json` cạnh file env bí mật
(cùng hàng rào với override của ADR-0061 bổ sung 2026-10-17): code của hub chạy, ghi `verified_by=orchestrator`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from company.deploy import ENV_SECRETS_DIR, DeployError
from company.measure import load_measures, measure_config, run_measures

PROJECT = "company-qlkh-dd-csv-staging"
GIA_TRI_GIA = "mat-khau-gia-cua-test"


def _cfg(d: Path, measures: list, mode: int = 0o600) -> Path:
    d.mkdir(exist_ok=True)
    f = d / f"{PROJECT}.measure.json"
    f.write_text(json.dumps({"measures": measures}), encoding="utf-8")
    f.chmod(mode)
    return f


def _env(d: Path) -> Path:
    f = d / f"{PROJECT}.env"
    f.write_text(f"# chú thích\n\nQLKH_SEED_PASSWORD={GIA_TRI_GIA}\nKHAC=x\n", encoding="utf-8")
    f.chmod(0o600)
    return f


PY_OK = [
    sys.executable,
    "-c",
    "import os,sys;print('p95_ms=812 url='+sys.argv[1]);print(os.environ.get('PW',''))",
    "{base_url}",
]
PY_FAIL = [sys.executable, "-c", "import sys;print('p95_ms=2500');sys.exit(1)"]


def test_khong_dat_thu_muc_hoac_khong_co_file_thi_khong_do(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.delenv(ENV_SECRETS_DIR, raising=False)
    assert measure_config(repo, PROJECT) == ""
    monkeypatch.setenv(ENV_SECRETS_DIR, str(tmp_path / "hub"))
    assert measure_config(repo, PROJECT) == ""


def test_file_khai_nguoi_khac_ghi_duoc_hoac_nam_trong_repo_thi_tu_choi(tmp_path, monkeypatch):
    """Lệnh đo chạy trên máy hub: ai ghi được file khai là chạy được lệnh trên máy hub."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_cfg(tmp_path / "hub", [], mode=0o664).parent))
    with pytest.raises(DeployError, match="ghi được"):
        measure_config(repo, PROJECT)
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_cfg(repo / ".hub", []).parent))
    with pytest.raises(DeployError, match="ngoài repo"):
        measure_config(repo, PROJECT)


def test_doc_khai_bao_hop_le(tmp_path):
    f = _cfg(
        tmp_path / "hub",
        [{"id": "DD-N4", "kind": "perf", "command": PY_OK, "timeout_s": 99999, "env": {"PW": "QLKH_SEED_PASSWORD"}}],
    )
    (m,) = load_measures(str(f))
    assert m.id == "DD-N4" and m.kind == "perf" and m.command == tuple(PY_OK)
    assert m.timeout_s == 1800, "trần cứng: một phép đo không giữ orchestrator quá 30 phút"
    assert m.env == (("PW", "QLKH_SEED_PASSWORD"),)


@pytest.mark.parametrize(
    "bad",
    [
        "không phải json",
        json.dumps({"measures": [{"id": "X", "kind": "perf", "command": "chuỗi, không phải mảng"}]}),
        json.dumps({"measures": [{"id": "X", "kind": "la", "command": ["a"]}]}),
        json.dumps({"measures": [{"id": "", "kind": "perf", "command": ["a"]}]}),
        json.dumps({"measures": [{"id": "X", "kind": "perf", "command": ["a"], "env": ["PW"]}]}),
        json.dumps({"measures": "x"}),
    ],
)
def test_khai_bao_hong_thi_nem_khong_doan(tmp_path, bad):
    f = tmp_path / "m.json"
    f.write_text(bad, encoding="utf-8")
    with pytest.raises(DeployError, match="measure"):
        load_measures(str(f))


def test_chay_lenh_thay_base_url_nap_bien_tu_file_env_va_che_gia_tri(tmp_path):
    hub = tmp_path / "hub"
    f = _cfg(
        hub,
        [
            {"id": "DD-N4", "kind": "perf", "command": PY_OK, "env": {"PW": "QLKH_SEED_PASSWORD"}},
            {"id": "DD-N6", "kind": "a11y", "command": PY_FAIL},
        ],
    )
    efile = _env(hub)
    repo = tmp_path / "repo"
    repo.mkdir()
    out = run_measures(repo, load_measures(str(f)), "http://127.0.0.1:8080", str(efile))
    a, b = out
    assert a["id"] == "DD-N4" and a["ok"] is True and a["exit_code"] == 0 and a["verified_by"] == "orchestrator"
    assert "url=http://127.0.0.1:8080" in a["stdout_tail"], "{base_url} được thay bằng địa chỉ staging đã deploy"
    assert GIA_TRI_GIA not in json.dumps(out) and "***" in a["stdout_tail"], "giá trị bí mật nạp vào env bị che"
    assert a["command"] == PY_OK, "bằng chứng ghi lệnh ĐÃ KHAI (placeholder), không ghi giá trị"
    assert b["ok"] is False and b["exit_code"] == 1 and "p95_ms=2500" in b["stdout_tail"]


def test_bien_khai_ma_file_env_khong_co_thi_khong_chay_va_noi_ro(tmp_path):
    hub = tmp_path / "hub"
    f = _cfg(hub, [{"id": "DD-N4", "kind": "perf", "command": PY_OK, "env": {"PW": "KHONG_CO"}}])
    repo = tmp_path / "repo"
    repo.mkdir()
    (r,) = run_measures(repo, load_measures(str(f)), "http://127.0.0.1:8080", str(_env(hub)))
    assert r["ok"] is False and r["unverified"] is True and "KHONG_CO" in r["reason"]
    (r,) = run_measures(repo, load_measures(str(f)), "http://127.0.0.1:8080", "")
    assert r["unverified"] is True, "không có file env bí mật mà phép đo cần biến từ đó"


def test_qua_gio_hoac_khong_chay_duoc_thi_ghi_loi_khong_nem(tmp_path):
    f = _cfg(
        tmp_path / "hub",
        [
            {"id": "P", "kind": "perf", "command": ["x"], "timeout_s": 5},
            {"id": "Q", "kind": "other", "command": ["khong-co-lenh-nay-xyz"]},
        ],
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(argv, **kw):
        if argv[0] == "x":
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        return subprocess.run(argv, **kw)

    a, b = run_measures(repo, load_measures(str(f)), "http://h", "", run=run)
    assert a["ok"] is False and "quá 5s" in a["error"]
    assert b["ok"] is False and "không chạy được" in b["error"]


# ---------- nối vào lượt QA hồi quy trên staging (orch/verify.py) ----------


def _staging_deployed(tmp_path, monkeypatch):
    from test_deploy_release_fsm import _fake_deploy
    from test_deploy_release_fsm import _orch as _orch_fsm
    from test_deploy_release_fsm import _repo as _repo_fsm

    fn, _ = _fake_deploy(monkeypatch)
    rt = {"command": "python serve.py", "port": 8080, "health": "/", "dependencies": ["PostgreSQL"]}
    bus, orch = _orch_fsm(tmp_path, _repo_fsm(tmp_path), deploy_fn=fn, runtime=rt)
    orch.run()
    return bus, orch


def _qa(bus) -> dict:
    return [e.payload for e in bus.replay(topic="review-results") if e.payload.get("source") == "qa"][-1]


def test_qa_hoi_quy_mang_bang_chung_do_cua_orchestrator(tmp_path, monkeypatch):
    """Staging deploy ok → trước lượt QA hồi quy, orchestrator chạy mọi phép đo đã khai trên cổng đã map; kết quả vào
    `evidence.measure` của review QA (ghi đè lời khai của model) và audit `measure.run` (gate_brief đọc)."""
    hub = tmp_path / "hub"
    hub.mkdir()
    f = hub / "company-p-staging.measure.json"
    f.write_text(json.dumps({"measures": [{"id": "DD-N4", "kind": "perf", "command": PY_OK}]}), encoding="utf-8")
    f.chmod(0o600)
    monkeypatch.setenv(ENV_SECRETS_DIR, str(hub))
    bus, _ = _staging_deployed(tmp_path, monkeypatch)
    (m,) = _qa(bus)["evidence"]["measure"]
    assert m["id"] == "DD-N4" and m["ok"] is True and m["base_url"] == "http://127.0.0.1:8080"
    assert m["verified_by"] == "orchestrator" and m["sha"], "đo trên đúng sha RC"
    runs = [
        json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "measure.run"
    ]
    assert runs and runs[-1]["release_id"] == "REL-001" and runs[-1]["id"] == "DD-N4" and runs[-1]["ok"] is True


def test_khong_khai_do_thi_qa_khong_co_measure(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_SECRETS_DIR, raising=False)
    bus, _ = _staging_deployed(tmp_path, monkeypatch)
    assert "measure" not in _qa(bus)["evidence"]


def test_khai_hong_hoac_staging_chua_deploy_thi_ban_ghi_unverified(tmp_path, monkeypatch):
    from company.orch.verify import measure_run

    hub = tmp_path / "hub"
    f = _cfg(hub, [{"id": "DD-N4", "kind": "perf", "command": PY_OK}])
    monkeypatch.setenv(ENV_SECRETS_DIR, str(hub))
    bus, orch = _staging_deployed(tmp_path, monkeypatch)
    f.rename(hub / "company-p-staging.measure.json")
    ev = next(e for e in bus.replay(topic="release-events") if e.payload.get("env") == "staging")
    hong = ev.model_copy(update={"payload": {**ev.payload, "evidence": {"deploy": {"ok": False}}}})
    (r,) = measure_run(orch, hong)
    assert r["id"] == "DD-N4" and r["unverified"] is True and "chưa deploy" in r["reason"] and r["sha"]
    (hub / "company-p-staging.measure.json").chmod(0o666)
    (r,) = measure_run(orch, ev)
    assert r["id"] == "?" and r["unverified"] is True and "ghi được" in r["reason"]


def test_khong_co_worktree_tich_hop_thi_khong_do(tmp_path, monkeypatch):
    from company.bus import InMemoryBus
    from company.events import Envelope
    from company.llm import FakeClient
    from company.orch.verify import measure_run
    from company.orchestrator import Orchestrator
    from test_orchestrator import handler

    orch = Orchestrator(InMemoryBus(), FakeClient(handler=handler))
    env = Envelope(topic="release-events", key="REL-9", actor="ops", payload={"release_id": "REL-9", "project_id": "P"})
    assert measure_run(orch, env) is None


# ---------- hồ sơ gate (gate_brief): release và nghiệm thu đọc `measure.run` ----------


def test_ho_so_gate_release_va_nghiem_thu_hien_lan_do_moi_nhat(tmp_path):
    from company import gate_brief as GB
    from test_gate_brief import _scenario

    db, _bus, orch = _scenario(tmp_path, to="release")
    md = GB.render_md(GB.build(GB.load_state(db), "REL-001"))
    assert "## Đo NFR" in md and "chưa đo" in md, "không có lần đo nào thì nói thẳng, không im lặng"
    orch._audit("measure.run", {"release_id": "REL-001", "id": "DD-N4", "kind": "perf", "ok": False, "exit_code": 1,
                                "elapsed_s": 3.0, "sha": "abc1234def", "stdout_tail": "p95_ms=2500", "verified_by": "orchestrator"})
    orch._audit("measure.run", {"release_id": "REL-001", "id": "DD-N4", "kind": "perf", "ok": True, "exit_code": 0,
                                "elapsed_s": 2.0, "sha": "abc1234def", "stdout_tail": "p95_ms=812", "verified_by": "orchestrator"})
    orch._audit("measure.run", {"release_id": "REL-001", "id": "DD-N6", "kind": "a11y", "ok": False, "unverified": True,
                                "reason": "staging chưa deploy ok", "verified_by": "orchestrator"})
    orch._audit("measure.run", {"release_id": "REL-002", "id": "DD-N4", "kind": "perf", "ok": False, "exit_code": 1})
    orch._audit("measure.run", {"release_id": "REL-001", "id": "GIA", "ok": True}, actor="qa")
    b = GB.build(GB.load_state(db), "REL-001")
    ms = {m["id"]: m for m in b["extra"]["measure"]}
    assert set(ms) == {"DD-N4", "DD-N6"}, "chỉ release này, chỉ actor orchestrator"
    assert ms["DD-N4"]["ok"] is True, "lần đo MỚI NHẤT của mỗi phép đo thắng"
    md = GB.render_md(b)
    assert "DD-N4 (perf): ĐẠT" in md and "p95_ms=812" in md and "DD-N6 (a11y): KHÔNG ĐO ĐƯỢC" in md
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    md = GB.render_md(GB.build(GB.load_state(db), "UAT-REL-001"))
    assert "DD-N4 (perf): ĐẠT" in md, "gate nghiệm thu thấy cùng số đo"


# ---------- CLI: đo lại một release đang chạy trên staging ----------


def test_cli_do_lai_release_dang_o_staging(tmp_path, monkeypatch, capsys):
    """RC đã lên staging TRƯỚC khi có file khai (hub thật REL-126): người vận hành chạy `python -m company.measure run
    <REL>`; đường đo là CHÍNH `verify.measure_run` (một chỗ), audit `measure.run` vào bus thật để gate_brief đọc."""
    from company.measure import main

    monkeypatch.delenv(ENV_SECRETS_DIR, raising=False)
    bus, _orch = _staging_deployed(tmp_path, monkeypatch)
    bus.close()
    db, repo = tmp_path / "c.sqlite", tmp_path / "khach"
    assert main(["run", "REL-001", "--repo", str(repo), "--db", str(db)]) == 2, "chưa khai đo: nói rõ, mã 2"
    assert "measure.json" in capsys.readouterr().out
    hub = tmp_path / "hub"
    hub.mkdir()
    f = hub / "company-p-staging.measure.json"
    f.write_text(json.dumps({"measures": [{"id": "DD-N4", "kind": "perf", "command": PY_OK},
                                          {"id": "DD-N6", "kind": "a11y", "command": PY_FAIL}]}), encoding="utf-8")
    f.chmod(0o600)
    monkeypatch.setenv(ENV_SECRETS_DIR, str(hub))
    assert main(["run", "REL-001", "--repo", str(repo), "--db", str(db)]) == 1, "có phép đo KHÔNG ĐẠT → mã 1"
    out = capsys.readouterr().out
    assert "DD-N4 perf ĐẠT" in out and "DD-N6 a11y KHÔNG ĐẠT" in out
    from company.sqlite_bus import SQLiteBus

    acts = [e for e in SQLiteBus(db).replay(topic="audit-log") if e.payload["action"] == "measure.run"]
    assert len(acts) == 2 and all(e.actor == "orchestrator" for e in acts)
    assert main(["run", "REL-404", "--repo", str(repo), "--db", str(db)]) == 2, "release chưa có staging deployed"


def test_chay_bang_python_m(tmp_path, monkeypatch, capsys):
    """`python -m company.measure` đi qua `main()` (runpy để dòng `__main__` thực thi, không cần pragma)."""
    import runpy

    monkeypatch.setattr(sys, "argv", ["measure", "run", "REL-404", "--repo", str(tmp_path), "--db", str(tmp_path / "c.sqlite")])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("company.measure", run_name="__main__")
    assert e.value.code == 2 and "REL-404" in capsys.readouterr().out
