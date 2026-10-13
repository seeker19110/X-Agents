"""ADR-0039 D1b: orchestrator TỰ kết luận `deployed` — `release-events.status` là kết luận của code, không phải
`payload` của model.

D1a (`tests/test_deploy_compose.py`) đo module `deploy()` đứng một mình. Ở đây đo chỗ NỐI: lượt deploy của `ops`
trên `STAGING_ROUTE`/`PROD_ROUTE` đi qua `verify.deploy_release`, và ba kết cục của nó rơi đúng chỗ trên bus —
`deployed` kèm `evidence.deploy` có container id, `deploy_failed` kèm phần nào hỏng + gate escalation, `skipped`
giữ nguyên hành vi cũ để repo đang chạy không gãy.

Máy chạy test và `windows-latest` của CI đều không có docker daemon: runner compose được tiêm qua
`Orchestrator(deploy_fn=partial(deploy, run=…, which=…))`, đúng khuôn D1a.

Đo hai chiều (AGENTS.md luật 4):
- bỏ vế `ps` khỏi điều kiện `deployed` của `deploy()` → `test_container_exited_ngay_sau_up_thi_deploy_failed` đỏ;
- bỏ vế smoke → `test_container_up_nhung_health_500_thi_deploy_failed` đỏ;
- lấy `deployed` từ `payload` của model (bỏ lời gọi `_deploy_release` trong `release_fsm._release`) →
  `test_model_khai_deployed_nhung_container_khong_chay` đỏ — ca quan trọng nhất của PR này.
"""
from __future__ import annotations

import json
import subprocess
from functools import partial
from pathlib import Path

from company.deploy import ENV_MODE, deploy
from company.events import Envelope, Task
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import handler

SERVER_OK = "import http.server,sys;http.server.test(http.server.SimpleHTTPRequestHandler,port=int(sys.argv[1]),bind='127.0.0.1')"
PS_OK = json.dumps([{"Service": "web", "ID": "abcdef0123456789", "State": "running",
                     "Publishers": [{"PublishedPort": 8080, "TargetPort": 80}]}])
PS_EXITED = json.dumps([{"Service": "web", "ID": "abcdef0123456789", "State": "exited",
                         "Publishers": [{"PublishedPort": 8080}]}])
RUNTIME = {"command": "python serve.py {port}", "health": "/", "timeout_s": 20}


class FakeCompose:
    """Runner compose giả (như D1a): ghi lại argv, trả kết quả dựng sẵn theo lệnh con. Không chạy container nào."""

    def __init__(self, **rc: tuple[int, str, str]):
        self.calls: list[list[str]] = []
        self._rc = {"up": (0, "", ""), "ps": (0, PS_OK, ""), "logs": (0, "web-1 | Traceback: cong 8080 ban", ""),
                    "down": (0, "", "")} | rc

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        code, out, err = self._rc[argv[6]]
        return subprocess.CompletedProcess(argv, code, out, err)

    @property
    def subs(self) -> list[str]:
        return [c[6] for c in self.calls]

    @property
    def projects(self) -> list[str]:
        return [c[3] for c in self.calls]


def _git(repo: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path, *, compose: bool = True) -> Path:
    repo = tmp_path / "khach"; repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (repo / "pyproject.toml").write_text("[project]\nname='app'\nversion='0'\n", encoding="utf-8")
    (repo / "serve.py").write_text(f"import sys\n{SERVER_OK}\n", encoding="utf-8")
    if compose:
        (repo / "compose.yaml").write_text("services:\n  web:\n    image: app\n", encoding="utf-8")
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "init")
    return repo


def _orch(tmp_path: Path, repo: Path | None, *, deploy_fn=None, runtime: dict | None = None):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler), repo=repo, deploy_fn=deploy_fn)
    orch.lead.tickets["T1"] = Task(ticket_id="T1", project_id="P", requirement_id="R1", assignee="builder",
                                   title="T1", acceptance=["a"])
    orch.lead.state["T1"] = "approved"
    spec = {"project_id": "P", "status": "approved", "kind": "library",
            "artifacts": {"prd": "prd", "requirements": "req"}}
    if runtime is not None: spec["runtime"] = runtime
    bus.publish(Envelope(topic="approved-specs", key="P", actor="product", payload=spec))
    bus.publish(Envelope(topic="release-candidates", key="REL-001", actor="delivery-lead",
                         payload={"release_id": "REL-001", "project_id": "P", "tickets": ["T1"], "version": "0.1.0",
                                  "notes": "rc"}))
    return bus, orch


