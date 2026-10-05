"""ADR-0029: `status=deployed` ở staging phải kèm bằng chứng máy chạy (`smoke`, `verified_by=orchestrator`).

Đo được 2026-09-06 (QLKH): 4 gate xanh, 389 test pass, 25 release — 0 điểm vào chạy được. `deployed` là lời khai
của release-engineer, `regression-staging` là verdict đọc diff. Test ở đây đo cả hai chiều: sản phẩm chạy → `ok`;
sản phẩm chết / không trả lời → status bị ghi đè thành `failed`; spec không khai `runtime` → `unverified` nói thẳng."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from company.events import Envelope, Task
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.smoke import Runtime, parse_runtime, run_smoke, unverified
from company.sqlite_bus import SQLiteBus
from test_orchestrator import handler

SERVER_OK = "import http.server,sys;http.server.test(http.server.SimpleHTTPRequestHandler,port=int(sys.argv[1]),bind='127.0.0.1')"
SERVER_DIE = "import sys;sys.stderr.write('config thiếu DATABASE_URL\\n');sys.exit(3)"


# ---------- run_smoke: đơn vị ----------

def test_run_smoke_ok_khi_san_pham_tra_loi(tmp_path):
    rt = Runtime((sys.executable, "-c", SERVER_OK, "{port}"), path="/", timeout_s=20)
    r = run_smoke(tmp_path, rt)
    assert r["ok"] is True and r["http_status"] == 200 and r["verified_by"] == "orchestrator"
    assert str(r["port"]) in r["command"][-1], "cổng trống được thế vào `{port}`"
    assert r["exit_code"] is None, "tiến trình bị orchestrator giết sau khi có bằng chứng, không phải tự chết"


def test_run_smoke_ghi_ma_thoat_va_stderr_khi_chet_som(tmp_path):
    rt = Runtime((sys.executable, "-c", SERVER_DIE), timeout_s=10)
    r = run_smoke(tmp_path, rt)
    assert r["ok"] is False and r["exit_code"] == 3 and r["http_status"] is None
    assert "DATABASE_URL" in r.get("stderr_tail", ""), "đuôi stderr là thứ người đọc cần để hiểu vì sao"


def test_run_smoke_het_gio_khi_khong_tra_loi(tmp_path):
    rt = Runtime((sys.executable, "-c", "import time;time.sleep(30)"), timeout_s=2)
    r = run_smoke(tmp_path, rt)
    assert r["ok"] is False and "không trả lời" in r["error"] and r["elapsed_s"] < 10


def test_run_smoke_lenh_khong_ton_tai(tmp_path):
    r = run_smoke(tmp_path, Runtime(("lenh-khong-co-that-xyz",), timeout_s=2))
    assert r["ok"] is False and "error" in r


def test_run_smoke_ma_http_khac_ky_vong_khong_phai_ok(tmp_path):
    rt = Runtime((sys.executable, "-c", SERVER_OK, "{port}"), path="/khong-co-file-nay", timeout_s=20)
    r = run_smoke(tmp_path, rt)
    assert r["http_status"] == 404 and r["ok"] is False


# ---------- parse_runtime ----------


def test_run_smoke_cong_co_dinh_da_bi_chiem_khong_phai_ok(tmp_path):
    """`runtime.port` cố định mà đã có tiến trình khác trả lời trên cổng đó (dev server cũ, release trước chưa tắt):
    lượt poll đầu chạm KẺ CHIẾM CỔNG và ghi `ok=True` cho một sản phẩm chưa hề lên — bằng chứng "chạy cho tôi xem"
    sai mà không ai biết. Đo hai chiều: bỏ kiểm cổng trước `spawn` thì `ok` thành True."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        rt = Runtime((sys.executable, "-c", "import time; time.sleep(30)"), port=port, timeout_s=5)
        r = run_smoke(tmp_path, rt)
    finally:
        srv.shutdown(); srv.server_close()
    assert r["ok"] is False and r["http_status"] is None
    assert "đã có tiến trình khác" in r["error"] and str(port) in r["error"]

