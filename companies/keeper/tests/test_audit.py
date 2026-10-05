"""BT6 — `audit.py` (`security-auditor`): gitleaks toàn lịch sử, audit dependency, OpenSSF Scorecard.

Mọi công cụ ngoài đi qua một `runner` TIÊM ĐƯỢC; không test nào gọi `gitleaks`/`pip-audit`/`gh` thật, không
test nào chạm mạng, và KHÔNG ca nào bị bỏ qua theo `os.name` hay biến môi trường — công cụ vắng mặt là một
NHÁNH MÃ được đo, không phải một lý do skip.
"""
import json
from pathlib import Path

from keeper.audit import (
    SCORECARD_CHECKS,
    TOOL_ERROR,
    audit,
    dependabot_findings,
    gitleaks_findings,
    pip_audit_findings,
    scorecard_findings,
)
from keeper.events import RunOutcome
from keeper.evidence import MISSING_EXIT, TIMEOUT_EXIT
from keeper.fakes import FakeGitHub
from keeper.github import CodeScanningAlert, DependabotAlert

LEAKS = [
    {"RuleID": "generic-api-key", "Description": "Generic API Key", "File": "llm.yaml",
     "StartLine": 12, "Commit": "abc123"},
]
PIP_AUDIT = {
    "dependencies": [
        {"name": "pydantic", "version": "2.6.0",
         "vulns": [{"id": "GHSA-xxxx", "description": "lỗ hổng mẫu", "fix_versions": ["2.6.1"]}]},
        {"name": "pyyaml", "version": "6.0", "vulns": []},
    ]
}


class _Tools:
    """Giả mọi tiến trình ngoài. `missing` liệt kê tên chương trình coi như KHÔNG có trên máy."""

    def __init__(self, *, leaks=LEAKS, gitleaks_exit=1, pip_json=PIP_AUDIT, pip_exit=1, missing=()) -> None:
        self.leaks, self.gitleaks_exit = leaks, gitleaks_exit
        self.pip_json, self.pip_exit = pip_json, pip_exit
        self.missing = set(missing)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, cwd, *, timeout: int = 600, tail: int | None = 2000) -> RunOutcome:
        argv = tuple(argv)
        self.calls.append(argv)
        cmd = " ".join(argv)
        if argv[0] in self.missing:
            return RunOutcome(cmd=cmd, exit_code=MISSING_EXIT, output_tail=f"{argv[0]}: không có trên máy")
        if argv[0] == "gitleaks":
            path = Path(argv[argv.index("--report-path") + 1])
            if self.leaks is not None:
                path.write_text(json.dumps(self.leaks), encoding="utf-8")
            return RunOutcome(cmd=cmd, exit_code=self.gitleaks_exit, output_tail="")
        return RunOutcome(cmd=cmd, exit_code=self.pip_exit, output_tail=json.dumps(self.pip_json))


class _GH(FakeGitHub):
    def __init__(self, *, dependabot=None, code_scanning=None) -> None:
        super().__init__()
        self._dep = dependabot
        self._cs = code_scanning

    def dependabot_alerts(self):
        return super().dependabot_alerts() if self._dep is None else list(self._dep)

    def code_scanning_alerts(self):
        return super().code_scanning_alerts() if self._cs is None else list(self._cs)


# --- gitleaks ---------------------------------------------------------------------------------------

def test_gitleaks_quet_toan_lich_su_va_bao_cao_secret(tmp_path):
    tools = _Tools()
    out = gitleaks_findings(tmp_path, runner=tools, report_path=tmp_path / "gitleaks.json")
    assert [f.kind for f in out] == ["secret"]
    assert out[0].subject == "llm.yaml:12" and out[0].severity == "critical"
    assert "generic-api-key" in out[0].detail
    argv = tools.calls[0]
    assert argv[0] == "gitleaks" and "--log-opts=--all" in argv and "--redact" in argv


def test_gitleaks_khong_co_tren_may_thi_khong_nem_va_khong_lam_do_suite(tmp_path):
    assert gitleaks_findings(tmp_path, runner=_Tools(missing=["gitleaks"]), report_path=tmp_path / "gitleaks.json") == []


