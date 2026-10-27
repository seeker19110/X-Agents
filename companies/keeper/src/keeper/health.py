"""`health-monitor` (BT3, `DAC-TA-KEEPER.md` §5): flake rate, thời gian CI p50/p95, tuổi PR mở, độ trôi
coverage giữa package.

Thời gian CI đo từ `WorkflowRun.startedAt` tới `.updatedAt` (tên trường thật của `gh run list --json` — kiểm
bằng `gh run list --json bogus`, xem `github.py:WorkflowRun`). Chỉ lấy run hoàn tất success/failure; run huỷ,
chưa hoàn tất hay thiếu một trong hai mốc bị LOẠI khỏi mẫu — không coi là 0 giây. Mẫu rỗng sau khi loại → `None`,
không phải `0.0`: `0.0` đọc thành "CI nhanh vô hạn", `None` đọc thành "chưa đo được"; lẫn hai thứ là đúng khuôn
"số xanh vì rỗng" đã ghi trong `TRAPS.md` gốc repo.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .events import Signal
from .github import PullRequest, WorkflowRun

# Ngưỡng độ trôi coverage giữa hai package coi là đáng báo (điểm phần trăm line-rate).
COVERAGE_DRIFT_THRESHOLD = 0.05


class GitHubLike(Protocol):
    def workflow_runs(self) -> list[WorkflowRun]: ...
    def open_prs(self) -> list[PullRequest] | None: ...
    def pr_age_days(self, pr: int, *, now: object = None) -> float | None: ...


def _completed_outcome(run: WorkflowRun) -> bool:
    return run.status == "completed" and run.conclusion in {"success", "failure"}


def _flake_counts(runs: list[WorkflowRun]) -> tuple[int, int]:
    """(nhóm không ổn định, nhóm đủ mẫu); gh run list không cung cấp matrix hay nguyên nhân lỗi.

    Khoá theo SHA + workflow ID + event, không theo tên hiển thị. Một databaseId chỉ là MỘT mẫu: run-list
    chỉ có trạng thái hiện tại, không đủ dữ liệu tách các attempt cũ. Không suy matrix từ tên workflow.
    """
    groups: dict[tuple[str, int, str], dict[int, str | None]] = {}
    for run in runs:
        if (not _completed_outcome(run) or not run.headSha or run.workflowDatabaseId is None
                or run.workflowDatabaseId <= 0 or not run.event):
            continue
        key = (run.headSha, run.workflowDatabaseId, run.event)
        groups.setdefault(key, {})[run.databaseId] = run.conclusion
    comparable = [set(outcomes.values()) for outcomes in groups.values() if len(outcomes) >= 2]
    return sum(len(outcomes) > 1 for outcomes in comparable), len(comparable)


def flake_rate(runs: list[WorkflowRun]) -> float | None:
    """Tỉ lệ nhóm workflow có cả success/failure, không phải tỉ lệ flaky test đã xác minh.

    Chỉ dùng run hoàn tất, cùng SHA/workflow ID/event và ít nhất hai run ID khác nhau. Thiếu danh tính,
    chưa hoàn tất, huỷ hay timeout không vào mẫu; thiếu mẫu trả None, không phải 0. Chưa phân biệt matrix
    và lỗi hạ tầng vì run-list không có dữ liệu đó.
    """
    unstable, comparable = _flake_counts(runs)
    return unstable / comparable if comparable else None


def flake_signal(runs: list[WorkflowRun]) -> Signal | None:
    unstable, comparable = _flake_counts(runs)
    if not unstable:
        return None
    return Signal(subject="ci-workflow", kind="health",
                  detail=f"flake rate (workflow không ổn định, chưa xác nhận test flake) = {unstable / comparable:.2f}",
                  evidence=f"workflow_runs()={len(runs)}; comparable={comparable}; unstable={unstable}; "
                           "matrix/infra chưa phân loại")


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _run_duration_seconds(run: WorkflowRun) -> float | None:
    """Thời lượng run hoàn tất success/failure, `startedAt` -> `updatedAt`; None nếu không thuộc mẫu, thiếu
    mốc, mốc hỏng hay thời lượng âm (đồng hồ ngược — dữ liệu hỏng, không phải "đo được 0")."""
    if not _completed_outcome(run):
        return None
    started = _parse_ts(run.startedAt)
    updated = _parse_ts(run.updatedAt)
    if started is None or updated is None:
        return None
    delta = (updated - started).total_seconds()
    if delta < 0:
        return None
    return delta


def _percentile(sorted_values: list[float], p: float) -> float:
    """Nội suy tuyến tính kiểu "linear" của numpy / R-7 của R: `idx = (n-1)*p`, giá trị là nội suy tuyến tính
    giữa hai phần tử liền kề tại `idx`. Chọn cách này vì nó là mặc định của `numpy.percentile` — người đọc số
    p95 ở đây quen với cách tính đó nhất, và trên mẫu nhỏ (vài chục run một chu kỳ watch) các phương pháp nội
    suy percentile khác (nearest-rank, midpoint...) cho ra số KHÁC NHAU đáng kể; không nêu rõ cách chọn thì số
    p95 rất dễ bị đọc sai là "chính xác" khi nó chỉ là một trong nhiều lựa chọn hợp lý."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    idx = (n - 1) * p
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def ci_duration_stats(runs: list[WorkflowRun]) -> tuple[float, float] | None:
    """(p50, p95) thời lượng CI bằng giây trên run hoàn tất success/failure ĐỦ HAI mốc `startedAt`/`updatedAt`.
    Run ngoài mẫu hoặc thiếu mốc không đóng góp gì (không phải 0 giây). Mẫu rỗng sau khi loại -> `None`
    (chưa đo được), không phải `(0.0, 0.0)` (sẽ đọc nhầm thành CI nhanh vô hạn)."""
    durations = sorted(d for r in runs if (d := _run_duration_seconds(r)) is not None)
    if not durations:
        return None
    return _percentile(durations, 0.50), _percentile(durations, 0.95)


