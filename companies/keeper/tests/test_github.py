"""BT2: `GitHubReader` chỉ đọc — bất biến I1 (không ghi) + bộ đệm TTL. Đo hai chiều theo `DAC-TA-KEEPER.md` §4:
mỗi ca có ca chiều ngược chứng minh test đang đo đúng cơ chế, không đo thứ khác."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from keeper import github as github_mod
from keeper.github import CACHE_TTL_SECONDS, GitHubReader, GitHubWriteAttempt


class _Clock:
    """Đồng hồ giả điều khiển được — test TTL không cần `sleep` thật."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


class _RunSpy:
    """Thay `subprocess.run`: đếm số lần gọi, trả `CompletedProcess` cố định hoặc ném theo kịch bản."""

    def __init__(self, stdout: str = "[]", returncode: int = 0, raise_exc: Exception | None = None) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.raise_exc = raise_exc
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append(argv)
        if self.raise_exc is not None:
            raise self.raise_exc
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr="")


def _reader(tmp_path: Path, spy: _RunSpy, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> GitHubReader:
    monkeypatch.setattr(github_mod.subprocess, "run", spy)
    return GitHubReader(tmp_path, **kw)


# ---------------------------------------------------------------------------------------------------------
# I1 — không cho ghi


@pytest.mark.parametrize(
    "args",
    [
        ("api", "repos/o/r/issues/1", "-X", "DELETE"),
        ("api", "repos/o/r/issues/1", "--method", "DELETE"),
        ("pr", "merge", "1"),
        ("pr", "close", "1"),
        ("pr", "edit", "1", "--title", "x"),
        ("issue", "close", "1"),
        ("repo", "delete", "o/r"),
    ],
)
def test_khong_cho_ghi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...]) -> None:
    spy = _RunSpy()
    reader = _reader(tmp_path, spy, monkeypatch)
    with pytest.raises(GitHubWriteAttempt):
        reader._run(*args)
    assert spy.calls == []  # bị chặn TRƯỚC khi chạm subprocess


def test_khong_cho_ghi_chieu_nguoc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tắt kiểm FORBIDDEN_ARGS (tạm thời) → cùng lời gọi KHÔNG ném nữa — chứng minh test trên đo đúng cái chặn
    đó, không đo thứ khác."""
    spy = _RunSpy(stdout="[]")
    reader = _reader(tmp_path, spy, monkeypatch)
    monkeypatch.setattr(github_mod, "FORBIDDEN_ARGS", ())
    reader._run("pr", "merge", "1")  # không ném
    assert spy.calls == [["gh", "pr", "merge", "1"]]


def test_khong_chan_nham_gia_tri_co_giong_tu_khoa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Giá trị của một cờ nhận tham số (`--repo`, `--head`...) có thể trùng chữ với một từ cấm mà không phải
    subcommand ghi — không được chặn nhầm."""
    spy = _RunSpy(stdout="[]")
    reader = _reader(tmp_path, spy, monkeypatch)
    reader._run("pr", "list", "--repo", "o/delete-me", "--head", "edit/foo", "--json", "number")
    assert len(spy.calls) == 1


# ---------------------------------------------------------------------------------------------------------
# Bộ đệm TTL


def test_bo_dem_khong_goi_lai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout="[]")
    clock = _Clock(0.0)
    reader = _reader(tmp_path, spy, monkeypatch, cache_ttl=CACHE_TTL_SECONDS, clock=clock)
    reader.open_prs()
    clock.advance(1.0)
    reader.open_prs()
    assert len(spy.calls) == 1  # trong TTL, chỉ gọi subprocess một lần


def test_bo_dem_khong_goi_lai_chieu_nguoc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TTL = 0 → mỗi lần gọi lại chạm subprocess — chứng minh test trên đo đúng bộ đệm."""
    spy = _RunSpy(stdout="[]")
    clock = _Clock(0.0)
    reader = _reader(tmp_path, spy, monkeypatch, cache_ttl=0.0, clock=clock)
    reader.open_prs()
    clock.advance(1.0)
    reader.open_prs()
    assert len(spy.calls) == 2


def test_bo_dem_het_han_goi_lai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout="[]")
    clock = _Clock(0.0)
    reader = _reader(tmp_path, spy, monkeypatch, cache_ttl=60.0, clock=clock)
    reader.open_prs()
    clock.advance(61.0)
    reader.open_prs()
    assert len(spy.calls) == 2


def test_bo_dem_theo_argv_rieng(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bộ đệm khoá theo argv — gọi hai method khác nhau không dùng chung một mục đệm."""
    spy = _RunSpy(stdout="[]")
    clock = _Clock(0.0)
    reader = _reader(tmp_path, spy, monkeypatch, clock=clock)
    reader.open_prs()
    reader.workflow_runs()
    assert len(spy.calls) == 2


