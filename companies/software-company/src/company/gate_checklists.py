"""Parser `gates/checklists.md` + bảng nguồn bằng chứng cho nửa "Người tự kiểm thêm" của mỗi gate.

Một nguồn sự thật cho hai người dùng (đặc tả `docs/dac-ta-tro-ly-kiem-duyet.md` §4.4 và §5):

- `company.subagents` sinh `.claude/agents/sc-gate-<kind>.md`: mỗi mục "Người tự kiểm thêm" thành một đề mục
  bắt buộc trả lời, kèm nguồn bằng chứng lấy từ `SELF_CHECK_SOURCES`.
- `company.gate_brief` rút bằng chứng thật từ bus/blackboard theo đúng các `id` trong bảng đó.

Parser phải GÃY TO khi `checklists.md` đổi cấu trúc (thiếu "Code gửi kèm:", thiếu "Người tự kiểm thêm:", kind lạ,
tập kind không khớp `GateKind`, hay một mục tự kiểm chưa có nguồn bằng chứng): raise, không đoán. Bản dẫn xuất
lệch nguồn nghĩa là người duyệt đang chấm theo checklist khác checklist công ty thực sự dùng.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from .gates import GateKind
from .registry import ROOT
from .roles import ROLE

CHECKLISTS = ROOT / "gates" / "checklists.md"

_GATE_H2 = re.compile(r"^## +Gate\b.*$", re.MULTILINE)
_KIND = re.compile(r"kind\s+`([a-z]+)`")
_SUBJECT = re.compile(r"subject\s*=?\s*`?([^`\)]+?)`?\)")
_CODE_ITEM = re.compile(r"^- \[ \] `([^`]+)` — (.+?)\s*$")
_SELF_ITEM = re.compile(r"^- \[ \] (.+?)\s*$")
CODE_HEAD, SELF_HEAD = "Code gửi kèm:", "Người tự kiểm thêm:"


@dataclass(frozen=True)
class CodeItem:
    key: str      # khoá trong `GateRequest.checklist`, hiện trong `gate_cli list`
    text: str


@dataclass(frozen=True)
class SelfItem:
    id: str                    # id ổn định dùng trong JSON hồ sơ (`self_check[].id`)
    text: str                  # nguyên văn mục trong checklists.md
    sources: tuple[str, ...]   # nguồn bằng chứng (§5.3–5.6), để trợ lý biết đi đâu tìm


@dataclass(frozen=True)
class GateSection:
    kind: str
    title: str        # dòng H2 nguyên văn (không có `## `)
    subject: str      # dạng subject: `SPEC-<project>`, `<release_id>`, `UAT-<release_id>`, `ticket_id`
    code: tuple[CodeItem, ...]
    self_checks: tuple[SelfItem, ...]


# §5.3–5.6: mỗi mục "Người tự kiểm thêm" → (id, nguồn bằng chứng). Khoá là NGUYÊN VĂN mục trong checklists.md,
# nên đổi chữ trong checklist mà quên đổi ở đây thì parser gãy — có chủ ý: mục không có nguồn thì trợ lý chỉ
# trả `unknown` được, và hồ sơ không rút được gì cho nó.
SELF_CHECK_SOURCES: dict[str, dict[str, tuple[str, tuple[str, ...]]]] = {
    "spec": {
        "NFR có số đo": ("spec.nfr-co-so-do", (
            "prd@latest — mục NFR/phi chức năng: dòng có ngưỡng và đơn vị (ms, s, %, rps, p95, MB, người dùng)",)),
        "Out-of-scope rõ": ("spec.out-of-scope", (
            "prd@latest — heading `Out of scope` / `Ngoài phạm vi` / `Không làm` và ≥ 1 mục dưới nó",)),
        "PII đã phân loại; DPIA có nếu cần": ("spec.pii", (
            "prd@latest — nhắc tới pii / dữ liệu cá nhân / CCCD / email / số điện thoại",
            "threat-model@latest — bảng phân loại dữ liệu, DPIA",
            "tasks — ticket mang risk_tags `pii`")),
        "Câu hỏi mở chỉ còn assumption đã ghi nhận": ("spec.cau-hoi-mo", (
            "clarification-questions và clarification-answers theo project_id — câu hỏi chưa có answer khớp question_id",)),
        "Có runtime chạy được: `kind` khai rõ; ứng dụng có lệnh khởi động, cổng, đường health và phụ thuộc ngoài": (
            "spec.runtime", (
                "approved-specs@latest theo project_id — payload.kind; payload.runtime.command/port/health/dependencies "
                "(ADR-0031; orchestrator đọc bằng `smoke.parse_runtime`)",
                "prd@latest — mục 8b `Chạy ở đâu`: lệnh, cổng, health, phụ thuộc ngoài khớp payload",
                "audit-log `spec.runtime_missing` theo project_id — số lần spec bị trả lại vì thiếu runtime")),
    },
    "release": {
        # Gate release ký TRƯỚC khi `_deliver()` chạy, nên thứ kiểm được ở đây là *có giao được không*, không
        # phải *đã giao chưa*. Sự cố 2026-09-10: ký xong mới biết tiến trình chạy thiếu `--deliver`.
        "Tiến trình đang chạy giao hàng được (`--deliver`)": ("release.giao-hang-duoc", (
            "trạng thái tiến trình orchestrator — cờ `--deliver` và `--push-remote` lúc khởi động (ADR-0027); "
            "console bật động cơ thì là `--deliver-remote` của `python -m console`",)),
        "Dashboard + alert (có runbook) cho dịch vụ/tính năng mới": ("release.dashboard-alert", (
            "api-contract@latest — endpoint/dịch vụ trong contract",
            "infra@latest — dashboard/alert/runbook có nhắc tới endpoint đó",
            "docs@latest — runbook")),
        "Changelog, docs, NOTICE cập nhật": ("release.changelog-docs-notice", (
            "worktree nhánh tích hợp — `git diff --name-only <base>..<integration>`: CHANGELOG*, docs/, NOTICE*; "
            "lockfile đổi mà NOTICE không đổi",)),
        "Error budget không âm": ("release.error-budget", (
            "incidents — SEV1/SEV2 trong 30 ngày của dự án",
            "release-events — rolled_back / failed",
            "repo không định nghĩa SLO → `unavailable`, không đoán")),
        "Người duyệt ≠ người tạo release": ("release.four-eyes", (
            "GateRequest.created_by — code từ chối khi decided_by trùng created_by",)),
        # Hai mục dưới dời từ gate `plan` cũ (ADR-0037). `id` giữ nguyên tiền tố `plan.` CÓ CHỦ Ý: hồ sơ
        # gate_brief đã ghi ra đĩa trước đây dùng đúng id này, đổi là hồ sơ cũ không đọc lại được.
        "Ước lượng có cơ sở (tham chiếu `knowledge` hoặc PERT)": ("plan.uoc-luong-co-so", (
            "knowledge — bài học estimate-vs-actual, hệ số hiệu chỉnh theo assignee",
            "audit-log `plan.proposed` — estimate_tokens từng ticket, phân bố min/median/max")),
        "Ngân sách token cho dự án được đặt; tổng estimate ≤ ngân sách": ("plan.ngan-sach-token", (
            "audit-log `plan.proposed` — sum(estimate_tokens), sum(budget_tokens) của plan",
            "front matter agents/ — budget_tokens_per_task của từng assignee",
            "llm.yaml `budget_usd` / `orchestrator metrics` — trần tiền của dự án")),
    },
    "acceptance": {
        "Chạy trên bản production (hoặc staging nếu hợp đồng quy định) với dữ liệu khách chấp thuận": (
            "acceptance.moi-truong", (
                "release-events — env/status mới nhất của release",
                "contract@latest — điều khoản dữ liệu và môi trường UAT")),
        "Finding truy vết về requirement_id; yêu cầu ngoài spec đi vào `change-requests`, không vào biên bản": (
            "acceptance.truy-vet", (
                "acceptance-results — finding thiếu requirement_id (`REQ-…`)",
                "prd@latest — danh sách requirement_id",
                "change-requests — CR sinh từ nghiệm thu")),
        "Sản phẩm khởi động được và trả lời một request thật — `gate_brief` tự chạy theo `runtime` của spec (ADR-0029), "
        "khách ký trên thứ đã chạy chứ không trên lời khai `deployed`": (
            "acceptance.da-chay", (
                "approved-specs@latest — `runtime` (lệnh khởi động, cổng, đường health); thiếu thì KHÔNG THỂ CHẠY, hồ sơ nói thẳng",
                "worktree tích hợp (`--repo`) — `gate_brief` khởi động sản phẩm ở đó và gọi một request thật: lệnh, mã thoát, "
                "mã HTTP, `verified_by=orchestrator` (mục \"Đã chạy\" của hồ sơ)",
                "release-events{staging}.smoke — lần orchestrator tự chạy lúc deploy staging, để đối chiếu")),
        "Khách đã xem bản giao trong PR thật trên GitHub (`--deliver-pr`, ADR-0038): PR nhánh release → nhánh của khách "
        "do orchestrator mở, không merge — review bằng UI quen thuộc rồi mới ký": (
            "acceptance.pr-giao-hang", (
                "audit-log delivery.done — trường `pr` (url, số PR, base ← head) của release; `delivery.pr_skipped`/"
                "`pr_failed` kèm lý do; chưa bật `--deliver-pr` thì `unknown`, khách xem tag/nhánh release trực tiếp",)),
        # 3b (báo cáo 2026-10-10-doi-chieu-tu-van-da-dang.md, từ "Cross-Cutting Probes" của lens-skill): bus không mang
        # bằng chứng cho hai câu này, nên `gate_brief` trả `unknown` kèm chỗ phải đọc — người/trợ lý đọc mã thật.
        "Mỗi file/khoá cấu hình/trường mới mà bản giao sinh ra có ít nhất một nơi đọc trong mã — trỏ dòng"
        " (sự cố QLKH: `runtime.yaml` sinh ra mà không ai đọc)": (
            "acceptance.noi-doc", (
                "worktree tích hợp (`--repo`) — `git diff --name-only <tag trước>..<tag release>`: file mới, khoá cấu hình mới",
                "pull-requests của các ticket trong release — trường/khoá mới khai trong summary",
                "grep tên file/khoá trong mã của bản giao: phải có ít nhất một dòng ĐỌC (không chỉ dòng ghi), trỏ file:dòng")),
        "Không khả năng nào README/spec đã hứa đứng sau stub"
        " (hàm trả giá trị cố định, thân `TODO`/`NotImplementedError`, module không ai gọi)": (
            "acceptance.khong-stub", (
                "README của bản giao + approved-specs@latest — danh sách khả năng đã hứa",
                "worktree tích hợp (`--repo`) — grep `NotImplementedError`, `TODO`, `pass`, `return None|[]|{}` trong hàm "
                "mà khả năng đó đi qua; module không ai import",)),
    },
    "escalation": {
        "Ngân sách còn": ("escalation.ngan-sach", (
            "audit-log theo ticket_id — output_tokens đã dùng so với budget_tokens (Supervisor.Budget)",
            "supervisor-actions — budget_cut / escalate / warn của ticket",
            "audit-log `budget.extended` — lần cấp thêm trước")),
    },
}

# §5.6: kind → trợ lý chuyên môn nên gọi cùng hồ sơ.
EXPERTS: dict[str, tuple[str, ...]] = {
    "spec": (f"sc-{ROLE.PRODUCT}", f"sc-{ROLE.SECURITY}"),
    "release": (f"sc-{ROLE.QA}", f"sc-{ROLE.SECURITY}", f"sc-{ROLE.OPS}", f"sc-{ROLE.PRODUCT}"),
    "acceptance": (f"sc-{ROLE.OPS}",),
    "escalation": (f"sc-{ROLE.QA}", f"sc-{ROLE.BUILDER}"),  # ADR-0037: một agent viết code, không còn "sc-<assignee>"
}

# Gate đóng bằng tiền thật (production, khách ký) dùng model mạnh; còn lại standard.
GATE_MODEL: dict[str, str] = {"release": "opus", "acceptance": "opus"}


def _items(block: str, head: str, rx: re.Pattern[str], kind: str) -> list[re.Match[str]]:
    """Các dòng `- [ ]` ngay dưới dòng `head` (tới dòng đầu tiên không phải mục)."""
    lines = block.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith(head))
    except StopIteration:
        raise ValueError(f"gate {kind!r}: thiếu dòng {head!r} trong checklists.md") from None
    out: list[re.Match[str]] = []
    for ln in lines[start + 1:]:
        m = rx.match(ln)
        if m is None:
            if out: break
            if ln.strip() == "": continue
            raise ValueError(f"gate {kind!r}: dưới {head!r} là {ln!r}, không phải mục `- [ ]`")
        out.append(m)
    if not out:
        raise ValueError(f"gate {kind!r}: {head!r} không có mục nào")
    return out


def parse(text: str | None = None) -> dict[str, GateSection]:
    """`checklists.md` → {kind: GateSection}. Raise ValueError khi cấu trúc lệch (xem docstring module)."""
    text = CHECKLISTS.read_text(encoding="utf-8") if text is None else text
    marks = list(_GATE_H2.finditer(text))
    if not marks:
        raise ValueError("checklists.md: không có mục `## Gate` nào")
    out: dict[str, GateSection] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[m.end():end]
        # mục con (`### ...`) thuộc về gate nhưng không chứa checklist: cắt để parser không đọc nhầm
        block = block.split("\n### ", 1)[0]
        title = m.group(0)[3:].strip()
        km = _KIND.search(title)
        if km is None:
            raise ValueError(f"checklists.md: tiêu đề gate không nêu kind: {title!r}")
        kind = km.group(1)
        if kind not in get_args(GateKind):
            raise ValueError(f"checklists.md: kind lạ {kind!r} (GateKind = {get_args(GateKind)})")
        if kind in out:
            raise ValueError(f"checklists.md: kind {kind!r} xuất hiện hai lần")
        sm = _SUBJECT.search(title)
        subject = sm.group(1).strip() if sm else "?"
        code = tuple(CodeItem(x.group(1), x.group(2)) for x in _items(block, CODE_HEAD, _CODE_ITEM, kind))
        table = SELF_CHECK_SOURCES.get(kind, {})
        selfs = []
        for x in _items(block, SELF_HEAD, _SELF_ITEM, kind):
            txt = x.group(1)
            if txt not in table:
                raise ValueError(f"gate {kind!r}: mục tự kiểm {txt!r} chưa có nguồn bằng chứng trong "
                                 f"SELF_CHECK_SOURCES (gate_checklists.py) — thêm id + nguồn trước")
            sid, sources = table[txt]
            selfs.append(SelfItem(sid, txt, sources))
        extra = sorted(set(table) - {s.text for s in selfs})
        if extra:
            raise ValueError(f"gate {kind!r}: SELF_CHECK_SOURCES có mục không còn trong checklists.md: {extra}")
        out[kind] = GateSection(kind, title, subject, code, tuple(selfs))
    missing = sorted(set(get_args(GateKind)) - set(out))
    if missing:
        raise ValueError(f"checklists.md thiếu gate cho kind {missing}")
    return out


def load(path: Path | None = None) -> dict[str, GateSection]:
    return parse((path or CHECKLISTS).read_text(encoding="utf-8"))