def test_parse_runtime_chuoi_hay_danh_sach_deu_duoc():
    a = parse_runtime({"runtime": {"command": "python -m app --port {port}", "health": "health", "port": 0}})
    assert a is not None and a.command == ("python", "-m", "app", "--port", "{port}") and a.path == "/health"
    assert a.argv(8123)[0] == sys.executable and "8123" in a.argv(8123)
    b = parse_runtime({"runtime": {"command": ["npm", "start"], "port": 3000}})
    assert b is not None and b.port == 3000 and b.path == "/"


def test_parse_runtime_thieu_hoac_hong_thi_none():
    assert parse_runtime(None) is None
    assert parse_runtime({}) is None
    assert parse_runtime({"runtime": "python -m app"}) is None
    assert parse_runtime({"runtime": {"command": ""}}) is None
    assert parse_runtime({"runtime": {"command": ["x"], "port": "abc"}}) is None


def test_parse_runtime_lenh_nhay_le_la_hong_khong_phai_crash():
    """`runtime.command` do spec-writer (model) viết: một dấu nháy lẻ làm `shlex.split` ném `ValueError: No closing
    quotation` xuyên qua `spec_runtime_gap` (guard Gate 1), `verify`, `dast`, `gate_brief` — event spec thành lỗi
    agent thay vì lời nhắn "runtime hỏng" gửi lại spec-writer. Đo hai chiều: bỏ `except ValueError` thì đỏ."""
    from company.orch.guards import spec_runtime_gap
    hong = {"runtime": {"command": "python -c 'print(1)", "port": 0}}
    assert parse_runtime(hong) is None
    assert "runtime.command" in (spec_runtime_gap(hong) or "")


def test_unverified_noi_ly_do():
    u = unverified("vì sao")
    assert u["unverified"] is True and u["reason"] == "vì sao" and u["verified_by"] == "orchestrator"


def test_probe_loopback_khong_di_qua_http_proxy(monkeypatch):
    """Audit 2026-09-23: `urlopen` mặc định theo `http_proxy` kể cả cho 127.0.0.1 — máy vận hành có proxy thì
    smoke/deploy probe đi vòng ra proxy và báo sản phẩm "không chạy" dù nó đang trả lời."""
    import http.server
    import threading

    from company.smoke import _probe

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
        def log_message(self, *a): pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k in ("no_proxy", "NO_PROXY"): monkeypatch.delenv(k, raising=False)
    for k in ("http_proxy", "HTTP_PROXY"): monkeypatch.setenv(k, "http://127.0.0.1:9")  # cổng discard: không ai nghe
    try:
        assert _probe(f"http://127.0.0.1:{srv.server_address[1]}/") == 200
    finally:
        srv.shutdown(); srv.server_close()


# ---------- orchestrator: lời khai `deployed` đi qua smoke ----------

def _git(repo: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path, server_src: str) -> Path:
    repo = tmp_path / "khach"; repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (repo / "pyproject.toml").write_text("[project]\nname='app'\nversion='0'\n", encoding="utf-8")
    (repo / "serve.py").write_text(server_src, encoding="utf-8")
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "init")
    return repo


def _orch(tmp_path: Path, repo: Path | None, runtime: dict | None):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler), repo=repo)
    orch.lead.tickets["T1"] = Task(ticket_id="T1", project_id="P", requirement_id="R1", assignee="builder",
                                   title="T1", acceptance=["a"])
    orch.lead.state["T1"] = "approved"
    # ADR-0031: spec ứng dụng chưa khai `runtime` không được mở gate spec — các ca dưới đây đo giai đoạn RELEASE
    # (smoke, QA hồi quy) nên spec nền khai `kind: library` để dừng đúng ở gate spec như trước; ca nào khảo sát
    # `kind` thì tự publish lại spec với kind của nó.
    spec = {"project_id": "P", "status": "approved", "kind": "library",
            "artifacts": {"prd": "prd", "requirements": "req"}}
    if runtime is not None: spec["runtime"] = runtime
    bus.publish(Envelope(topic="approved-specs", key="P", actor="product", payload=spec))
    bus.publish(Envelope(topic="release-candidates", key="REL-001", actor="delivery-lead",
                         payload={"release_id": "REL-001", "project_id": "P", "tickets": ["T1"], "version": "0.1.0",
                                  "notes": "rc"}))
    return bus, orch