def ci_duration_signal(runs: list[WorkflowRun]) -> Signal | None:
    stats = ci_duration_stats(runs)
    if stats is None:
        return None
    p50, p95 = stats
    return Signal(subject="ci-workflow", kind="health", detail=f"thời gian CI p50={p50:.1f}s p95={p95:.1f}s",
                  evidence=f"workflow_runs()={len(runs)}")


def pr_age_signals(gh: GitHubLike, *, max_age_days: float = 7.0) -> list[Signal]:
    """Một `Signal` cho mỗi PR mở lâu hơn `max_age_days`."""
    out: list[Signal] = []
    # `None` (gh không trả lời) → không có tín hiệu tuổi PR: đây chỉ là quan sát, không mở cổng nào. Cổng
    # cần fail closed là `budget.can_open_pr`, nó tự xử lý `None`.
    for pr in gh.open_prs() or []:
        age = gh.pr_age_days(pr.number)
        if age is not None and age > max_age_days:
            out.append(Signal(subject=f"pr-{pr.number}", kind="health",
                               detail=f"PR mở {age:.1f} ngày (> {max_age_days})", evidence=pr.url))
    return out


def _line_rate(path: Path) -> float | None:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    raw = root.attrib.get("line-rate")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def coverage_drift_signals(repo: Path, *, threshold: float = COVERAGE_DRIFT_THRESHOLD) -> list[Signal]:
    """Đọc mọi `coverage.xml` dưới `repo` (một per package theo khuôn CI hiện có); nếu có từ hai file trở lên
    và chênh lệch `line-rate` cao nhất-thấp nhất vượt `threshold` → một `Signal`. Không có/không đủ file →
    rỗng, không đoán."""
    rates: dict[str, float] = {}
    for path in sorted(repo.rglob("coverage.xml")):
        if ".venv" in path.parts:
            continue
        rate = _line_rate(path)
        if rate is not None:
            rates[str(path.relative_to(repo))] = rate
    if len(rates) < 2:
        return []
    hi_path, hi = max(rates.items(), key=lambda kv: kv[1])
    lo_path, lo = min(rates.items(), key=lambda kv: kv[1])
    if hi - lo <= threshold:
        return []
    return [Signal(subject="coverage-drift", kind="health",
                    detail=f"{hi_path}={hi:.3f} vs {lo_path}={lo:.3f} (lệch {hi - lo:.3f} > {threshold})",
                    evidence=f"{len(rates)} coverage.xml")]


def scan(repo: Path, gh: GitHubLike) -> list[Signal]:
    out: list[Signal] = []
    runs = gh.workflow_runs()
    if sig := flake_signal(runs):
        out.append(sig)
    if sig := ci_duration_signal(runs):
        out.append(sig)
    out += pr_age_signals(gh)
    out += coverage_drift_signals(repo)
    return out