def test_gitleaks_bao_cao_cu_con_lai_thi_bi_xoa_truoc_khi_chay(tmp_path):
    """Báo cáo của LẦN CHẠY TRƯỚC (cùng `report_path`) không được đọc nhầm thành kết quả lần này."""
    report_path = tmp_path / "gitleaks.json"
    report_path.write_text(json.dumps([{"RuleID": "cu", "File": "cu.py", "StartLine": 1, "Commit": "cu"}]),
                            encoding="utf-8")
    out = gitleaks_findings(tmp_path, runner=_Tools(), report_path=report_path)
    assert [f.subject for f in out] == ["llm.yaml:12"]  # kết quả MỚI, không phải "cu.py:1" của file cũ


def test_gitleaks_khong_truyen_report_path_thi_tu_sinh_ten_duy_nhat(tmp_path):
    """Không truyền `report_path`: hàm tự sinh một đường dẫn mặc định (theo `os.getpid()`+`uuid4`, không phải
    một tên cố định) — công cụ vắng mặt nên không có gì để ghi, chỉ đo được đường ĐI QUA nhánh mặc định."""
    assert gitleaks_findings(tmp_path, runner=_Tools(missing=["gitleaks"])) == []


def test_gitleaks_sach_thi_khong_co_phat_hien_nao(tmp_path):
    assert gitleaks_findings(tmp_path, runner=_Tools(leaks=[], gitleaks_exit=0), report_path=tmp_path / "gitleaks.json") == []


def _la_loi_cong_cu(out, tool, kind):
    """Công cụ CÓ trên máy nhưng không chạy xong: đúng MỘT finding đánh dấu, không phải `[]` ("sạch")."""
    assert len(out) == 1, out
    f = out[0]
    assert f.subject == f"{tool}:{TOOL_ERROR}" and f.kind == kind
    return f


def test_gitleaks_bao_cao_hong_hoac_thieu_thi_bao_loi_cong_cu(tmp_path):
    """Không file báo cáo / báo cáo không phải list = gitleaks KHÔNG quét xong — không được đọc thành "sạch"."""
    _la_loi_cong_cu(gitleaks_findings(tmp_path, runner=_Tools(leaks=None), report_path=tmp_path / "gitleaks.json"),
                    "gitleaks", "secret")          # không ghi file nào
    _la_loi_cong_cu(gitleaks_findings(tmp_path, runner=_Tools(leaks={"khong": "phai list"}),
                                      report_path=tmp_path / "gitleaks.json"), "gitleaks", "secret")


def test_gitleaks_qua_gio_thi_bao_loi_cong_cu(tmp_path):
    class _Treo(_Tools):
        def __call__(self, argv, cwd, **kw):
            return RunOutcome(cmd=" ".join(argv), exit_code=TIMEOUT_EXIT, output_tail="gitleaks: quá 600s")

    f = _la_loi_cong_cu(gitleaks_findings(tmp_path, runner=_Treo(), report_path=tmp_path / "gitleaks.json"),
                        "gitleaks", "secret")
    assert "quá 600s" in f.detail


# --- dependency -------------------------------------------------------------------------------------

def test_pip_audit_bao_cao_tung_lo_hong(tmp_path):
    out = pip_audit_findings(tmp_path, runner=_Tools())
    assert [f.subject for f in out] == ["pydantic==2.6.0"]
    assert out[0].kind == "dependency" and "GHSA-xxxx" in out[0].detail


def test_pip_audit_khong_co_tren_may_thi_rong_json_hong_thi_bao_loi(tmp_path):
    assert pip_audit_findings(tmp_path, runner=_Tools(missing=["uv"])) == []
    _la_loi_cong_cu(pip_audit_findings(tmp_path, runner=_Tools(pip_json="khong phai dict")),
                    "pip-audit", "dependency")