def _staging(bus):
    return [e.payload for e in bus.replay(topic="release-events") if e.payload.get("env") == "staging"]


def test_deployed_kem_smoke_ok_khi_san_pham_chay(tmp_path):
    repo = _repo(tmp_path, f"import sys\n{SERVER_OK}\n")
    bus, orch = _orch(tmp_path, repo, {"command": "python serve.py {port}", "health": "/", "timeout_s": 20})
    orch.run()
    st = _staging(bus)
    assert st and st[-1]["status"] == "deployed"
    sm = st[-1]["smoke"]
    assert sm["ok"] is True and sm["http_status"] == 200 and sm["verified_by"] == "orchestrator"
    assert sm["cwd"].endswith("_integration"), "chạy trong worktree tích hợp, không phải repo gốc của khách"
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "release.smoke" in acts and "release.smoke_failed" not in acts
    # lượt production phải THẤY bằng chứng smoke trong evidence (agent không có tool đọc bus)
    assert orch._release_evidence("REL-001")["staging"]["smoke"]["ok"] is True


def test_deployed_bi_ghi_de_failed_khi_san_pham_khong_chay(tmp_path):
    """Chiều đo quan trọng nhất: release-engineer khai `deployed` nhưng máy khởi động không được → `failed`."""
    repo = _repo(tmp_path, SERVER_DIE)
    bus, orch = _orch(tmp_path, repo, {"command": "python serve.py", "port": 0, "timeout_s": 10})
    orch.run()
    st = _staging(bus)
    assert st and st[-1]["status"] == "failed", "bốn gate xanh không được che một sản phẩm không chạy"
    assert st[-1]["smoke"]["exit_code"] == 3
    fails = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "release.smoke_failed"]
    assert fails and fails[0]["ticket_id"] is None and "REL-001" in fails[0]["evidence"]
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "escalation", "RC failed không được nằm im: mở escalation cho người quyết"
    assert g.kind != "release", "không có deployed thật thì QA hồi quy không chạy, Gate 3 không mở"


def test_runtime_deploy_khai_thi_smoke_bo_qua_khong_fail(tmp_path):
    """ADR-0041: `runtime.command` không có cách nào spawn được một app cần cài dependency riêng trước khi
    chạy (đo thật trên QLKH: `python serve.py` chạy bằng venv của chính orchestrator, không có gói của khách,
    exit_code=127/3 bất kể nội dung lệnh) — nhưng khi spec đã khai `runtime.deploy` (ADR-0039/0040), bằng
    chứng thật đến từ `deploy_process.sh`/`compose` chạy NGAY SAU, không phải từ `smoke()` chạy trần.

    Cố ý dùng `SERVER_DIE` (lệnh CHẮC CHẮN fail nếu bị spawn thật) để chứng minh smoke() không hề chạy nó —
    nếu vẫn chạy, status sẽ bị ghi đè `failed` giống `test_deployed_bi_ghi_de_failed_khi_san_pham_khong_chay`.

    Đo hai chiều: bỏ điều kiện `rt.deploy` mới thêm trong `verify.smoke()` → test này đỏ (status thành `failed`,
    `release.smoke_failed` xuất hiện)."""
    repo = _repo(tmp_path, SERVER_DIE)
    bus, orch = _orch(tmp_path, repo, {"command": "python serve.py", "port": 0, "timeout_s": 2,
                                       "deploy": "docker-compose.yml"})
    orch.run()
    st = _staging(bus)
    assert st and st[-1]["status"] == "deployed", "runtime.deploy đã khai — không để smoke trần hạ status"
    sm = st[-1]["smoke"]
    assert sm["unverified"] is True and "runtime.deploy" in sm["reason"]
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "release.smoke_failed" not in acts and "release.smoke_blocked" not in acts
    assert "release.smoke" not in acts, "run_smoke() không được gọi — không có bằng chứng chạy trần nào để ghi"
    g = orch.gate.pending.get("REL-001")
    assert g is None or g.kind != "escalation", (
        "không mở escalation ở bước smoke/regression — pipeline đi tiếp bình thường tới Gate 3 (release)")


