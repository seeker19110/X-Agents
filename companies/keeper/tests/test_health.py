from datetime import datetime
from pathlib import Path

import pytest

from keeper import health
from keeper.fakes import FakeGitHub
from keeper.github import WorkflowRun


def _run(sha: str, conclusion: str | None, *, name: str = "ci", db: int = 1,
         workflow: int | None = 1, event: str = "push", status: str = "completed") -> WorkflowRun:
    return WorkflowRun(databaseId=db, name=name, status="completed", conclusion=conclusion, headSha=sha,
                       createdAt="2026-09-08T00:00:00Z", workflowDatabaseId=workflow,
                       event=event).model_copy(update={"status": status})


def _timed_run(started: str | None, updated: str | None, *, db: int = 1) -> WorkflowRun:
    return WorkflowRun(databaseId=db, name="ci", status="completed", conclusion="success", headSha=f"sha{db}",
                        createdAt="2026-09-08T00:00:00Z", startedAt=started, updatedAt=updated)


def test_ci_duration_p50_p95_tinh_tay() -> None:
    # 4 run, thời lượng (giây): 10, 20, 30, 40 — tính từ startedAt tới updatedAt.
    # Nội suy tuyến tính (kiểu numpy "linear" / R-7): idx = (n-1)*p.
    # p50: idx=(4-1)*0.5=1.5 -> giữa vals[1]=20 và vals[2]=30 -> 20+0.5*(30-20)=25.0
    # p95: idx=(4-1)*0.95=2.85 -> giữa vals[2]=30 và vals[3]=40 -> 30+0.85*(40-30)=38.5
    runs = [
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:10Z", db=1),
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:20Z", db=2),
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:30Z", db=3),
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:40Z", db=4),
    ]
    stats = health.ci_duration_stats(runs)
    assert stats is not None
    p50, p95 = stats
    assert p50 == 25.0
    assert p95 == 38.5


def test_ci_duration_run_thieu_moc_bi_loai() -> None:
    # 3 run đủ mốc: 10, 20, 30 giây. Một run thứ tư thiếu updatedAt (chưa chạy xong) phải bị LOẠI khỏi mẫu.
    # Chiều ngược: so kết quả tính TRÊN đúng 3 run đủ mốc với kết quả tính khi CÓ thêm run thiếu mốc — phải
    # giống hệt nhau, chứng minh việc loại có tác dụng thật (không lặng lẽ lọt vào mẫu).
    complete = [
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:10Z", db=1),
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:20Z", db=2),
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:30Z", db=3),
    ]
    incomplete = _timed_run("2026-09-08T00:00:00Z", None, db=4)

    stats_full_sample = health.ci_duration_stats(complete)
    stats_with_incomplete = health.ci_duration_stats([*complete, incomplete])

    assert stats_full_sample is not None
    assert stats_with_incomplete is not None
    assert stats_with_incomplete == stats_full_sample
    # Khác với việc coi thiếu mốc là 0 giây (0.0 là "CI nhanh vô hạn", sai với thực tế "chưa đo được") —
    # nếu loại không có tác dụng, run thiếu mốc sẽ kéo p50 xuống gần 0, và test trên đã chặn điều đó.
    p50, _ = stats_full_sample
    assert p50 != 0.0


def test_ci_duration_run_thieu_startedAt_bi_loai() -> None:
    complete = [
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:10Z", db=1),
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:20Z", db=2),
    ]
    incomplete = _timed_run(None, "2026-09-08T00:00:05Z", db=3)
    assert health.ci_duration_stats([*complete, incomplete]) == health.ci_duration_stats(complete)


def test_ci_duration_mau_rong_tra_none() -> None:
    # Mẫu rỗng -> None, KHÔNG PHẢI 0.0. 0.0 là "CI nhanh vô hạn"; None là "chưa đo được".
    assert health.ci_duration_stats([]) is None


def test_ci_duration_toan_bo_run_thieu_moc_tra_none() -> None:
    runs = [_timed_run("2026-09-08T00:00:00Z", None, db=1), _timed_run(None, None, db=2)]
    assert health.ci_duration_stats(runs) is None


def test_ci_duration_signal_bao_gom_p50_p95() -> None:
    runs = [
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:10Z", db=1),
        _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:20Z", db=2),
    ]
    sig = health.ci_duration_signal(runs)
    assert sig is not None
    assert "p50" in sig.detail and "p95" in sig.detail


def test_ci_duration_signal_mau_rong_im() -> None:
    assert health.ci_duration_signal([]) is None


def test_ci_duration_moc_hong_khong_parse_duoc_bi_loai() -> None:
    ok = _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:10Z", db=1)
    hong = _timed_run("khong-phai-ngay-gio", "2026-09-08T00:00:05Z", db=2)
    assert health.ci_duration_stats([ok, hong]) == health.ci_duration_stats([ok])