# ---------------------------------------------------------------------------------------------------------
# gh vắng mặt / quá giờ / JSON hỏng — không bao giờ ném, không làm đỏ suite


def test_gh_khong_co_tren_may(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(raise_exc=FileNotFoundError())
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.open_prs() is None, "gh vắng mặt = KHÔNG BIẾT số PR mở, không phải 0 (I3 phải đóng)"


def test_gh_co_that_ma_khong_chay_duoc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`gh` CÓ trên máy mà không chạy được (quyền, binary hỏng) ném `OSError` khác `FileNotFoundError`: `_run`
    phải trả `(False, lý do)` như khi vắng mặt, không để ngoại lệ thô thoát ra và giết lượt đọc."""
    spy = _RunSpy(raise_exc=PermissionError(13, "Permission denied", "gh"))
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.open_prs() is None, "gh hỏng = KHÔNG BIẾT số PR mở, không phải 0 (I3 phải đóng)"
    assert reader._run("pr", "list") == (False, "gh: không chạy được (Permission denied)")


def test_gh_qua_thoi_gian(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(raise_exc=subprocess.TimeoutExpired(cmd="gh", timeout=60))
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.workflow_runs() == []


def test_gh_tra_ma_loi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout="", returncode=1)
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.checks(1) == []


def test_json_hong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout="khong-phai-json{{{")
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.open_prs() is None


def test_json_hong_o_ham_doc_khong_phai_cong_thi_rong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hàm đọc chỉ để QUAN SÁT (`workflow_runs`, `checks`) vẫn giữ quy ước cũ: JSON hỏng → `[]`. Phân biệt "không
    biết" là `open_prs`/`merged_prs` (cổng I3) và hai nguồn `audit` dùng để kết luận "không có phát hiện"."""
    spy = _RunSpy(stdout="khong-phai-json{{{")
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.workflow_runs() == []


def test_json_khong_phai_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout=json.dumps({"not": "a list"}))
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.merged_prs("2026-09-01") is None


def test_json_rong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout="")
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.workflow_runs() == []


@pytest.mark.parametrize("spy", [_RunSpy(stdout="", returncode=1), _RunSpy(stdout="khong-phai-json{{{"),
                                 _RunSpy(stdout=""), _RunSpy(raise_exc=FileNotFoundError())],
                         ids=["ma-loi", "json-hong", "rong", "khong-co-gh"])
def test_nguon_cua_security_auditor_phan_biet_khong_biet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         spy: _RunSpy) -> None:
    """Hai nguồn mà `audit` dùng để nói "không có phát hiện" — đọc lỗi thành `[]` là đọc "chưa quét" thành
    "sạch". `None` để `audit` báo lỗi công cụ, như gitleaks/pip-audit."""
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.dependabot_alerts() is None
    assert reader.code_scanning_alerts() is None


def test_gh_loi_merged_prs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout="", returncode=1)
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.merged_prs("2026-09-01") is None


# ---------------------------------------------------------------------------------------------------------
# Từng method parse đúng khi gh trả JSON hợp lệ


def test_open_prs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"number": 1, "title": "t", "url": "u", "headRefName": "h", "createdAt": "2026-09-01T00:00:00Z"}]
    spy = _RunSpy(stdout=json.dumps(rows))
    reader = _reader(tmp_path, spy, monkeypatch)
    out = reader.open_prs()
    assert out[0].number == 1
    assert out[0].headRefName == "h"


def test_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"name": "keeper-unit", "state": "SUCCESS", "link": "l"}]
    spy = _RunSpy(stdout=json.dumps(rows))
    reader = _reader(tmp_path, spy, monkeypatch)
    out = reader.checks(5)
    assert out[0].name == "keeper-unit"
    assert spy.calls[0] == ["gh", "pr", "checks", "5", "--json", "name,state,link"]


def test_dependabot_alerts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"number": 3, "state": "open", "severity": "high", "summary": "s"}]
    spy = _RunSpy(stdout=json.dumps(rows))
    reader = _reader(tmp_path, spy, monkeypatch)
    out = reader.dependabot_alerts()
    assert out[0].severity == "high"