def test_smoke_fail_lan_hai_gate_da_pending_khong_mo_gate_trung(tmp_path):
    """verify.py 91->94: RC đã escalate vì smoke fail lần đầu (gate `REL-001` đang pending) → smoke fail LẦN NỮA
    cho cùng release không mở thêm gate escalation, chỉ ghi audit + hạ status."""
    from company.orch import verify

    repo = _repo(tmp_path, SERVER_DIE)
    bus, orch = _orch(tmp_path, repo, {"command": "python serve.py", "port": 0, "timeout_s": 10})
    orch.run()
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "escalation"
    n_truoc = sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.request"
                  and '"subject_id": "REL-001"' in (e.payload.get("evidence") or ""))
    rc = orch.latest("release-candidates", "REL-001")
    integ = orch._integration_of_release(rc)
    out = verify.smoke(orch, "release-engineer", rc, "REL-001", {"status": "deployed"}, integ)
    assert out["status"] == "failed"
    n_sau = sum(1 for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.request"
                and '"subject_id": "REL-001"' in (e.payload.get("evidence") or ""))
    assert n_sau == n_truoc


def test_du_an_legacy_pid_none_thi_false():
    """verify.py 47->exit: không xác định được `project_id` (RC ngoài dự án nào, hoặc gọi trực tiếp không có
    `project_for`) → không thể tự khai `legacy`, coi như không legacy."""
    from company.bus import InMemoryBus
    from company.orch.verify import _du_an_legacy
    from company.orchestrator import Orchestrator

    orch = Orchestrator(InMemoryBus(), FakeClient(handler=handler))
    assert _du_an_legacy(orch, None) is False


def test_khong_khai_runtime_thi_unverified_khong_chan(tmp_path):
    repo = _repo(tmp_path, SERVER_DIE)
    bus, orch = _orch(tmp_path, repo, None)
    orch.run()
    st = _staging(bus)
    assert st[-1]["status"] == "deployed" and st[-1]["smoke"]["unverified"] is True
    assert "runtime" in st[-1]["smoke"]["reason"]
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert acts.count("release.smoke_unverified") == 1


def _spec_ung_dung(bus, **them):
    """Publish đè spec `kind=application` KHÔNG có `runtime` — trạng thái mà ADR-0031 chặn ở gate spec, nhưng
    dự án duyệt trước ADR-0031 vẫn mang tới giai đoạn release. Đây là ca K1.5 phải xử."""
    bus.publish(Envelope(topic="approved-specs", key="P", actor="product",
                         payload={"project_id": "P", "status": "approved", "kind": "application",
                                  "artifacts": {"prd": "prd", "requirements": "req"}, **them}))


def test_k15_ung_dung_khong_smoke_duoc_thi_khong_len_deployed(tmp_path):
    """K1.5 — `unverified` KHÔNG phải trạng thái trung lập với sản phẩm phải-chạy-được. Trước bản sửa, spec
    `kind=application` thiếu `runtime` vẫn cho RC lên `deployed` với một dòng "chưa kiểm" trong bằng chứng: đúng
    hình dạng của QLKH (2026-09-06 — 25 release, 4 gate xanh, 0 điểm vào). Nay nó đi ĐÚNG đường smoke fail.

    Đo hai chiều: bỏ nhánh `kind != "application"` trong `_chua_kiem` (luôn `return {**p, "smoke": smoke}`) →
    `status` trở lại `deployed` và không có gate nào mở, test ĐỎ ở cả ba assert dưới."""
    repo = _repo(tmp_path, SERVER_DIE)
    bus, orch = _orch(tmp_path, repo, None)
    _spec_ung_dung(bus)
    orch.run()
    st = _staging(bus)
    assert st[-1]["status"] == "failed", "sản phẩm phải chạy được mà không kiểm được thì không được lên deployed"
    assert st[-1]["smoke"]["unverified"] is True and "runtime" in st[-1]["smoke"]["reason"]
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "escalation", "RC failed không được nằm im — mở escalation cho người quyết"
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "release.smoke_blocked" in acts, "phải ghi rõ vì sao chặn, không chỉ đổi status"