def test_ci_duration_thoi_luong_am_bi_loai() -> None:
    # updatedAt trước startedAt (đồng hồ ngược / dữ liệu hỏng) -> loại, không coi là 0.
    ok = _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:10Z", db=1)
    am = _timed_run("2026-09-08T00:00:10Z", "2026-09-08T00:00:00Z", db=2)
    assert health.ci_duration_stats([ok, am]) == health.ci_duration_stats([ok])


def test_flake_rate_cung_sha_khac_ket_qua() -> None:
    runs = [_run("abc", "success", db=1), _run("abc", "failure", db=2)]
    assert health.flake_rate(runs) > 0
    assert health.flake_rate(runs) == 1.0


def test_flake_rate_cung_sha_cung_ket_qua_la_khong() -> None:
    runs = [_run("abc", "success", db=1), _run("abc", "success", db=2)]
    assert health.flake_rate(runs) == 0.0


def test_flake_rate_khong_co_run_lap_lai() -> None:
    runs = [_run("abc", "success", db=1), _run("def", "success", db=2)]
    assert health.flake_rate(runs) is None


def test_flake_rate_danh_sach_rong() -> None:
    assert health.flake_rate([]) is None


@pytest.mark.parametrize("second", [
    {"workflow": 2}, {"event": "pull_request"}, {"status": "in_progress"}, {"status": "queued"},
])
def test_flake_rate_does_not_pool_different_or_unfinished_workflows(second: dict) -> None:
    runs = [_run("abc", "success", db=1), _run("abc", "failure", db=2, **second)]
    assert health.flake_rate(runs) is None
    assert health.flake_signal(runs) is None


@pytest.mark.parametrize("conclusion", [None, "cancelled", "timed_out", "startup_failure", "action_required",
                                         "neutral", "skipped", "stale"])
def test_flake_rate_excludes_non_test_outcomes(conclusion: str | None) -> None:
    assert health.flake_rate([_run("abc", "success", db=1), _run("abc", conclusion, db=2)]) is None


@pytest.mark.parametrize("missing", [{"workflow": None}, {"workflow": 0}, {"event": ""}])
def test_flake_rate_missing_comparison_identity_is_unknown(missing: dict) -> None:
    assert health.flake_rate([_run("abc", "success", db=1, **missing),
                              _run("abc", "failure", db=2, **missing)]) is None


def test_flake_rate_missing_sha_is_unknown() -> None:
    assert health.flake_rate([_run("", "success", db=1), _run("", "failure", db=2)]) is None


def test_flake_rate_counts_comparable_workflow_groups_not_shas() -> None:
    runs = [_run("abc", "success", db=1), _run("abc", "failure", db=2),
            _run("abc", "success", db=3, workflow=2), _run("abc", "success", db=4, workflow=2)]
    assert health.flake_rate(runs) == .5
    signal = health.flake_signal(runs)
    assert signal is not None
    assert "workflow" in signal.detail and "test flake" in signal.detail
    assert "comparable=2" in signal.evidence and "unstable=1" in signal.evidence
    assert "matrix" in signal.evidence and "infra" in signal.evidence


def test_flake_rate_duplicate_run_is_not_an_independent_sample() -> None:
    assert health.flake_rate([_run("abc", "success", db=1), _run("abc", "failure", db=1)]) is None


def test_flake_rate_display_name_does_not_replace_stable_workflow_identity() -> None:
    assert health.flake_rate([_run("abc", "success", db=1, name="old name"),
                              _run("abc", "failure", db=2, name="new name")]) == 1.0


@pytest.mark.parametrize(("status", "conclusion"), [("in_progress", "success"), ("queued", "success"),
                                                       ("completed", "cancelled")])
def test_ci_duration_excludes_unfinished_or_cancelled_runs(status: str, conclusion: str) -> None:
    complete = _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:10Z")
    excluded = _timed_run("2026-09-08T00:00:00Z", "2026-09-08T00:00:50Z", db=2)
    excluded = excluded.model_copy(update={"status": status, "conclusion": conclusion})
    assert health.ci_duration_stats([complete, excluded]) == (10.0, 10.0)


def test_flake_signal_phat_khi_co_flake() -> None:
    runs = [_run("abc", "success", db=1), _run("abc", "failure", db=2)]
    sig = health.flake_signal(runs)
    assert sig is not None
    assert sig.kind == "health"


def test_flake_signal_im_khi_khong_flake() -> None:
    runs = [_run("abc", "success", db=1), _run("abc", "success", db=2)]
    assert health.flake_signal(runs) is None