def test_pip_audit_output_khong_phai_json_thi_bao_loi_cong_cu(tmp_path):
    class _Rac(_Tools):
        def __call__(self, argv, cwd, **kw):
            return RunOutcome(cmd=" ".join(argv), exit_code=2, output_tail="Traceback: khong phai JSON")

    f = _la_loi_cong_cu(pip_audit_findings(tmp_path, runner=_Rac()), "pip-audit", "dependency")
    assert "Traceback" in f.detail


def test_pip_audit_qua_gio_thi_bao_loi_cong_cu(tmp_path):
    class _Treo(_Tools):
        def __call__(self, argv, cwd, **kw):
            return RunOutcome(cmd=" ".join(argv), exit_code=TIMEOUT_EXIT, output_tail="uv run pip-audit: quá 600s")

    _la_loi_cong_cu(pip_audit_findings(tmp_path, runner=_Treo()), "pip-audit", "dependency")


def test_dependabot_chi_lay_alert_dang_mo():
    gh = _GH(dependabot=[
        DependabotAlert(number=1, state="open", severity="high", summary="bump A"),
        DependabotAlert(number=2, state="fixed", severity="critical", summary="đã vá"),
        DependabotAlert(number=3, state="open", severity="", summary="không rõ mức"),
    ])
    out = dependabot_findings(gh)
    assert [f.subject for f in out] == ["dependabot-1", "dependabot-3"]
    assert [f.severity for f in out] == ["high", "medium"]  # mức lạ/rỗng → medium, không đoán cao hơn


# --- Scorecard --------------------------------------------------------------------------------------

def test_scorecard_lay_tu_alert_code_scanning_do_action_dang_len():
    gh = _GH(code_scanning=[
        CodeScanningAlert(number=7, state="open", severity="high", rule_description="Token-Permissions: ..."),
        CodeScanningAlert(number=8, state="open", severity="", rule_description="Branch-Protection"),
        CodeScanningAlert(number=9, state="open", severity="high", rule_description="py/sql-injection"),
        CodeScanningAlert(number=10, state="fixed", severity="high", rule_description="Pinned-Dependencies"),
    ])
    out = scorecard_findings(gh)
    assert [f.subject for f in out] == ["Token-Permissions", "Branch-Protection"]
    assert [f.severity for f in out] == ["high", "medium"]
    assert {f.kind for f in out} == {"scorecard"}
    assert "Token-Permissions" in SCORECARD_CHECKS


def test_scorecard_repo_khong_bat_action_thi_khong_co_phat_hien():
    assert scorecard_findings(FakeGitHub()) == []


class _GHKhongTraLoi(FakeGitHub):
    """`gh` chưa đăng nhập, quá giờ, hay API trả lỗi: `GitHubReader` trả `None` = KHÔNG BIẾT."""

    def dependabot_alerts(self):
        return None

    def code_scanning_alerts(self):
        return None


def test_gh_khong_tra_loi_thi_bao_loi_cong_cu_khong_phai_sach():
    """Trước đây `GitHubReader` nuốt lỗi `gh` thành `[]`, và hai nguồn qua `gh` đọc "không quét được" thành "không
    có alert nào" — đúng điều docstring module cấm cho gitleaks/pip-audit ("Công cụ lỗi KHÔNG phải 'không có
    phát hiện'"), chỉ là đi đường khác."""
    gh = _GHKhongTraLoi()
    _la_loi_cong_cu(dependabot_findings(gh), "dependabot", "dependency")
    f = _la_loi_cong_cu(scorecard_findings(gh), "code-scanning", "scorecard")
    assert "KHÔNG phải" in f.detail


# --- gộp --------------------------------------------------------------------------------------------

def test_audit_gop_ba_nguon(tmp_path):
    out = audit(tmp_path, _GH(), runner=_Tools())
    assert [f.kind for f in out] == ["secret", "dependency", "dependency"]


def test_audit_khong_co_cong_cu_nao_tren_may_van_chay_duoc(tmp_path):
    out = audit(tmp_path, FakeGitHub(), runner=_Tools(missing=["gitleaks", "uv"]))
    assert [f.kind for f in out] == ["dependency"]  # chỉ còn dependabot qua gh