def test_k15_co_co_legacy_thi_van_di_tiep(tmp_path):
    """Chiều còn lại: dự án khai `legacy: true` (có trước ADR-0031, không đòi được `runtime`) vẫn đi tiếp —
    nếu không thì bản sửa này chặn đứng mọi dự án cũ đang chạy. Bằng chứng vẫn nói thẳng là chưa kiểm."""
    repo = _repo(tmp_path, SERVER_DIE)
    bus, orch = _orch(tmp_path, repo, None)
    _spec_ung_dung(bus)
    bus.publish(Envelope(topic="research-requests", key="P", actor="human:chu-du-an",
                         payload={"project_id": "P", "description": "dự án cũ", "legacy": True}))
    orch.run()
    st = _staging(bus)
    assert st[-1]["status"] == "deployed", "dự án legacy vẫn đi tiếp"
    assert st[-1]["smoke"]["unverified"] is True, "…nhưng bằng chứng không được nói dối là đã kiểm"
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "release.smoke_blocked" not in acts


def test_khong_co_repo_thi_unverified_noi_ro_ly_do(tmp_path):
    bus, orch = _orch(tmp_path, None, {"command": "python serve.py"})
    orch.run()
    st = _staging(bus)
    assert st[-1]["status"] == "deployed" and st[-1]["smoke"]["unverified"] is True
    assert "worktree" in st[-1]["smoke"]["reason"]


def test_run_smoke_communicate_qua_gio_khong_lam_hong_bang_chung(tmp_path, monkeypatch):
    """Tiến trình bị kill mà `communicate` vẫn treo (pipe stderr bị con giữ) → bỏ qua stderr, bằng chứng còn lại giữ nguyên."""
    import subprocess as sp

    from company.sandbox import SubprocessSandbox

    class Proc:
        returncode = 7
        def poll(self): return 7
        def kill(self): raise AssertionError("đã chết thì không kill")
        def communicate(self, timeout=None): raise sp.TimeoutExpired(cmd="x", timeout=timeout)

    # K2.4: `Popen` không còn nằm trong `smoke.py` mà trong `SubprocessSandbox` — tiêm qua đúng seam đó thay vì
    # monkeypatch module. Nhờ vậy test đi qua CẢ `_ProcHandle` (nơi `communicate` treo được nuốt), không chỉ qua
    # vòng lặp poll của `run_smoke`.
    r = run_smoke(tmp_path, Runtime(("x",), timeout_s=2),
                  sandbox=SubprocessSandbox(popen=lambda *a, **k: Proc()))
    assert r["ok"] is False and r["exit_code"] == 7 and "stderr_tail" not in r


# ---------- ADR-0029 mở rộng (B3): `regression-staging` mang `evidence.run` do orchestrator tự chạy ----------

def _qa_reviews(bus):
    return [e.payload for e in bus.replay(topic="review-results") if e.payload.get("source") == "qa"]


def _acts(bus):
    return [e.payload["action"] for e in bus.replay(topic="audit-log")]


def _fake_smoke(monkeypatch, results):
    """Runtime giả: `run_smoke` của `company.orch.verify` (K1: tách khỏi orchestrator.py, ADR-0034) trả lần lượt
    từng kết quả (lượt deployed rồi lượt QA hồi quy)."""
    from company.orch import verify as ov
    calls: list[Path] = []
    def fake(root, rt, sandbox=None):   # `sandbox=` từ K2.4: verify truyền sandbox của tiến trình xuống
        calls.append(root)
        return dict(results[min(len(calls), len(results)) - 1])
    monkeypatch.setattr(ov, "run_smoke", fake)
    return calls


OK = {"verified_by": "orchestrator", "command": ["python", "serve.py", "8123"], "port": 8123, "url": "http://127.0.0.1:8123/",
      "ok": True, "http_status": 200, "exit_code": None, "elapsed_s": 0.5}
BAD = {**OK, "ok": False, "http_status": 500, "elapsed_s": 0.7}