def _fake_deploy(monkeypatch, *, probe: int | None = 200, binary: str | None = "/usr/bin/docker", **rc):
    """`deploy()` thật với runner + `which` + probe tiêm vào — logic kết luận là của D1a, chỉ docker là giả."""
    import company.deploy as D
    monkeypatch.setattr(D, "http_probe", lambda url: probe)
    fake = FakeCompose(**rc)
    return partial(deploy, mode="auto", run=fake, which=lambda b: binary), fake


def _rel(bus, env_name: str) -> list[dict]:
    return [e.payload for e in bus.replay(topic="release-events") if e.payload.get("env") == env_name]


def _acts(bus) -> list[str]:
    return [e.payload["action"] for e in bus.replay(topic="audit-log")]


# ---------- đủ ba phần → `deployed` ----------

def test_deployed_la_container_dang_chay_kem_bang_chung(tmp_path, monkeypatch):
    fn, fake = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    st = _rel(bus, "staging")[-1]
    assert st["status"] == "deployed"
    d = st["evidence"]["deploy"]
    assert d["ok"] is True and d["verified_by"] == "orchestrator", "bằng chứng máy sinh, không phải lời khai"
    assert d["project"] == "company-p-staging" and d["env"] == "staging"
    assert d["services"] == ["web"] and d["container_ids"] == ["abcdef012345"] and d["port"] == 8080
    assert d["started_at"] and d["smoke"]["http_status"] == 200 and d["compose_file"] == "compose.yaml"
    assert fake.subs == ["up", "ps"], "deploy xong KHÔNG `down`: sản phẩm phải còn sống sau lượt"
    assert "release.deploy" in _acts(bus) and "release.deploy_failed" not in _acts(bus)
    assert orch.lead.state["T1"] == "merged", "staging deployed thật → ticket đi tiếp như cũ"


# ---------- thiếu một phần → `deploy_failed` ----------

def test_model_khai_deployed_nhung_container_khong_chay(tmp_path, monkeypatch):
    """Ca quan trọng nhất của PR: agent `ops` trả `status=deployed` (handler giả luôn trả thế), nhưng `compose ps`
    cho service `exited`. Nếu `deployed` được lấy từ `payload` của model thì event trên bus nói "đã deploy" trong
    khi không có tiến trình nào sống — đúng hình dạng QLKH 2026-09-06 (25 release, 0 điểm vào).

    Đo hai chiều: bỏ lời gọi `_deploy_release` trong `release_fsm._release` → `status` trở lại `deployed`, không có
    `evidence.deploy`, không gate nào mở; cả bốn assert dưới đỏ."""
    fn, fake = _fake_deploy(monkeypatch, ps=(0, PS_EXITED, ""))
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    st = _rel(bus, "staging")[-1]
    assert st["status"] == "deploy_failed", "lời khai `deployed` không tự nó thành sự thật"
    d = st["evidence"]["deploy"]
    assert d["ok"] is False and "web=exited" in d["error"] and "cong 8080 ban" in d["logs_tail"]
    assert "down" in fake.subs, "`deploy()` đã tự dọn — orchestrator KHÔNG gọi `down` lần hai"
    assert fake.subs.count("down") == 1
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "escalation", "RC không đi tiếp được thì phải có người được hỏi"
    assert not _rel(bus, "production"), "không deployed thì QA hồi quy không chạy, Gate 3 không mở"
    assert "release.deploy_failed" in _acts(bus)