def test_code_scanning_alerts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"number": 4, "state": "open", "severity": "critical", "rule_description": "d"}]
    spy = _RunSpy(stdout=json.dumps(rows))
    reader = _reader(tmp_path, spy, monkeypatch)
    out = reader.code_scanning_alerts()
    assert out[0].rule_description == "d"


def test_workflow_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"databaseId": 7, "name": "ci", "status": "completed", "conclusion": "success", "headSha": "a",
             "createdAt": "2026-09-01T00:00:00Z"}]
    spy = _RunSpy(stdout=json.dumps(rows))
    reader = _reader(tmp_path, spy, monkeypatch)
    out = reader.workflow_runs()
    assert out[0].databaseId == 7


def test_merged_prs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"number": 8, "title": "t", "url": "u", "headRefName": "h", "mergedAt": "2026-09-05T00:00:00Z"}]
    spy = _RunSpy(stdout=json.dumps(rows))
    reader = _reader(tmp_path, spy, monkeypatch)
    out = reader.merged_prs("2026-09-01")
    assert out[0].mergedAt == "2026-09-05T00:00:00Z"
    assert "--search" in spy.calls[0]


def test_pr_age_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import datetime as dt

    spy = _RunSpy(stdout=json.dumps({"createdAt": "2026-09-01T00:00:00Z"}))
    reader = _reader(tmp_path, spy, monkeypatch)
    age = reader.pr_age_days(1, now=dt.datetime(2026, 9, 8, tzinfo=dt.UTC))
    assert age == pytest.approx(7.0)


def test_pr_age_days_gh_loi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout="", returncode=1)
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.pr_age_days(1) is None


def test_pr_age_days_khong_co_createdAt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout=json.dumps({}))
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.pr_age_days(1) is None


def test_pr_age_days_json_hong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout="{{{not json")
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.pr_age_days(1) is None


def test_pr_age_days_khong_phai_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout=json.dumps([1, 2, 3]))
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.pr_age_days(1) is None


def test_pr_age_days_createdat_khong_phai_iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout=json.dumps({"createdAt": "khong-phai-ngay"}))
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.pr_age_days(1) is None