def test_regression_staging_giu_pass_va_mang_evidence_run_khi_smoke_200(tmp_path, monkeypatch):
    repo = _repo(tmp_path, SERVER_DIE)
    calls = _fake_smoke(monkeypatch, [OK, OK])
    bus, orch = _orch(tmp_path, repo, {"command": "python serve.py {port}", "timeout_s": 5})
    orch.run()
    qa = _qa_reviews(bus)
    assert qa and qa[-1]["verdict"] == "pass"
    run = qa[-1]["evidence"]["run"]
    assert run["ok"] is True and run["http_status"] == 200 and run["verified_by"] == "orchestrator"
    assert run["command"] == OK["command"] and run["sha"], "lệnh thật và sha RC: người ký Gate 3 biết CÁI GÌ đã chạy"
    assert len(calls) == 2 and str(calls[0]).endswith("_integration"), "một lần cho deployed (worktree tích hợp)..."
    assert calls[1].name == run["sha"], "...một lần cho QA — ở checkout ĐÚNG sha đã staged, không ở đầu nhánh (audit 2026-09-23)"
    acts = _acts(bus)
    assert "regression.run" in acts and "regression.run_failed" not in acts and "regression.verdict_overridden" not in acts
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "release", "smoke ok + QA pass → Gate 3 mở như thường"


def test_regression_staging_pass_ma_smoke_fail_thi_ha_fail_rc_khong_di_tiep(tmp_path, monkeypatch):
    """Chiều đo quan trọng nhất: deployed qua smoke, nhưng ở lượt QA sản phẩm không trả lời đúng → verdict pass của
    model bị hạ `fail`, escalation mở cho RC, Gate 3 KHÔNG mở."""
    repo = _repo(tmp_path, SERVER_DIE)
    _fake_smoke(monkeypatch, [OK, BAD])
    bus, orch = _orch(tmp_path, repo, {"command": "python serve.py {port}", "timeout_s": 5})
    orch.run()
    qa = _qa_reviews(bus)
    assert qa and qa[-1]["verdict"] == "fail", "verdict không có bằng chứng chạy đạt thì không được là pass"
    assert qa[-1]["evidence"]["run"]["http_status"] == 500
    assert any(f["level"] == "block" and "http_status=500" in f["text"] for f in qa[-1]["findings"])
    assert "http_status=500" in qa[-1]["root_cause"]
    acts = _acts(bus)
    assert "regression.run_failed" in acts and "regression.verdict_overridden" in acts
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "escalation", "RC fail không nằm im: escalation cho người quyết"


def test_khong_runtime_kind_application_legacy_thi_qa_hoi_quy_van_chan(tmp_path, monkeypatch):
    """Dự án `legacy: true` (K1.5) là đường DUY NHẤT còn lại để một spec `kind=application` thiếu `runtime` đi
    qua được smoke. Nó phải vẫn bị chặn ở chặng sau — QA hồi quy hạ `fail` rồi mở escalation (ADR-0029 mục 3).

    Trước K1.5 ca này KHÔNG cần cờ `legacy`: mọi dự án đều qua smoke rồi mới bị QA chặn. Nay dự án không khai
    `legacy` bị chặn sớm hơn một chặng, đo ở `test_k15_ung_dung_khong_smoke_duoc_thi_khong_len_deployed` — chặn
    sớm hơn vì `waive_release_findings` (người duyệt escalation) waive MỌI nguồn chưa pass, kể cả `qa`, nên
    "chưa bao giờ kiểm sản phẩm có chạy không" bị waive chung với finding compliance không có code để sửa."""
    repo = _repo(tmp_path, SERVER_DIE)
    calls = _fake_smoke(monkeypatch, [OK])
    bus, orch = _orch(tmp_path, repo, None)
    spec = bus.latest("approved-specs", "P").payload
    bus.publish(Envelope(topic="approved-specs", key="P", actor="product", payload={**spec, "kind": "application"}))
    bus.publish(Envelope(topic="research-requests", key="P", actor="human:chu-du-an",
                         payload={"project_id": "P", "description": "dự án có trước ADR-0031", "legacy": True}))
    orch.run()
    assert calls == [], "không có runtime thì không có gì để chạy — không đoán lệnh"
    st = _staging(bus)
    assert st[-1]["status"] == "deployed" and st[-1]["smoke"]["unverified"] is True, "deployed giữ nguyên như ADR-0029 mục 3"
    qa = _qa_reviews(bus)
    run = qa[-1]["evidence"]["run"]
    assert run["unverified"] is True and "runtime" in run["reason"] and run["spec_kind"] == "application"
    assert qa[-1]["verdict"] == "fail" and "kind=application" in qa[-1]["root_cause"]
    acts = _acts(bus)
    assert "regression.run_unverified" in acts and "regression.verdict_overridden" in acts
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "escalation" and g.kind != "release"