def test_deploy_failed_lan_hai_gate_da_pending_khong_mo_gate_trung(tmp_path, monkeypatch):
    """verify.py 100->exit (`_escalate`): RC đã escalate vì deploy_failed lần đầu → deploy_failed LẦN NỮA cho
    cùng release không mở thêm gate escalation."""
    from company.orch import verify

    fn, _fake = _fake_deploy(monkeypatch, ps=(0, PS_EXITED, ""))
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    g = orch.gate.pending.get("REL-001")
    assert g is not None and g.kind == "escalation"
    n_truoc = sum(1 for e in _acts(bus) if e == "gate.request")
    rc = orch.latest("release-candidates", "REL-001")
    integ = orch._integration_of_release(rc)
    out = verify.deploy_release(orch, "ops", rc, "REL-001", {"status": "deployed"}, integ, "staging")
    assert out["status"] == "deploy_failed"
    n_sau = sum(1 for e in _acts(bus) if e == "gate.request")
    assert n_sau == n_truoc


def test_deploy_failed_khong_tra_ticket_ve_lam_lai(tmp_path, monkeypatch):
    """`deploy_failed` KHÁC `failed`: chưa dựng được môi trường chạy (thường là hạ tầng máy trực) không phải bằng
    chứng code hỏng, nên ticket nằm yên chờ người quyết ở gate escalation thay vì rơi về `changes_requested`."""
    fn, _ = _fake_deploy(monkeypatch, ps=(0, PS_EXITED, ""))
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    assert _rel(bus, "staging")[-1]["status"] == "deploy_failed"
    assert orch.lead.state["T1"] == "approved", "không lên `merged` (chưa deploy), cũng không về `changes_requested`"
    assert orch.lead.tickets["T1"].retry == 0, "không đốt lượt retry của ticket vì một cổng bận trên máy trực"


def test_container_exited_ngay_sau_up_thi_deploy_failed(tmp_path, monkeypatch):
    """Đo hai chiều vế `ps`: bỏ kiểm `compose ps` (chỉ tin `up -d` thoát 0) thì ca này đỏ — `up -d` thoát 0 ở đây."""
    fn, fake = _fake_deploy(monkeypatch, up=(0, "", ""), ps=(0, PS_EXITED, ""))
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    st = _rel(bus, "staging")[-1]
    assert fake.calls[0][6:] == ["up", "-d", "--build"] and st["status"] == "deploy_failed"
    assert "exited" in st["evidence"]["deploy"]["error"]


def test_container_up_nhung_health_500_thi_deploy_failed(tmp_path, monkeypatch):
    """Đo hai chiều vế smoke: mọi service `running` nhưng cổng đã map trả 500 → vẫn KHÔNG phải `deployed`."""
    fn, _ = _fake_deploy(monkeypatch, probe=500)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    st = _rel(bus, "staging")[-1]
    assert st["status"] == "deploy_failed" and "smoke" in st["evidence"]["deploy"]["error"]
    assert st["evidence"]["deploy"]["smoke"]["http_status"] == 500


def test_thieu_binary_khi_khai_dich_danh_thi_deploy_failed_khong_giet_orchestrator(tmp_path, monkeypatch):
    """`COMPANY_DEPLOY=compose` là lời khai đích danh của người vận hành: thiếu binary là LỖI (fail-closed,
    ADR-0039 quyết định 4) — nhưng lỗi đó thành `deploy_failed` có bằng chứng, không phải một traceback làm chết
    vòng lặp orchestrator."""
    monkeypatch.setenv(ENV_MODE, "compose")
    import company.deploy as D
    monkeypatch.setattr(D, "http_probe", lambda url: 200)
    fn = partial(deploy, run=FakeCompose(), which=lambda b: None)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    st = _rel(bus, "staging")[-1]
    assert st["status"] == "deploy_failed"
    assert "compose" in st["evidence"]["deploy"]["error"] and st["evidence"]["deploy"]["ok"] is False
    assert orch.gate.pending["REL-001"].kind == "escalation"


# ---------- `skipped`: đường lùi, giữ nguyên hành vi cũ ----------

def test_khong_co_compose_file_thi_skipped_va_giu_hanh_vi_cu(tmp_path, monkeypatch):
    fn, fake = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path, compose=False), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    st = _rel(bus, "staging")[-1]
    assert st["status"] == "deployed", "chưa có compose file thì repo đang chạy không được gãy"
    assert "compose.yaml" in st["evidence"]["deploy"]["skipped"] and st["evidence"]["deploy"]["ok"] is False
    assert fake.calls == [], "không dò ra compose thì không chạy lệnh docker nào"
    assert "release.deploy_skipped" in _acts(bus)


