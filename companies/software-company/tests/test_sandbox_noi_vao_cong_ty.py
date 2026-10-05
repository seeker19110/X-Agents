"""K2.4/K2.5 kịch bản B: mọi lệnh có đối số hoặc nội dung do model/repo KHÁCH sinh đi qua `Sandbox`, và lớp bảo
vệ đã dùng được ghi vào bằng chứng (ADR-0035).

Ba điểm gọi: `WorkspaceTools.run` (tool `run` của model), `TicketWorkspace._run` (lint/test của `run_checks`),
`smoke.run_smoke` (lệnh khởi động do spec-writer viết). Git KHÔNG đi qua đây — argv hard-code, hook đã vô hiệu,
push cần credential của người vận hành (ADR-0035 nêu rõ ngoại lệ này).

Test ở đây đo hai thứ khác nhau, đừng gộp: `test_pham_vi_*` là test QUY ƯỚC (grep mã nguồn — bắt PR sau lỡ thêm
một `subprocess.run` mới), còn các test còn lại đo HÀNH VI thật qua một sandbox giả.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from company.bus import InMemoryBus
from company.events import AuditLog, Envelope
from company.gate_cli import PersistentGate
from company.gates import GateRequest
from company.llm import FakeClient
from company.orch.cli import _sandbox_for
from company.orchestrator import Orchestrator
from company.orchestrator import main as orch_main
from company.sandbox import ContainerSandbox, Result, RunSpec, SandboxError, SubprocessSandbox
from company.smoke import Runtime, run_smoke
from company.sqlite_bus import SQLiteBus
from company.tools import WorkspaceTools
from company.workspace import TicketWorkspace
from test_orchestrator import handler
from test_tools_and_agentic import _init_repo


def test_s1_che_do_duoc_audit_va_status_doc_lai_tu_bus():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(), sandbox=SubprocessSandbox())
    orch.record_sandbox_mode()
    orch.record_sandbox_mode()
    rows = [e for e in bus.replay(topic="audit-log") if e.payload.get("action") == "sandbox.mode"]
    assert len(rows) == 1
    assert json.loads(rows[0].payload["evidence"]) == {"mode": "subprocess"}
    bus.publish(Envelope(topic="audit-log", key="builder", actor="builder",
                         payload=AuditLog(actor="builder", action="sandbox.mode",
                                          evidence=json.dumps({"mode": "container:fake"})).model_dump()))
    assert Orchestrator(bus, FakeClient()).status()["sandbox_mode"] == "subprocess"
    restarted = Orchestrator(bus, FakeClient(), sandbox=SpySandbox())
    restarted.record_sandbox_mode()
    assert restarted.status()["sandbox_mode"] == "container:test"


def test_s1_cli_run_ghi_mot_audit_sandbox_mode_truoc_khi_chay(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANY_SANDBOX", "subprocess")
    monkeypatch.setattr("company.llm.make_client", lambda: FakeClient())
    db = tmp_path / "company.sqlite"
    assert orch_main(["--db", str(db), "run", "--max-steps", "0"]) == 0
    rows = [e for e in SQLiteBus(db).replay(topic="audit-log") if e.payload.get("action") == "sandbox.mode"]
    assert len(rows) == 1
    assert json.loads(rows[0].payload["evidence"]) == {"mode": "subprocess"}


def test_s1_container_that_khong_cho_ma_khach_gia_quyet_dinh_gate(tmp_path):
    """Đối chứng F1: cùng lệnh ghi SQLite lọt qua subprocess, bị chặn bởi mount của container."""
    docker = shutil.which("docker")
    image = "python:3.12-slim"
    reason = None
    if docker is None or subprocess.run([docker, "info"], capture_output=True).returncode != 0:
        reason = "Docker Engine không dùng được trên runner"
    elif subprocess.run([docker, "image", "inspect", image], capture_output=True).returncode != 0:
        reason = "image python:3.12-slim chưa có cục bộ; không pull trong test"
    if reason:
        pytest.skip(reason)

    cwd = tmp_path / "work"
    cwd.mkdir()

    def attempt(name, sandbox, python):
        db = tmp_path / f"{name}.sqlite"
        bus = SQLiteBus(db)
        gate = PersistentGate(bus)
        gate.request(GateRequest(kind="spec", subject_id="SPEC-P1", created_by="human:po", checklist=["prd"]))
        fake = Envelope(topic="audit-log", key="human:attacker", actor="human:attacker",
                        payload=AuditLog(actor="human:attacker", action="gate.decide",
                                         evidence=json.dumps({"subject_id": "SPEC-P1", "decision": "approve",
                                                              "by": "human:attacker"})).model_dump())
        code = ("import sqlite3\n"
                f"db=sqlite3.connect({str(db)!r})\n"
                "db.execute('INSERT INTO events(event_id,topic,key,actor,ts,body) VALUES (?,?,?,?,?,?)', "
                f"({fake.event_id!r}, 'audit-log', 'human:attacker', 'human:attacker', "
                f"{fake.ts.isoformat()!r}, {fake.model_dump_json()!r}))\n"
                "db.commit()\n")
        result = sandbox.run(RunSpec(argv=[python, "-c", code], cwd=cwd))
        bus.poll()
        reopened = SQLiteBus(db)
        approved = PersistentGate(reopened).is_approved("SPEC-P1")
        reopened.close()
        bus.close()
        return result, approved

    plain, forged = attempt("plain", SubprocessSandbox(), sys.executable)
    protected, approved = attempt("protected", ContainerSandbox(docker, image), "python")
    assert plain.exit_code == 0 and forged
    assert protected.exit_code != 0 and not approved

SRC = Path(__file__).resolve().parents[1] / "src" / "company"
SCHEMAS = Path(__file__).resolve().parents[1] / "topics" / "schemas"


class SpySandbox:
    """Ghi lại từng `RunSpec` rồi trả kết quả dựng sẵn. Không chạy gì — test đo ĐƯỜNG ĐI, không đo lệnh."""

    def __init__(self, name: str = "container:test", exit_code: int = 0, stdout: str = "ok", stderr: str = ""):
        self.name = name
        self.specs: list[RunSpec] = []
        self._res = Result(exit_code, stdout, stderr, False, name)

    def run(self, spec: RunSpec) -> Result:
        self.specs.append(spec)
        return self._res

    def spawn(self, spec: RunSpec):
        self.specs.append(spec)
        raise OSError("SpySandbox không spawn thật")


def _ws(tmp_path) -> TicketWorkspace:
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    ws.create()
    return ws


# ---------- K2.4: phạm vi bắt buộc (test quy ước, grep mã nguồn) ----------

# Ngoại lệ có LÝ DO, không phải chỗ giấu lệnh chưa xử lý:
# - `sandbox.py`: chính nó là nơi duy nhất được gọi `subprocess` — đó là định nghĩa của module.
# - `workspace.py`, `gate_brief.py`: các lời gọi `git` (ADR-0035 §"Git KHÔNG đi qua đây" — argv hard-code, hook
#   đã vô hiệu, push cần credential của người vận hành). Test dưới khẳng định TỪNG lời gọi còn lại trong hai file
#   đó thật sự là git, chứ không miễn cả file.
# - `llm.py`: `claude`/`codex` chạy như MODEL BACKEND (ADR-0023/0024). Không phải lệnh do model hay repo khách
#   sinh — argv do code ghép, và chính nó là thứ gọi model; nhốt nó vào container mạng tắt là cắt đường ra API và
#   mất credential của người vận hành. Tool mà CLI xin chạy vẫn đi qua cầu MCP về `tools.py`, tức là VẪN qua
#   `Sandbox` (xem `ClaudeCodeClient.bind_toolbox`) — đó mới là chỗ mã của khách chạy.
# - `github_pr.py` (ADR-0038): `gh pr list/create` — cùng lý do với git: argv do code ghép (slug, nhánh, tiêu đề),
#   không chạy mã của khách, cần credential của người vận hành trên đĩa (`gh auth login`; env đã lọc `GH_*`).
#   Nhốt vào container mạng tắt là cắt đường lên GitHub. Test dưới khẳng định TỪNG lời gọi trong file là gh.
# - `deploy.py` (ADR-0039 §7): `docker compose up -d/ps/logs/down` — ngoại lệ subprocess THỨ HAI. Nhốt một client
#   gọi `/var/run/docker.sock` vào container là vô nghĩa: qua socket đó nó có quyền cao nhất của máy, nên
#   "sandbox" chỉ là một lớp giả. argv do code ghép (`--project-name` do code đặt, chỉ đường dẫn compose file đến
#   từ spec và phải là file có thật trong repo khách), env đã lọc `clean_env`.
MIEN_HOAN_TOAN = {"sandbox.py", "llm.py"}
CHI_GIT = {"workspace.py", "gate_brief.py"}
CHI_GH = {"github_pr.py"}
CHI_COMPOSE = {"deploy.py"}


def _goi_subprocess(src: str) -> list[str]:
    """Bắt cả THAM CHIẾU (`run: Any = subprocess.run`) chứ không chỉ lời gọi có ngoặc: một module tiêm được runner
    lách được luật cũ bằng cách giữ `subprocess.run` làm giá trị mặc định — đúng hình dạng của `deploy.py`."""
    return [m.group(0) for m in re.finditer(r"subprocess\.(run|Popen)\b[^\n]*", src)]


def test_pham_vi_khong_module_nao_ngoai_sandbox_goi_subprocess_truc_tiep():
    """Đo hai chiều: trả `tools.py` về `subprocess.run(...)` như trước K2.4 thì test này đỏ ngay, không cần chạy
    một lượt agent nào. Đây là chốt cho PR SAU — module mới trong `company/` phải đi qua `Sandbox`, không chỉ ba
    module đã sửa hôm nay."""
    vi_pham: list[str] = []
    for p in sorted(SRC.rglob("*.py")):
        if p.name in MIEN_HOAN_TOAN:
            continue
        for goi in _goi_subprocess(p.read_text(encoding="utf-8")):
            if p.name in CHI_GIT and '"git"' in goi:
                continue
            if p.name in CHI_GH and '"gh"' in goi:
                continue
            if p.name in CHI_COMPOSE and "compose" in goi:
                continue
            vi_pham.append(f"{p.relative_to(SRC).as_posix()}: {goi[:110]}")
    assert not vi_pham, ("lệnh chạy ngoài Sandbox (ADR-0035) — đưa qua `Sandbox` hoặc ghi lý do vào danh sách "
                         "ngoại lệ của test này:\n" + "\n".join(vi_pham))


def test_pham_vi_git_van_duoc_phep_ngoai_sandbox():
    """Chiều ngược của test trên: ngoại lệ git là CÓ THẬT, không phải danh sách rỗng để test luôn xanh."""
    for name in sorted(CHI_GIT):
        goi = _goi_subprocess((SRC / name).read_text(encoding="utf-8"))
        assert goi and all('"git"' in g for g in goi), f"mọi lời gọi còn lại trong {name} phải là git: {goi}"


def test_pham_vi_gh_chi_o_github_pr_va_la_gh_that():
    """Chiều ngược cho ngoại lệ ADR-0038: `github_pr.py` có gọi subprocess thật, và mọi lời gọi ở đó là `gh`."""
    for name in sorted(CHI_GH):
        goi = _goi_subprocess((SRC / name).read_text(encoding="utf-8"))
        assert goi and all('"gh"' in g for g in goi), f"mọi lời gọi trong {name} phải là gh: {goi}"


def test_pham_vi_compose_chi_o_deploy_va_chi_bon_lenh_con():
    """Chiều ngược cho ngoại lệ ADR-0039. Binary là biến (`docker` hay `COMPANY_DEPLOY_RUNTIME`) nên không grep
    được như `"gh"`; grep phần KHÔNG đổi được — `deploy.py` có đúng một tham chiếu subprocess, nó là runner mặc
    định của compose — rồi đo phần còn lại bằng hành vi: argv luôn bắt đầu `<binary> compose --project-name …`
    và chỉ bốn lệnh con được ghép."""
    from company.deploy import CMD_SUB, _argv

    for name in sorted(CHI_COMPOSE):
        goi = _goi_subprocess((SRC / name).read_text(encoding="utf-8"))
        assert len(goi) == 1 and "compose" in goi[0], f"{name} chỉ được có runner compose mặc định: {goi}"
    assert set(CMD_SUB) == {"up", "ps", "logs", "down"}, "ADR-0039 §6 cho phép đúng bốn lệnh con"
    argv = _argv("docker", "company-P-staging", "compose.yaml", "up", "-d")
    assert argv[:6] == ["docker", "compose", "--project-name", "company-P-staging", "-f", "compose.yaml"]


# ---------- K2.4: hành vi — ba điểm gọi thật sự đi qua sandbox được tiêm ----------

def test_tool_run_cua_model_di_qua_sandbox(tmp_path):
    ws = _ws(tmp_path)
    spy = SpySandbox(stdout="All checks passed!")
    out = WorkspaceTools(ws, sandbox=spy).run("lint")
    assert len(spy.specs) == 1, "tool `run` phải đi qua sandbox, không gọi subprocess thẳng"
    spec = spy.specs[0]
    assert spec.cwd == ws.path and spec.network is False, "lint/test không cần mạng → mạng tắt"
    assert spec.env.get("PATH"), "env phải là `clean_env()` tường minh; RunSpec.env rỗng là lệnh không có cả PATH"
    assert out.startswith("exit=0") and "All checks passed!" in out


def test_run_checks_di_qua_sandbox_cua_worktree(tmp_path):
    ws = _ws(tmp_path)
    spy = SpySandbox()
    ws.sandbox = spy
    checks = ws.run_checks()
    assert len(spy.specs) == 2, "lint và test, cả hai qua sandbox"
    assert checks["lint"] is True and checks["tests"] is True


def test_sandbox_di_theo_worktree_nen_runner_khong_phai_doi_dong_nao(tmp_path):
    """`runner.py` dựng `WorkspaceTools(ws, ...)` mà không biết gì về sandbox. Đường duy nhất để lượt agent kỹ
    thuật chạy trong container là sandbox đi THEO worktree — nếu ai đó bỏ nhánh `ws.sandbox` trong
    `WorkspaceTools.__init__`, mọi lượt agent lặng lẽ tụt về subprocess mà không test nào khác đỏ."""
    ws = _ws(tmp_path)
    spy = SpySandbox()
    ws.sandbox = spy
    assert WorkspaceTools(ws).sandbox is spy
    assert WorkspaceTools(ws, sandbox=SubprocessSandbox()).sandbox is not spy, "tham số tường minh thắng"
    assert isinstance(WorkspaceTools(ws.path).sandbox, SubprocessSandbox), "gốc là Path thì không có gì để đi theo"


def test_smoke_mo_dung_mot_cong_loopback_chu_khong_tat_mang(tmp_path):
    """Khác lint/test: lệnh khởi động PHẢI trả lời được `127.0.0.1:<port>`, nên `network=True` + `port`. Bỏ hai
    trường này thì backend container chạy `--network none` và mọi smoke đều `không trả lời` — xanh vỏ đỏ lòng."""
    spy = SpySandbox()
    out = run_smoke(tmp_path, Runtime((sys.executable, "-c", "pass", "{port}"), timeout_s=2), sandbox=spy)
    assert len(spy.specs) == 1
    spec = spy.specs[0]
    assert spec.network is True and spec.port == out["port"] and spec.port > 0
    assert "OSError" in out["error"], "SpySandbox không spawn thật — lỗi khởi động phải vào bằng chứng"


# ---------- K2.5: lớp bảo vệ đã dùng nằm trong BẰNG CHỨNG ----------

def test_lint_het_gio_thi_output_la_ly_do_het_gio_khong_phai_chuoi_rong(tmp_path):
    """`SubprocessSandbox` nuốt `TimeoutExpired` và trả `Result(timed_out=True, stdout="")` — nếu `_run` chỉ đọc
    `exit_code` thì `run_checks` báo `lint=False` với output RỖNG, người đọc PR không biết là lint đỏ hay lint
    chưa từng chạy xong. Đây là khác biệt duy nhất giữa đường cũ (`except TimeoutExpired`) và đường sandbox."""
    class HetGio:
        name = "subprocess"
        def run(self, spec):
            return Result(None, "", f"quá {spec.timeout}s", True, self.name)
        def spawn(self, spec):
            raise AssertionError("lint không spawn")

    ws = _ws(tmp_path)
    ws.sandbox = HetGio()
    checks = ws.run_checks()
    assert checks["lint"] is False and "quá" in checks["lint_output"]


def test_local_checks_ghi_ten_sandbox(tmp_path):
    ws = _ws(tmp_path)
    ws.sandbox = SpySandbox(name="container:python:3.12-slim")
    assert ws.run_checks()["sandbox"] == "container:python:3.12-slim"


def test_smoke_ghi_ten_sandbox_ke_ca_khi_khong_khoi_dong_duoc(tmp_path):
    """Bằng chứng phải nói lớp bảo vệ NGAY CẢ khi lệnh chết: người đọc cần phân biệt "sản phẩm hỏng" với
    "container thiếu image nên không chạy được"."""
    out = run_smoke(tmp_path, Runtime(("lenh-khong-co-that-xyz",), timeout_s=2), sandbox=SpySandbox(name="x:1"))
    assert out["sandbox"] == "x:1" and out["ok"] is False


def test_mac_dinh_van_la_subprocess_o_ca_hai_bang_chung(tmp_path):
    """Hành vi mặc định KHÔNG đổi so với trước ADR-0035: không tiêm gì thì vẫn là tiến trình con thường, và bằng
    chứng nói đúng như vậy — `sandbox=subprocess` không phải lỗi, nó là lớp bảo vệ đang thật sự có."""
    ws = _ws(tmp_path)
    assert ws.run_checks()["sandbox"] == "subprocess"
    out = run_smoke(tmp_path, Runtime((sys.executable, "-c", "import sys;sys.exit(3)"), timeout_s=5))
    assert out["sandbox"] == "subprocess" and out["exit_code"] == 3


def test_audit_tools_used_ghi_sandbox_chi_khi_bang_chay_duoc_lenh(tmp_path):
    """`dump_calls` là thứ đi vào audit `tools_used`. Bảng chỉ đọc (`allow_run=False`, researcher trên repo khách)
    KHÔNG được khai sandbox: nói một lớp bảo vệ không tồn tại vì không có gì để bảo vệ cũng là lời khai sai."""
    import json as _json

    from company.tools import dump_calls

    ws = _ws(tmp_path)
    ws.sandbox = SpySandbox(name="container:img")
    assert _json.loads(dump_calls(WorkspaceTools(ws).toolbox()))["sandbox"] == "container:img"
    assert "sandbox" not in _json.loads(dump_calls(WorkspaceTools(ws.path, allow_run=False).toolbox()))


def test_schema_cho_phep_truong_sandbox():
    """Bằng chứng ghi vào payload mà schema không khai thì `guard` chặn event — K2.5 là hai nửa, thiếu nửa nào
    cũng hỏng."""
    for topic, walk in (("pull-requests", ("local_checks",)), ("release-events", ("smoke",))):
        node = json.loads((SCHEMAS / f"{topic}.json").read_text(encoding="utf-8"))["properties"]["payload"]["properties"]
        for k in walk:
            node = node[k]
        assert "sandbox" in node["properties"], f"{topic}.{'.'.join(walk)} thiếu `sandbox`"


# ---------- CLI: chỉ lệnh chạy mã của khách mới đọc cấu hình sandbox ----------

@pytest.mark.parametrize("cmd", ["status", "report", "show", "comment", "takeover", "metrics"])
def test_cli_lenh_cua_nguoi_khong_dung_sandbox_theo_cau_hinh(cmd, monkeypatch):
    """`COMPANY_SANDBOX=container` trên máy không có docker là fail-closed CÓ CHỦ Ý — nhưng chỉ cho lệnh thật sự
    chạy mã của khách. Ném `SandboxError` khi người vận hành gõ `status` là chặn nhầm."""
    monkeypatch.setenv("COMPANY_SANDBOX", "container")
    monkeypatch.setenv("COMPANY_SANDBOX_RUNTIME", "docker-khong-co-that-xyz")
    assert _sandbox_for(cmd) is None


@pytest.mark.parametrize("cmd", ["run", "redeploy", "recheck"])  # recheck: DAST + uv run trên cây RC (ADR-0047)
def test_cli_lenh_chay_ma_khach_fail_closed(cmd, monkeypatch):
    monkeypatch.setenv("COMPANY_SANDBOX", "container")
    monkeypatch.setenv("COMPANY_SANDBOX_RUNTIME", "docker-khong-co-that-xyz")
    with pytest.raises(SandboxError):
        _sandbox_for(cmd)


def test_orchestrator_mac_dinh_subprocess_khong_doc_cau_hinh(monkeypatch):
    """`Orchestrator` được dựng thẳng trong hàng trăm test và trong `console`; nếu nó tự gọi `sandbox_from_config`
    thì `auto` sẽ chọn container ngay khi máy có docker (CI ubuntu có) — hành vi test đổi theo máy chạy."""
    monkeypatch.setenv("COMPANY_SANDBOX", "container")
    o = Orchestrator(InMemoryBus(), FakeClient(handler=handler))
    assert isinstance(o.sandbox, SubprocessSandbox)


@pytest.mark.parametrize('caller', ['tools', 'workspace', 'licenses'])
@pytest.mark.parametrize('mode', ['container:test', 'subprocess'])
def test_s2_uv_chi_mo_pypi_trong_container_khong_mo_mang_khac(tmp_path, caller, mode):
    from company.supply_chain import installed_licenses
    ws = _ws(tmp_path)
    (ws.path / 'pyproject.toml').write_text(
        '[project]\nname="khach"\nversion="0.1.0"\ndependencies=["pytest", "ruff"]\n')
    spy = SpySandbox(name=mode, stdout='{}'); ws.sandbox = spy
    if caller == 'tools': WorkspaceTools(ws).run('lint')
    elif caller == 'workspace': ws.run_checks()
    else: installed_licenses(ws.path, spy)
    assert spy.specs
    for spec in spy.specs:
        assert spec.argv[0] == 'uv' and spec.network is False
        assert spec.allowed_domains == (('pypi.org', 'files.pythonhosted.org') if mode.startswith('container:') else ())