def test_khong_runtime_kind_library_hay_docs_thi_unverified_khong_chan(tmp_path, monkeypatch):
    """`library`/`docs` không có server: smoke `unverified` nhưng KHÔNG chặn RC.

    Trước ADR-0031 ca này còn nhánh "spec chưa khai kind" — nay thiếu `kind` = `application` (im lặng không phải
    miễn trừ) nên spec đó bị chặn ngay ở Gate 1, không bao giờ tới được RC; nhánh ấy đo ở
    `tests/test_gate_spec_runtime.py`."""
    for kind in ("library", "docs"):
        d = tmp_path / kind; d.mkdir()
        repo = _repo(d, SERVER_DIE)
        _fake_smoke(monkeypatch, [OK])
        bus, orch = _orch(d, repo, None)
        spec = bus.latest("approved-specs", "P").payload
        bus.publish(Envelope(topic="approved-specs", key="P", actor="product", payload={**spec, "kind": kind}))
        orch.run()
        qa = _qa_reviews(bus)
        assert qa[-1]["verdict"] == "pass" and qa[-1]["evidence"]["run"]["unverified"] is True
        assert qa[-1]["evidence"]["run"]["spec_kind"] == kind
        assert "regression.run_unverified" in _acts(bus) and "regression.verdict_overridden" not in _acts(bus)
        g = orch.gate.pending.get("REL-001")
        assert g is not None and g.kind == "release", f"kind={kind}: không chặn cứng, nhưng bằng chứng nói 'chưa kiểm'"


def test_qa_thay_evidence_run_trong_input_va_loi_khai_cua_no_bi_bo(tmp_path, monkeypatch):
    """Prompt qa-debugger v13 nói 'kết quả ở payload.evidence.run' — input phải THẬT SỰ mang nó; và mọi
    `evidence.run` model tự khai bị thay bằng bản của orchestrator (một nguồn bằng chứng duy nhất)."""
    from test_orchestrator import _agent_of, _inp
    seen: list[dict] = []
    def h(system, user):
        out = handler(system, user)
        if _agent_of(system) == "qa":
            seen.append(_inp(user))
            out = {**out, "evidence": {"run": {"ok": True, "http_status": 200, "verified_by": "qa"}, "note": "giữ"}}
        return out
    repo = _repo(tmp_path, SERVER_DIE)
    _fake_smoke(monkeypatch, [OK, BAD])
    bus, orch = _orch(tmp_path, repo, {"command": "python serve.py {port}"})
    orch.runner.client = FakeClient(handler=h)
    orch.run()
    assert seen and seen[-1]["evidence"]["run"]["http_status"] == 500, "QA nhìn thấy đúng kết quả máy vừa chạy"
    qa = _qa_reviews(bus)
    assert qa[-1]["evidence"]["run"]["verified_by"] == "orchestrator" and qa[-1]["evidence"]["note"] == "giữ"
    assert qa[-1]["verdict"] == "fail" and "regression.run_claimed_ignored" in _acts(bus)


def test_evidence_run_song_qua_restart_va_redeploy_khong_bi_once_nuot(tmp_path, monkeypatch):
    """TRAPS §1 khuôn 2/3: bằng chứng ở trên bus (không RAM) — mở lại bus vẫn đọc được; RC redeploy là lượt deployed
    THỨ HAI hợp lệ → `regression.run_unverified` phải ghi lần nữa (khoá once mang event_id)."""
    repo = _repo(tmp_path, SERVER_DIE)
    _fake_smoke(monkeypatch, [OK])
    bus, orch = _orch(tmp_path, repo, None)
    orch.run()
    assert _acts(bus).count("regression.run_unverified") == 1
    bus2 = SQLiteBus(tmp_path / "c.sqlite")
    orch2 = Orchestrator(bus2, FakeClient(handler=handler), repo=repo)
    qa = [e.payload for e in bus2.replay(topic="review-results") if e.payload.get("source") == "qa"]
    assert qa[-1]["evidence"]["run"]["unverified"] is True
    assert orch2.lead.release_qa["REL-001"].verdict == "pass"
    assert "regression.unverified:REL-001:" in " ".join(orch2.once), "khoá once dựng lại từ audit-log"
    bus2.publish(Envelope(topic="release-events", key="REL-001", actor="ops",
                          payload={"release_id": "REL-001", "env": "staging", "status": "deployed", "version": "0.1.0"}))
    orch2.run()
    assert _acts(bus2).count("regression.run_unverified") == 2, "lượt deployed thứ hai không bị khoá của lượt một nuốt"