def test_khong_khai_runtime_thi_skipped_noi_ly_do(tmp_path, monkeypatch):
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=None)
    orch.run()
    st = _rel(bus, "staging")[-1]
    assert st["status"] == "deployed" and "runtime" in st["evidence"]["deploy"]["skipped"]
    assert _acts(bus).count("release.deploy_skipped") == 1, "`once` theo event: một dòng, không rải log"


def test_khong_co_repo_thi_skipped_noi_ro_worktree(tmp_path, monkeypatch):
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, None, deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    st = _rel(bus, "staging")[-1]
    assert st["status"] == "deployed" and "worktree" in st["evidence"]["deploy"]["skipped"]


def test_mac_dinh_khong_tiem_gi_thi_dung_deploy_that(tmp_path):
    """Không truyền `deploy_fn` → orchestrator dùng `company.deploy.deploy` thật, và nó tự đọc `COMPANY_DEPLOY`."""
    _bus, orch = _orch(tmp_path, None, runtime=RUNTIME)
    assert orch.deploy_fn is deploy


# ---------- production: vẫn CHỈ qua PROD_ROUTE ----------

def test_production_deploy_that_va_khong_them_cong_nao(tmp_path, monkeypatch):
    """ADR-0039 quyết định 5: production không có cổng mới — vẫn là `PROD_ROUTE` sau khi người ký gate release.
    Lượt đó nay dựng compose project RIÊNG (`company-p-production`), không giẫm lên staging."""
    fn, fake = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    assert not _rel(bus, "production"), "chưa ký gate release thì chưa có lượt production nào"
    orch.gate.decide("REL-001", "approve", by="human:release-manager", reason="staging xanh — deploy production")
    orch.run()
    prod = _rel(bus, "production")[-1]
    assert prod["status"] == "deployed" and prod["evidence"]["deploy"]["project"] == "company-p-production"
    assert "company-p-staging" in fake.projects and "company-p-production" in fake.projects
    assert orch.lead.state["T1"] == "released"


def test_production_deploy_failed_thi_khong_giao_hang(tmp_path, monkeypatch):
    """Người đã ký Gate 3, nhưng container production không lên → KHÔNG tag, KHÔNG push, KHÔNG mở gate nghiệm thu:
    khách chỉ được mời ký trên thứ đang chạy."""
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    orch.gate.decide("REL-001", "approve", by="human:release-manager", reason="staging xanh — deploy production")
    fn2, _ = _fake_deploy(monkeypatch, ps=(0, PS_EXITED, ""))
    orch.deploy_fn = fn2
    orch.run()
    prod = _rel(bus, "production")[-1]
    assert prod["status"] == "deploy_failed"
    assert orch.delivered == {}, "chưa chạy được thì chưa giao hàng"
    assert orch.lead.state["T1"] == "merged", "không lên `released`"


# ---------- đúng sha đã staged (audit 2026-09-23) ----------

def _merge_sau_staging(orch) -> str:
    """Ticket khác approved SAU khi RC đã staged: `integrate_approved` merge nó ngay vào nhánh tích hợp, nên đầu
    nhánh chạy trước `release_sha[rid]`. Trả về sha đã staged."""
    integ = orch.integration
    (integ.path / "chua_ky.py").write_text("X = 1\n", encoding="utf-8")
    _git(integ.path, "add", "-A"); _git(integ.path, "commit", "-q", "-m", "merge(T9): chua qua staging")
    staged = orch.release_sha["REL-001"]
    assert integ.rev(integ.branch) != staged
    return staged


