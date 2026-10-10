"""Cầu `gh` CHỈ ĐỌC cho `keeper` (BT2, `DAC-TA-KEEPER.md` §4). Sao khuôn từ
`software-company/src/company/github_pr.py:62` (`_gh`): `encoding="utf-8"`, `env=clean_env()`, bắt
`FileNotFoundError`/`TimeoutExpired`, cắt stderr `[-300:]`, không bao giờ ném ngoại lệ tiến trình.

Bất biến **I1** (`DAC-TA-KEEPER.md` §0): `keeper` không có quyền ghi ngoài nhánh/commit/PR của chính nó.
`GitHubReader` không có hàm nào gọi `gh pr merge`, `gh api -X`, hay bất kỳ thao tác ghi nào — và `_run()`
ép điều đó bằng mã, không chỉ bằng việc "không viết hàm ghi": mọi argv đi qua `_run()` bị soi trước khi chạy.
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from pydantic import BaseModel
from xagents_core.sandbox import clean_env

# Từ khoá GHI. "-X"/"--method" là cờ HTTP tuỳ ý của `gh api` (có thể là -X DELETE, -X POST...) — luôn nguy hiểm
# dù verb là gì, nên chặn chính cờ chứ không chặn verb. "merge"/"close"/"delete"/"edit" là SUBCOMMAND ghi của
# `gh pr`/`gh issue`/`gh repo` (`gh pr merge`, `gh issue close`, `gh repo delete`, `gh pr edit`...).
#
# `-f/-F/--field/--raw-field/--input` KHÔNG có trong bảng của `DAC-TA-KEEPER.md` §4 và đó là một LỖ: `gh api`
# đổi phương thức sang POST ngay khi có bất kỳ trường nào, KHÔNG cần `-X`. Nghĩa là
# `gh api repos/o/r/pulls/1/merge -f x=y` là một lời gọi GHI mà bảng gốc cho lọt (token "merge" nằm trong
# đường dẫn `repos/.../merge`, không phải một token riêng, nên so khớp tuyệt đối không thấy). Chặn chính các
# cờ đó là chặn đúng cơ chế, thay vì cố đoán mọi hình dạng đường dẫn.
FORBIDDEN_ARGS = ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input",
                  "merge", "close", "delete", "edit")

# Cờ của CHÍNH các phương thức đọc dưới đây nhận một GIÁ TRỊ theo sau (tên repo, nhánh, ngày tìm kiếm...).
# Giá trị đó có thể trùng chữ với một từ trong FORBIDDEN_ARGS mà không hề là subcommand ghi — ví dụ repo tên
# "delete-me" sau "--repo", hay nhánh "edit/foo" sau "--head". So khớp phải BỎ QUA token ngay sau các cờ này,
# nếu không sẽ chặn nhầm một lời gọi đọc hợp lệ.
_VALUE_FLAGS = frozenset({
    "--repo", "-R", "--json", "--limit", "--state", "--head", "--base", "--since", "--search", "-q", "--jq",
    # Cờ của `gh pr create` — thêm ở BT8 sau khi khảo sát đường canary. Cùng HỌ lỗi với `--repo delete-me` đã
    # sửa ở BT2 (`AGENTS.md` bắt buộc §5: sửa một lỗi thì rà cả họ lỗi đó), và ở đây nó cắn thật: một PR bảo trì
    # có tiêu đề đúng bằng chữ "merge"/"close"/"delete"/"edit", hoặc `--body-file edit`, hoặc `--label delete`,
    # sẽ ném `GitHubWriteAttempt` — chặn nhầm một lời gọi ĐỌC/TẠO-PR hợp lệ. Bảng cấm soi SUBCOMMAND, nên mọi cờ
    # nhận giá trị đều phải nằm ở đây, không chỉ những cờ tình cờ đã dùng.
    "--title", "-t", "--body", "-b", "--body-file", "-F", "--label", "-l", "--assignee", "-a",
    "--milestone", "-m", "--project", "-p", "--reviewer", "-r", "--template", "-T",
})

CACHE_TTL_SECONDS = 60.0


class GitHubWriteAttempt(Exception):
    """`_run()` phát hiện argv chứa một thao tác ghi (bất biến I1). Không bao giờ được bắt và bỏ qua — đây là
    lỗi lập trình trong `keeper`, phải làm hỏng ngay, không được lặng lẽ tiếp tục."""


def _is_forbidden_token(a: str) -> bool:
    """Một token có phải từ/cờ ghi không — kể cả dạng DÍNH LIỀN mà `gh` (pflag) chấp nhận:

    - cờ dài kèm `=`: `--method=POST`, `--field=k=v`, `--raw-field=k=v`, `--input=f` → so phần trước `=`;
    - cờ ngắn dính giá trị hoặc gộp cụm: `-XPOST`, `-X=POST`, `-fk=v`, `-Fk=@f`, `-iXPOST` → duyệt từng chữ
      sau `-`: gặp chữ của cờ ghi là chặn; gặp chữ của một cờ NHẬN GIÁ TRỊ (`-q`, `-H`, `-R`...) thì phần còn
      lại là giá trị, dừng. Chữ lạ coi như cờ bool và đi tiếp — cờ lạ nhận giá trị có thể bị chặn nhầm, đó
      là hướng hỏng an toàn (I1).

    Bảng suy ra từ `FORBIDDEN_ARGS`/`_VALUE_FLAGS` MỖI LẦN gọi, không chép thành hằng thứ hai: ca chiều ngược
    thay bảng phải thấy đúng bảng đó."""
    if a in FORBIDDEN_ARGS:
        return True
    if a.startswith("--"):
        return "=" in a and a.split("=", 1)[0] in FORBIDDEN_ARGS
    if a.startswith("-") and len(a) > 2:
        forbidden_shorts = {f[1] for f in FORBIDDEN_ARGS if len(f) == 2 and f.startswith("-")}
        value_shorts = {f[1] for f in _VALUE_FLAGS if len(f) == 2 and f.startswith("-")} | {"H"}
        for ch in a[1:]:
            if ch in forbidden_shorts:
                return True
            if ch in value_shorts:
                return False
    return False


def _contains_forbidden(args: tuple[str, ...]) -> bool:
    """Quy tắc so khớp: mỗi token qua `_is_forbidden_token` (khớp tuyệt đối HOẶC dạng dính liền của cờ ghi,
    không phải substring), trừ token ngay sau một cờ trong `_VALUE_FLAGS` (đó là giá trị của cờ, không phải
    một subcommand)."""
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if _is_forbidden_token(a):
            return True
        if a in _VALUE_FLAGS:
            skip_next = True
    return False


class PullRequest(BaseModel):
    """Một dòng của `gh pr list`. `extra="ignore"`: chỉ lấy trường mình xin qua `--json`, phần thừa gh trả
    thêm ở version khác không làm vỡ parse."""
    model_config = {"extra": "ignore"}
    number: int
    title: str = ""
    url: str = ""
    headRefName: str = ""
    createdAt: str | None = None
    mergedAt: str | None = None


class CheckRun(BaseModel):
    model_config = {"extra": "ignore"}
    name: str
    state: str = ""
    link: str = ""


class DependabotAlert(BaseModel):
    model_config = {"extra": "ignore"}
    number: int
    state: str = ""
    severity: str = ""
    summary: str = ""


class CodeScanningAlert(BaseModel):
    model_config = {"extra": "ignore"}
    number: int
    state: str = ""
    severity: str = ""
    rule_description: str = ""


class WorkflowRun(BaseModel):
    """`startedAt`/`updatedAt`: tên trường THẬT của `gh run list --json` (kiểm bằng `gh run list --json bogus`
    để `gh` tự liệt kê trường hợp lệ — không phải `run_started_at`/`updated_at` của REST API thô, đó là tên
    JSON của endpoint HTTP, `gh` CLI đặt tên khác). Mặc định `None`: bản ghi thiếu (gh cũ, hay run đang chạy
    dở nên chưa có `updatedAt` kết thúc) không làm vỡ parse; `health.ci_duration_stats()` coi run thiếu một
    trong hai mốc là chưa đo được, loại khỏi mẫu thay vì đoán 0."""
    model_config = {"extra": "ignore"}
    databaseId: int
    name: str = ""
    status: str = ""
    conclusion: str | None = None
    headSha: str = ""
    createdAt: str | None = None
    startedAt: str | None = None
    updatedAt: str | None = None


class GitHubReader:
    """Adapter `gh` chỉ đọc, một instance cho một repo cục bộ (`repo` là cwd chạy `gh`). Bộ đệm TTL theo argv:
    một chu kỳ watch (BT3) gọi nhiều phương thức nhiều lần trong vài giây — không có lý do gọi lại `gh` cho
    cùng một câu hỏi trong cùng một chu kỳ.

    `clock` tiêm được (mặc định `time.monotonic`) để test đo TTL không phải `sleep` thật — chỉ cần một đồng
    hồ giả trả giá trị tăng dần theo ý test."""

    def __init__(
        self,
        repo: Path,
        *,
        timeout: int = 60,
        cache_ttl: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.repo = repo
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._clock = clock
        self._cache: dict[tuple[str, ...], tuple[float, bool, str]] = {}

    def _run(self, *args: str) -> tuple[bool, str]:
        """`gh <args>` trong `self.repo`; không ném lỗi tiến trình — (ok, stdout) hoặc (False, lý do rút gọn).
        Ném `GitHubWriteAttempt` NGAY LẬP TỨC (trước khi chạm bộ đệm hay subprocess) nếu argv chứa một thao
        tác ghi — bất biến I1 thành mã."""
        if _contains_forbidden(args):
            raise GitHubWriteAttempt(f"gh {' '.join(args)}: thao tác ghi bị cấm (bất biến I1)")

        now = self._clock()
        cached = self._cache.get(args)
        if cached is not None:
            expires_at, ok, out = cached
            if now < expires_at:
                return ok, out

        try:
            r = subprocess.run(
                ["gh", *args], cwd=str(self.repo), capture_output=True, text=True, encoding="utf-8",
                env=clean_env(), timeout=self.timeout, check=False,
            )
        except FileNotFoundError:
            ok, out = False, "gh: không có trên máy (cài GitHub CLI rồi `gh auth login`)"
        except subprocess.TimeoutExpired:
            ok, out = False, f"gh {' '.join(args[:2])}: quá {self.timeout}s"
        except OSError as e:   # có trên máy mà không chạy được (quyền, binary hỏng)
            ok, out = False, f"gh: không chạy được ({e.strerror or e})"
        else:
            ok, out = (True, r.stdout.strip()) if r.returncode == 0 else (False, (r.stderr or r.stdout).strip()[-300:])

        self._cache[args] = (now + self.cache_ttl, ok, out)
        return ok, out

    @staticmethod
    def _parse_list(out: str) -> list[dict]:
        """JSON hỏng hoặc rỗng → `[]`, không bao giờ ném."""
        if not out:
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def _parse_list_strict(ok: bool, out: str) -> list[dict] | None:
        """Như `_parse_list` nhưng PHÂN BIỆT "gh nói rỗng" (`[]`) với "không biết" (`None`): gh lỗi, quá
        giờ, vắng mặt, hay trả thứ không phải một mảng JSON → `None`. Dùng cho câu hỏi mà câu trả lời rỗng
        mở cổng (bất biến I3 — `budget.can_open_pr`): đọc lỗi thành "0 PR" là fail OPEN."""
        if not ok:
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, list) else None

    def open_prs(self) -> list[PullRequest] | None:
        """`None` = không biết (gh lỗi/JSON hỏng) — KHÁC `[]` (biết chắc 0 PR). Xem `_parse_list_strict`."""
        ok, out = self._run("pr", "list", "--state", "open", "--json", "number,title,url,headRefName,createdAt")
        rows = self._parse_list_strict(ok, out)
        return None if rows is None else [PullRequest.model_validate(row) for row in rows]

    def checks(self, pr: int) -> list[CheckRun]:
        ok, out = self._run("pr", "checks", str(pr), "--json", "name,state,link")
        if not ok:
            return []
        return [CheckRun.model_validate(row) for row in self._parse_list(out)]

    def dependabot_alerts(self) -> list[DependabotAlert] | None:
        """`None` = không biết, như `open_prs`: `audit` lấy nguồn này để nói "không có phát hiện", nên đọc lỗi
        thành `[]` là đọc "chưa quét" thành "sạch"."""
        ok, out = self._run(
            "api", "repos/{owner}/{repo}/dependabot/alerts",
            "--jq", "[.[] | {number, state, severity: .security_advisory.severity, summary: .security_advisory.summary}]",
        )
        rows = self._parse_list_strict(ok, out)
        return None if rows is None else [DependabotAlert.model_validate(row) for row in rows]

    def code_scanning_alerts(self) -> list[CodeScanningAlert] | None:
        """`None` = không biết — cùng lý do `dependabot_alerts`."""
        ok, out = self._run(
            "api", "repos/{owner}/{repo}/code-scanning/alerts",
            "--jq", "[.[] | {number, state, severity: .rule.security_severity_level, "
                    "rule_description: .rule.description}]",
        )
        rows = self._parse_list_strict(ok, out)
        return None if rows is None else [CodeScanningAlert.model_validate(row) for row in rows]

    def pr_age_days(self, pr: int, *, now: datetime | None = None) -> float | None:
        ok, out = self._run("pr", "view", str(pr), "--json", "createdAt")
        if not ok or not out:
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return None
        created_raw = data.get("createdAt") if isinstance(data, dict) else None
        if not created_raw:
            return None
        try:
            created = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        reference = now or datetime.now(UTC)
        return (reference - created).total_seconds() / 86400.0

    def workflow_runs(self) -> list[WorkflowRun]:
        ok, out = self._run(
            "run", "list", "--json",
            "databaseId,name,status,conclusion,headSha,createdAt,startedAt,updatedAt", "--limit", "50",
        )
        if not ok:
            return []
        return [WorkflowRun.model_validate(row) for row in self._parse_list(out)]

    def merged_prs(self, since: str) -> list[PullRequest] | None:
        """`None` = không biết, như `open_prs`."""
        ok, out = self._run(
            "pr", "list", "--state", "merged", "--search", f"merged:>={since}",
            "--json", "number,title,url,headRefName,mergedAt",
        )
        rows = self._parse_list_strict(ok, out)
        return None if rows is None else [PullRequest.model_validate(row) for row in rows]
