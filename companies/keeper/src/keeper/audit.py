"""`security-auditor` (BT6, `DAC-TA-KEEPER.md` §8): gitleaks toàn lịch sử + audit dependency + OpenSSF
Scorecard, tất cả phát ra `SecurityFinding` (topic `security-findings`).

## Ba nguồn, và Scorecard đến qua đường nào

Đặc tả nói "Scorecard **qua `github.py`**". Đo lại: `GitHubReader` (BT2) không có phương thức scorecard nào,
và `gh` cũng không có endpoint scorecard — điểm Scorecard công khai nằm ở `api.securityscorecards.dev`, tức
là MẠNG, mà test của `keeper` không được chạm. Cơ chế thật đã có sẵn: **Scorecard Action đẩy kết quả lên
GitHub code scanning dưới dạng SARIF**, mỗi check là một rule (`Token-Permissions`, `Branch-Protection`…).
Nên `scorecard_findings()` đọc `gh.code_scanning_alerts()` — đúng nghĩa "qua `github.py`", dùng lại
`GitHubReader`/`FakeGitHub` sẵn có, không thêm một phương thức nào và không chạm mạng.

Repo chưa bật Scorecard Action thì `code_scanning_alerts()` vẫn trả các alert của công cụ khác (CodeQL...);
lọc theo TÊN CHECK của Scorecard nên chúng không bị đếm nhầm thành điểm Scorecard.

## Công cụ vắng mặt là một NHÁNH MÃ, không phải một lý do skip

`gitleaks`/`pip-audit` không có trên máy → `run_command` trả `MISSING_EXIT` (`evidence.py`) → hàm ở đây trả
`[]`. Không ném, không làm đỏ suite, và **không** `pytest.mark.skipif` theo `os.name` hay biến môi trường:
một ca bỏ qua theo môi trường là một ca xanh vì rỗng (`TRAPS.md` §2). Cùng lý do, mọi tiến trình đi qua tham
số `runner` tiêm được.

## Công cụ lỗi KHÔNG phải "không có phát hiện"

Chỉ `MISSING_EXIT` mới nghĩa là công cụ vắng mặt. Công cụ CÓ trên máy mà quá giờ (`TIMEOUT_EXIT`), không ghi
báo cáo, hay trả thứ không parse được → đúng MỘT `SecurityFinding` đánh dấu (`subject="<tool>:loi-cong-cu"`,
`kind` của nguồn đó, mức `DEFAULT_SEVERITY`), mang lý do trong `detail`. Trả `[]` ở đây là đọc "chưa quét
xong" thành "sạch" — khuôn 1 "chế độ hỏng không tự khai báo" (`TRAPS.md`).

Hai nguồn qua `gh` theo cùng luật: `GitHubReader` trả `None` khi `gh` không trả lời → `dependabot:loi-cong-cu`
/ `code-scanning:loi-cong-cu`. Bản đầu nuốt lỗi `gh` thành `[]` ngay trong `github.py`, nên luật trên chỉ đúng
cho hai công cụ chạy cục bộ.

Mã thoát của cả hai công cụ này là 1 khi TÌM THẤY vấn đề — nên `exit_code != 0` KHÔNG phải lỗi ở đây, và
không được dùng để quyết định gì. Chỉ nội dung báo cáo mới được đọc.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from .events import SecurityFinding
from .evidence import MISSING_EXIT, CommandRunner, run_command
from .github import CodeScanningAlert, DependabotAlert

# Bốn mức của `SecurityFinding.severity`. Bảng chạy được (`SEVERITIES`) và kiểu tĩnh (`Severity`) phải khớp
# nhau; giữ cả hai vì `_severity()` nhận chuỗi tự do từ GitHub, mypy không kiểm được cho ta.
Severity = Literal["low", "medium", "high", "critical"]
SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})
# Mức khi công cụ/GitHub trả rỗng hoặc một chuỗi lạ: KHÔNG đoán cao hơn (mọi thứ thành `critical` thì
# `security-findings` hết phân biệt được), cũng không đoán `low` (làm biến mất việc thật).
DEFAULT_SEVERITY: Severity = "medium"

# Tên check của OpenSSF Scorecard (bản v4/v5) — dùng làm bộ lọc rule id trong alert code scanning.
SCORECARD_CHECKS = frozenset({
    "Binary-Artifacts", "Branch-Protection", "CI-Tests", "CII-Best-Practices", "Code-Review",
    "Contributors", "Dangerous-Workflow", "Dependency-Update-Tool", "Fuzzing", "License", "Maintained",
    "Packaging", "Pinned-Dependencies", "SAST", "Security-Policy", "Signed-Releases", "Token-Permissions",
    "Vulnerabilities", "Webhooks",
})

#: Hậu tố `subject` của finding đánh dấu "công cụ CÓ trên máy nhưng không chạy xong" (quá giờ, lỗi, báo cáo
#: hỏng/thiếu) — xem mục "Công cụ lỗi" ở docstring module.
TOOL_ERROR = "loi-cong-cu"
# `GitHubReader` đã gộp mọi chế độ hỏng của `gh` (vắng mặt, chưa đăng nhập, quá giờ, API lỗi, JSON hỏng) thành
# `None`; lý do chi tiết nằm trong bộ đệm của nó, không tới được đây.
_GH_UNKNOWN = "gh không trả lời (vắng mặt, chưa `gh auth login`, quá giờ, API lỗi hay JSON hỏng)"


def _default_gitleaks_report_path() -> Path:
    """Tên file MẶC ĐỊNH khi không truyền `report_path`, nhưng DUY NHẤT theo tiến trình + lời gọi
    (`os.getpid()` + `uuid4`) — không phải một hằng số toàn cục cố định.

    Bản đầu dùng đúng một tên cố định (`keeper-gitleaks.json`) trong `tempfile.gettempdir()` cho MỌI lời gọi
    không truyền `report_path`. Bốn ca của `test_audit.py` (dòng ~76-94) gọi `gitleaks_findings()` không
    truyền `report_path` nên ghi/xoá CÙNG một file ngoài `tmp_path` — chạy `-n auto` hay hai phiên song song
    là giẫm lên nhau, đúng khuôn "test đỏ theo môi trường" (`AGENTS.md` §5). Test đã sửa để luôn truyền
    `report_path` trỏ vào `tmp_path`, nhưng MÃ SẢN PHẨM (không có `tmp_path`) vẫn gọi không truyền — nên hàm
    này thêm phần còn thiếu: một tên duy nhất mỗi lần gọi, để hai lần `security-auditor` chạy chồng nhau
    không đọc nhầm báo cáo của nhau.
    """
    return Path(tempfile.gettempdir()) / f"keeper-gitleaks-{os.getpid()}-{uuid.uuid4().hex}.json"


class SecuritySource(Protocol):
    """Phần giao diện `github.py` mà `security-auditor` cần — `GitHubReader` và `FakeGitHub` đều khớp."""
    def dependabot_alerts(self) -> list[DependabotAlert] | None: ...
    def code_scanning_alerts(self) -> list[CodeScanningAlert] | None: ...


def _severity(raw: str | None) -> Severity:
    s = (raw or "").strip().lower()
    return cast(Severity, s) if s in SEVERITIES else DEFAULT_SEVERITY


def _tool_error(tool: str, kind: Literal["secret", "dependency", "scorecard"], reason: str) -> list[SecurityFinding]:
    """Một finding đánh dấu công cụ không chạy xong — xem mục "Công cụ lỗi" ở docstring module."""
    return [SecurityFinding(subject=f"{tool}:{TOOL_ERROR}", severity=DEFAULT_SEVERITY, kind=kind,
                            detail=f"{tool} không quét xong — KHÔNG phải 'không có phát hiện': {reason[-300:]}")]


def _load_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def gitleaks_findings(
    repo: Path, *, runner: CommandRunner = run_command, report_path: Path | None = None,
) -> list[SecurityFinding]:
    """`gitleaks` trên TOÀN LỊCH SỬ (`--log-opts=--all`), báo cáo JSON ra file.

    `--redact` là bắt buộc: không có nó thì bí mật vừa tìm được lại được chép nguyên văn vào một event trên
    bus và vào log — tức là công cụ tìm rò rỉ tự tạo thêm một chỗ rò rỉ.
    """
    path = report_path or _default_gitleaks_report_path()
    if path.exists():
        path.unlink()  # báo cáo của lần chạy TRƯỚC không được đọc nhầm thành kết quả lần này
    r = runner(
        ("gitleaks", "detect", "--source", str(repo), "--no-banner", "--redact",
         "--log-opts=--all", "--report-format", "json", "--report-path", str(path)),
        repo,
    )
    if r.exit_code == MISSING_EXIT:
        return []
    if not path.exists():
        return _tool_error("gitleaks", "secret", f"exit {r.exit_code}, không có báo cáo: {r.output_tail}")
    data = _load_json(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return _tool_error("gitleaks", "secret", f"exit {r.exit_code}, báo cáo không phải mảng JSON")
    return [
        SecurityFinding(
            subject=f"{row.get('File', '?')}:{row.get('StartLine', 0)}",
            severity="critical",  # một bí mật đã vào lịch sử git là đã lộ, không có mức nào thấp hơn
            kind="secret",
            detail=f"{row.get('RuleID', '?')}: {row.get('Description', '')} (commit {row.get('Commit', '?')})",
        )
        for row in data if isinstance(row, dict)
    ]


def pip_audit_findings(repo: Path, *, runner: CommandRunner = run_command) -> list[SecurityFinding]:
    """`uv run pip-audit --format json` — audit dependency CỤC BỘ (bổ sung cho Dependabot, thấy cả gói chỉ
    khoá trong `uv.lock`). `tail=None` vì output là JSON phải parse nguyên vẹn.

    QUYẾT ĐỊNH ĐÃ GHI (`sc-security`: "cố ý hay bỏ sót — không im lặng để đó"): CỐ Ý ra mạng khi chạy THẬT, và
    đây là ĐIỂM DUY NHẤT của `keeper` được phép làm vậy. Hai lý do gộp lại: (1) `uv run` tự cài `pip-audit`
    nếu máy chưa có — không có nó thì tool "vắng mặt" và nhánh `MISSING_EXIT` bên dưới chạy, không phải lỗi;
    (2) một khi có `pip-audit`, bản thân công cụ TRA cơ sở dữ liệu lỗ hổng (PyPI Advisory / OSV) — dữ liệu đó
    đổi mỗi ngày, cache cục bộ là dữ liệu CŨ, và `security-auditor` tồn tại để báo lỗ hổng MỚI chứ không phải
    lỗ hổng của tuần trước. Không thêm cờ offline: một audit bảo mật chạy offline là một audit không đo được
    gì mới. Test không chạm mạng (runner giả, `AGENTS.md` cấm §4) — chỉ mã SẢN PHẨM mới ra mạng, và chỉ ở
    hàm này."""
    r = runner(("uv", "run", "pip-audit", "--format", "json"), repo, tail=None)
    if r.exit_code == MISSING_EXIT:
        return []
    data = _load_json(r.output_tail)
    if not isinstance(data, dict):
        return _tool_error("pip-audit", "dependency", f"exit {r.exit_code}, output không phải JSON: {r.output_tail}")
    out: list[SecurityFinding] = []
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            out.append(SecurityFinding(
                subject=f"{dep.get('name', '?')}=={dep.get('version', '?')}",
                severity=DEFAULT_SEVERITY,  # pip-audit không trả mức; `triager` xếp hạng sau
                kind="dependency",
                detail=f"{vuln.get('id', '?')}: {vuln.get('description', '')}",
            ))
    return out


def dependabot_findings(gh: SecuritySource) -> list[SecurityFinding]:
    """Alert Dependabot ĐANG MỞ. Alert đã `fixed`/`dismissed` không phải việc phải làm. `gh` không trả lời
    (`None`) → lỗi công cụ, như gitleaks/pip-audit — xem docstring module."""
    alerts = gh.dependabot_alerts()
    if alerts is None:
        return _tool_error("dependabot", "dependency", _GH_UNKNOWN)
    return [
        SecurityFinding(subject=f"dependabot-{a.number}", severity=_severity(a.severity),
                        kind="dependency", detail=a.summary)
        for a in alerts if a.state == "open"
    ]


def scorecard_findings(gh: SecuritySource) -> list[SecurityFinding]:
    """Alert code scanning ĐANG MỞ mà rule là một check của Scorecard — xem docstring module."""
    alerts = gh.code_scanning_alerts()
    if alerts is None:
        return _tool_error("code-scanning", "scorecard", _GH_UNKNOWN)
    out: list[SecurityFinding] = []
    for a in alerts:
        if a.state != "open":
            continue
        check = a.rule_description.split(":", 1)[0].strip()
        if check in SCORECARD_CHECKS:
            out.append(SecurityFinding(subject=check, severity=_severity(a.severity),
                                       kind="scorecard", detail=a.rule_description))
    return out


def audit(
    repo: Path, gh: SecuritySource, *, runner: CommandRunner = run_command,
) -> list[SecurityFinding]:
    """Cả ba nguồn, một lượt. Thứ tự: bí mật → dependency → scorecard (nặng nhất trước, để đọc log là thấy)."""
    return (
        gitleaks_findings(repo, runner=runner)
        + dependabot_findings(gh)
        + pip_audit_findings(repo, runner=runner)
        + scorecard_findings(gh)
    )