def test_production_deploy_dung_sha_da_staged_khong_phai_dau_nhanh_tich_hop(tmp_path, monkeypatch):
    """Audit 2026-09-23: production deploy chạy trong `_integration` (đầu nhánh) chứ không ở `release_sha[rid]` —
    ticket approved sau staging lên production mà chưa qua staging/QA/Gate 3; tag thì lại ở sha staged."""
    fn, _ = _fake_deploy(monkeypatch)
    roots: list[Path] = []
    def ghi(root, *a, **k):
        roots.append(Path(root)); return fn(root, *a, **k)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=ghi, runtime=RUNTIME)
    orch.run()
    staged = _merge_sau_staging(orch)
    orch.gate.decide("REL-001", "approve", by="human:release-manager", reason="staging xanh — deploy production")
    orch.run()
    assert _rel(bus, "production")[-1]["status"] == "deployed"
    prod_root = roots[-1]
    assert _git(prod_root, "rev-parse", "HEAD") == staged, "production chạy đúng sha đã staged"
    assert not (prod_root / "chua_ky.py").exists(), "code chưa qua staging không được lên production"


def test_hoi_quy_qa_chay_dung_sha_da_staged(tmp_path, monkeypatch):
    """Cùng lỗi ở `regression_run`: smoke chạy trên đầu nhánh tích hợp nhưng bằng chứng lại ghi `sha` đã staged."""
    from company.orch import verify as ov
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    staged = _merge_sau_staging(orch)
    roots: list[Path] = []
    monkeypatch.setattr(ov, "run_smoke", lambda root, rt, sandbox=None: roots.append(Path(root)) or {"ok": True})
    ev = next(e for e in bus.replay(topic="release-events") if e.payload.get("env") == "staging")
    run = ov.regression_run(orch, ev)
    assert run["sha"] == staged and _git(roots[-1], "rev-parse", "HEAD") == staged
    assert not (roots[-1] / "chua_ky.py").exists()


def test_tool_chi_doc_cua_qa_hoi_quy_nhin_dung_sha_da_staged(tmp_path, monkeypatch):
    """Cùng họ lỗi (luật 5): QA hồi quy đọc code qua tool chỉ đọc — phải thấy đúng thứ đã staged, không phải
    ticket merge vào nhánh tích hợp SAU staging."""
    from company.orch import verify as ov
    from company.tools import ToolCall
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    _merge_sau_staging(orch)
    ev = next(e for e in bus.replay(topic="release-events") if e.payload.get("env") == "staging")
    tb = orch._read_only_tools(ev)
    assert tb is not None
    rid = str(ev.payload["release_id"])
    root = ov._release_root(orch, rid, orch._integration_of_release(ev))
    assert "chua_ky.py" not in tb.call(ToolCall(id="1", name="list_files", args={"path": ".", "glob": "*"}))
    assert (root / "chua_ky.py").exists() is False


def test_bang_chung_deploy_ghi_sha_da_deploy_de_san_chat_luong_doi_chieu(tmp_path, monkeypatch):
    """ADR-0043 sàn A2/R2: gate tự duyệt đòi deploy ở ĐÚNG sha đã staged. Deploy chạy trên `checkout_at(sha)` nhưng
    bằng chứng không nói sha nào — sàn không có gì để đối chiếu, nên code phải điền (model không khai được)."""
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    staged = orch.release_sha["REL-001"]
    assert _rel(bus, "staging")[-1]["evidence"]["deploy"]["sha"] == staged
    orch.gate.decide("REL-001", "approve", by="human:release-manager", reason="staging xanh — deploy production")
    orch.run()
    assert _rel(bus, "production")[-1]["evidence"]["deploy"]["sha"] == staged


def test_khong_co_sha_da_staged_thi_bang_chung_deploy_khong_khai_sha(tmp_path, monkeypatch):
    """Chiều ngược của ca trên: `_release_root` rơi về worktree tích hợp khi chưa có sha — bằng chứng không được ghi
    một sha mà deploy không chạy trên đó (sàn ADR-0043 khi đó báo thiếu, đúng: thiếu bằng chứng → người)."""
    fn, _ = _fake_deploy(monkeypatch)
    bus, orch = _orch(tmp_path, _repo(tmp_path), deploy_fn=fn, runtime=RUNTIME)
    orch.run()
    orch.release_sha.pop("REL-001")
    orch.gate.decide("REL-001", "approve", by="human:release-manager", reason="staging xanh — deploy production")
    orch.run()
    assert "sha" not in _rel(bus, "production")[-1]["evidence"]["deploy"]