class _AgeGitHub(FakeGitHub):
    def __init__(self, age_days: float) -> None:
        super().__init__()
        self._age = age_days

    def pr_age_days(self, pr: int, *, now: datetime | None = None) -> float | None:
        self._count("pr_age_days")
        return self._age


def test_pr_age_signals_qua_han() -> None:
    gh = _AgeGitHub(30.0)
    out = health.pr_age_signals(gh, max_age_days=7.0)
    assert len(out) == 1
    assert out[0].kind == "health"


def test_pr_age_signals_trong_han() -> None:
    gh = _AgeGitHub(1.0)
    assert health.pr_age_signals(gh, max_age_days=7.0) == []


def test_pr_age_signals_gh_khong_biet_thi_khong_no() -> None:
    """`open_prs()` trả `None` (gh hỏng) → không tín hiệu, không `TypeError` giết vòng quét."""
    class _MuGitHub(FakeGitHub):
        def open_prs(self):  # type: ignore[no-untyped-def]
            return None

    assert health.pr_age_signals(_MuGitHub(), max_age_days=7.0) == []


def _write_coverage(repo: Path, rel: str, line_rate: float) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'<?xml version="1.0"?><coverage line-rate="{line_rate}"></coverage>', encoding="utf-8")


def test_coverage_drift_vuot_nguong(tmp_path: Path) -> None:
    _write_coverage(tmp_path, "pkg_a/coverage.xml", 1.0)
    _write_coverage(tmp_path, "pkg_b/coverage.xml", 0.80)
    out = health.coverage_drift_signals(tmp_path, threshold=0.05)
    assert len(out) == 1
    assert out[0].kind == "health"


def test_coverage_drift_trong_nguong(tmp_path: Path) -> None:
    _write_coverage(tmp_path, "pkg_a/coverage.xml", 1.0)
    _write_coverage(tmp_path, "pkg_b/coverage.xml", 0.98)
    assert health.coverage_drift_signals(tmp_path, threshold=0.05) == []


def test_coverage_drift_mot_file_khong_du_so_sanh(tmp_path: Path) -> None:
    _write_coverage(tmp_path, "pkg_a/coverage.xml", 0.5)
    assert health.coverage_drift_signals(tmp_path) == []


def test_coverage_drift_khong_co_file(tmp_path: Path) -> None:
    assert health.coverage_drift_signals(tmp_path) == []


def test_coverage_drift_file_hong_bi_bo_qua(tmp_path: Path) -> None:
    _write_coverage(tmp_path, "pkg_a/coverage.xml", 1.0)
    p = tmp_path / "pkg_b" / "coverage.xml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("khong phai xml", encoding="utf-8")
    assert health.coverage_drift_signals(tmp_path) == []


def test_coverage_drift_khong_co_line_rate(tmp_path: Path) -> None:
    p = tmp_path / "pkg_a" / "coverage.xml"
    p.parent.mkdir(parents=True)
    p.write_text('<?xml version="1.0"?><coverage></coverage>', encoding="utf-8")
    p2 = tmp_path / "pkg_b" / "coverage.xml"
    p2.parent.mkdir(parents=True)
    p2.write_text('<?xml version="1.0"?><coverage line-rate="0.9"></coverage>', encoding="utf-8")
    assert health.coverage_drift_signals(tmp_path) == []


def test_coverage_drift_line_rate_khong_phai_so(tmp_path: Path) -> None:
    p = tmp_path / "pkg_a" / "coverage.xml"
    p.parent.mkdir(parents=True)
    p.write_text('<?xml version="1.0"?><coverage line-rate="khong-phai-so"></coverage>', encoding="utf-8")
    p2 = tmp_path / "pkg_b" / "coverage.xml"
    p2.parent.mkdir(parents=True)
    p2.write_text('<?xml version="1.0"?><coverage line-rate="0.9"></coverage>', encoding="utf-8")
    assert health.coverage_drift_signals(tmp_path) == []


def test_coverage_drift_bo_qua_venv(tmp_path: Path) -> None:
    _write_coverage(tmp_path, "pkg_a/coverage.xml", 1.0)
    _write_coverage(tmp_path, ".venv/lib/coverage.xml", 0.0)
    assert health.coverage_drift_signals(tmp_path) == []


class _FlakyGitHub(FakeGitHub):
    def workflow_runs(self) -> list[WorkflowRun]:
        self._count("workflow_runs")
        return [_run("abc", "success", db=1), _run("abc", "failure", db=2)]


def test_scan_tong_hop(tmp_path: Path) -> None:
    gh = FakeGitHub()
    out = health.scan(tmp_path, gh)
    assert isinstance(out, list)


def test_scan_bao_gom_flake_signal(tmp_path: Path) -> None:
    gh = _FlakyGitHub()
    out = health.scan(tmp_path, gh)
    assert any(s.detail.startswith("flake rate") for s in out)