def test_pr_age_days_mac_dinh_now_that(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Không truyền `now` → dùng đồng hồ hệ thống thật (nhánh mặc định), không ném."""
    spy = _RunSpy(stdout=json.dumps({"createdAt": "2020-01-01T00:00:00Z"}))
    reader = _reader(tmp_path, spy, monkeypatch)
    age = reader.pr_age_days(1)
    assert age is not None
    assert age > 0


@pytest.mark.parametrize("argv", [
    ("api", "repos/o/r/pulls/1/merge", "-f", "merge_method=squash"),
    ("api", "repos/o/r/issues/1/comments", "-F", "body=@x.txt"),
    ("api", "repos/o/r/pulls", "--field", "title=x"),
    ("api", "repos/o/r/pulls", "--raw-field", "title=x"),
    ("api", "graphql", "--input", "q.json"),
])
def test_truong_lam_gh_api_thanh_post_cung_bi_chan(argv, tmp_path):
    """`gh api` chuyển sang POST ngay khi có `-f/-F/--field/--raw-field/--input`, KHÔNG cần `-X`. Không chặn
    các cờ đó thì `gh api repos/o/r/pulls/1/merge -f x=y` là một lời gọi GHI lọt qua I1: token "merge" nằm
    TRONG đường dẫn `repos/.../merge` nên phép so khớp tuyệt đối không thấy nó."""
    with pytest.raises(GitHubWriteAttempt):
        GitHubReader(tmp_path)._run(*argv)


@pytest.mark.parametrize("argv", [
    ("api", "repos/o/r/issues/1", "--method=DELETE"),
    ("api", "repos/o/r/issues/1", "-XDELETE"),
    ("api", "repos/o/r/issues/1", "-X=DELETE"),
    ("api", "repos/o/r/issues/1", "-iXPOST"),               # gộp cờ ngắn: -i (bool) rồi -X POST
    ("api", "repos/o/r/pulls/1/merge", "-fmerge_method=squash"),
    ("api", "repos/o/r/issues/1/comments", "-Fbody=@x.txt"),
    ("api", "repos/o/r/pulls", "--field=title=x"),
    ("api", "repos/o/r/pulls", "--raw-field=title=x"),
    ("api", "graphql", "--input=q.json"),
])
def test_co_ghi_dang_dinh_lien_cung_bi_chan(argv, tmp_path, monkeypatch):
    """`gh` (pflag) nhận cờ ở dạng DÍNH LIỀN: `--method=POST`, `-XPOST`, `-fk=v`, `--field=k=v`... So khớp
    tuyệt đối từng token thì các dạng này lọt qua bảng chặn — một lời gọi GHI thủng I1."""
    spy = _RunSpy()
    monkeypatch.setattr(github_mod.subprocess, "run", spy)
    with pytest.raises(GitHubWriteAttempt):
        GitHubReader(tmp_path)._run(*argv)
    assert spy.calls == []


@pytest.mark.parametrize("argv", [
    ("pr", "list", "--json=number", "--jq=.[].number"),
    ("api", "repos/o/r/pulls", "-q.[].number"),               # -q nhận giá trị dính liền, chữ "f"/"X" sau đó là giá trị
    ("api", "repos/o/r/pulls", "-HAccept: application/vnd.github+json"),
    ("pr", "list", "--repo=o/delete-me", "--limit=5"),
    ("pr", "list", "-L5", "--paginate"),                     # cụm cờ ngắn không chứa cờ ghi
])
def test_co_doc_dang_dinh_lien_khong_bi_chan_nham(argv, tmp_path, monkeypatch):
    spy = _RunSpy(stdout="[]")
    monkeypatch.setattr(github_mod.subprocess, "run", spy)
    GitHubReader(tmp_path)._run(*argv)          # không ném
    assert len(spy.calls) == 1


def test_truong_lam_gh_api_thanh_post_chieu_nguoc(monkeypatch, tmp_path):
    """Chiều ngược: bỏ đúng năm cờ trường khỏi bảng chặn → lời gọi ghi ở trên KHÔNG còn bị chặn, chứng minh
    test trên đang đo chính năm cờ đó chứ không đo token "merge"/"delete" sẵn có."""
    spy = _RunSpy()
    monkeypatch.setattr(github_mod, "FORBIDDEN_ARGS", ("-X", "--method", "close", "delete", "edit"))
    monkeypatch.setattr(github_mod.subprocess, "run", spy)
    GitHubReader(tmp_path)._run("api", "repos/o/r/pulls/1/merge", "-f", "merge_method=squash")
    assert len(spy.calls) == 1   # đã CHẠY thật — đúng thứ bảng chặn đầy đủ ngăn được


@pytest.mark.parametrize("argv", [
    ("pr", "create", "--title", "merge", "--body-file", "b.md"),
    ("pr", "create", "--title", "x", "--body-file", "edit"),
    ("pr", "create", "--title", "x", "--label", "delete"),
    ("pr", "create", "--title", "close"),
    ("pr", "create", "-t", "merge", "-b", "x"),
])
def test_gia_tri_cua_co_khong_bi_soi_nhu_subcommand(argv, tmp_path, monkeypatch):
    """Cùng HỌ với `--repo delete-me` đã sửa ở BT2: bảng cấm soi SUBCOMMAND, nên giá trị của một cờ không được
    đem so với bảng đó. Ở đây nó cắn thật — một PR bảo trì có tiêu đề đúng bằng chữ "merge" hoặc nhãn "delete"
    sẽ bị chặn như một lời gọi ghi, trong khi `gh pr create` chính là thứ bất biến I1 CHO PHÉP."""
    spy = _RunSpy()
    monkeypatch.setattr(github_mod.subprocess, "run", spy)
    GitHubReader(tmp_path)._run(*argv)          # không ném
    assert len(spy.calls) == 1


def test_gia_tri_cua_co_chieu_nguoc(tmp_path, monkeypatch):
    """Chiều ngược: bỏ các cờ của `gh pr create` khỏi `_VALUE_FLAGS` → đúng lời gọi trên bị chặn nhầm."""
    monkeypatch.setattr(github_mod, "_VALUE_FLAGS", frozenset({"--repo", "-R"}))
    with pytest.raises(GitHubWriteAttempt):
        GitHubReader(tmp_path)._run("pr", "create", "--title", "merge", "--body-file", "b.md")


def test_gh_loi_open_prs_la_khong_biet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _RunSpy(stdout="", returncode=1)
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.open_prs() is None


def test_open_prs_rong_that_la_list_rong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`[]` hợp lệ từ gh = BIẾT là 0 PR — khác hẳn `None` (không biết)."""
    spy = _RunSpy(stdout="[]")
    reader = _reader(tmp_path, spy, monkeypatch)
    assert reader.open_prs() == []