def test_verdict_with_run_giu_fail_cua_model_va_khong_nhan_doi_finding(tmp_path):
    """Model đã fail (tự thấy lỗi) và smoke cũng fail → giữ fail, không ghi `verdict_overridden`."""
    bus, orch = _orch(tmp_path, None, None)
    env = Envelope(topic="release-events", key="REL-001", actor="ops",
                   payload={"release_id": "REL-001", "env": "staging", "status": "deployed"})
    p = orch._verdict_with_run("qa", env, {"ticket_id": "REL-001", "source": "qa", "verdict": "fail",
                                                    "root_cause": "của model", "findings": []}, BAD)
    assert p["verdict"] == "fail" and p["root_cause"] == "của model" and p["findings"] == []
    assert p["evidence"]["run"] == BAD
    assert "regression.verdict_overridden" not in _acts(bus) and "regression.run_failed" in _acts(bus)


def test_khong_co_worktree_thi_regression_run_unverified_noi_ro(tmp_path):
    bus, orch = _orch(tmp_path, None, {"command": "python serve.py"})
    orch.run()
    qa = _qa_reviews(bus)
    assert qa[-1]["evidence"]["run"]["unverified"] is True and "worktree" in qa[-1]["evidence"]["run"]["reason"]


def test_gate_brief_release_hien_evidence_run(tmp_path, monkeypatch):
    from company.gate_brief import _run_summary, build, render_md
    assert _run_summary({"evidence": {"run": {"unverified": True, "reason": "x"}}}) == "unverified — x"
    assert _run_summary({"evidence": {"run": OK}}) == "ok=True http=200 exit=None (orchestrator)"
    assert _run_summary({"evidence": {"run": "lạ"}}) is None and _run_summary({}) is None
    repo = _repo(tmp_path, SERVER_DIE)
    _fake_smoke(monkeypatch, [OK, OK])
    _, orch = _orch(tmp_path, repo, {"command": "python serve.py {port}"})
    orch.run()
    b = build(orch, "REL-001")
    assert b["extra"]["staging_reviews"][0]["run"].startswith("ok=True http=200")
    assert "chạy: ok=True http=200" in render_md(b)


def _capture_smoke_spec(tmp_path, mode, command):
    class Done:
        def poll(self): return 0
        def stderr_tail(self, limit): return ''
    class Capture:
        name = mode
        def spawn(self, spec):
            self.spec = spec
            return Done()
    sb = Capture()
    result = run_smoke(tmp_path, Runtime(command), sandbox=sb)
    return sb.spec, result


def test_s2_smoke_waitress_container_bind_nhan_relay(tmp_path):
    spec, result = _capture_smoke_spec(tmp_path, 'container:img',
                                      ('uv', 'run', 'waitress-serve', '--listen=127.0.0.1:{port}', 'campus.wsgi:application'))
    assert any(a.startswith('--listen=0.0.0.0:') for a in spec.argv)
    assert result['command'] == spec.argv


def test_s2_smoke_uv_container_cap_allowlist_pypi(tmp_path):
    spec, _ = _capture_smoke_spec(tmp_path, 'container:img', ('uv', 'run', 'waitress-serve'))
    assert spec.allowed_domains == ('pypi.org', 'files.pythonhosted.org')


def test_s2_smoke_subprocess_giu_bind_host_va_khong_khai_enforcement(tmp_path):
    spec, _ = _capture_smoke_spec(tmp_path, 'subprocess',
                                 ('uv', 'run', 'waitress-serve', '--listen=127.0.0.1:{port}', 'campus.wsgi:application'))
    assert any(a.startswith('--listen=127.0.0.1:') for a in spec.argv)
    assert spec.allowed_domains == ()
