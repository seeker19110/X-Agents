"""Bằng chứng đo hai chiều — bất biến **I2** (`DAC-TA-KEEPER.md` §0, §8) và `AGENTS.md` bắt buộc §4.

## Vì sao `before.exit_code == 0` là báo cáo VÔ HIỆU

`AGENTS.md` §4: "tắt bản sửa → test ĐỎ; bật lại → XANH". Nửa đầu là nửa dễ bỏ quên, và bỏ nó thì bộ test chỉ
chứng minh "code chạy được", không chứng minh "test đo đúng cái vừa sửa". Ba gói trước của repo này đã có ba
ca tự nhận là chiều ngược mà xanh vĩnh viễn. Nên `require_two_way()` từ chối chính cái hình dạng đó: stash bản
sửa đi rồi chạy CI mà vẫn `exit_code == 0` ⇒ hoặc patch không sửa gì thật, hoặc không test nào đi qua nó.

## Vì sao `verified_by` KHÔNG BAO GIỜ đến từ payload

Cạm bẫy lớn nhất của BT6 (`DAC-TA-KEEPER.md` §8): cám dỗ để agent **tự khai** `verified_by="workspace"`. Đó
đúng là `AGENTS.md` cấm §8 ("không tin lời khai") — và một lời khai thì không tốn gì để viết, trong khi hai
lần chạy CI thật thì tốn. Nếu trường này nhận được từ JSON model trả về, mọi hàng kiểm còn lại thành trang trí.

Đường dữ liệu bị chặn ở ĐÚNG một chỗ, `verification_report()`:

    payload model trả về ──drop_self_claims()──▶ trường KỂ CHUYỆN (ticket_id, family_hits, family_safe)
                                                        │
    collect_two_way() (code vừa chạy lệnh) ─────────────┴──▶ VerificationReport(before, after, verified_by)

Phép hợp nhất trong `verification_report()` CỐ Ý viết theo thứ tự nguy hiểm — `{**đo được, **payload}`, đúng
khuôn `guard.guard_payload()` trả `{**payload, **clean}` — để bộ lọc là thứ DUY NHẤT giữ lời khai ở ngoài, và
để ca chiều ngược tắt được nó rồi đo lại (bỏ lọc ⇒ lời khai lọt, mua được một lần xanh). Viết kiểu "ghi đè
sau" thì bộ lọc thành vô dụng-nhưng-trông-an-toàn: không ai đo được nó còn sống hay đã chết.

`SELF_CLAIM_FIELDS` đứng cạnh `CORE.untrusted_fields` (`core.py`) chứ không nằm trong nó: hai cơ chế khác nhau.
`untrusted_fields` là *lọc nội dung* (sanitize chuỗi có mẫu injection, giữ trường lại); self-claim là *bỏ hẳn
trường* vì bản thân sự tồn tại của nó là lời khai. `guard.guard_payload()` không có thao tác bỏ trường, nên
chỗ chặn ở đây, tại nơi duy nhất dựng `VerificationReport`.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path, PureWindowsPath
from typing import Any

from pydantic import BaseModel
from xagents_core.sandbox import clean_env

from .events import RunOutcome, VerificationReport
from .family import FamilyReport, FamilyReportInvalid, FamilySite, require_family_report
from .family import SafeSite as FamilySafeSite
from .worktree import refuse_shared_checkout

# Chỉ MỘT giá trị được coi là "code vừa chạy lệnh trong workspace này". `orchestrator` là một người xác minh
# HỢP LỆ ở chỗ khác trong repo, nhưng không hợp lệ cho một patch của `keeper`: patch được đo trên worktree.
TRUSTED_VERIFIER = "workspace"

# Mã thoát cho hai chế độ hỏng của tiến trình. Âm nên không trùng mã thoát thật của lệnh nào (0-255), và
# KHÁC NHAU vì "công cụ không có trên máy" là chuyện bình thường (`audit.py` bỏ qua) còn "quá giờ" thì không.
MISSING_EXIT = -1
TIMEOUT_EXIT = -2

STASH_MESSAGE = "keeper-two-way"
DEFAULT_TIMEOUT = 600
DEFAULT_TAIL = 2000

# Trường mà model KHÔNG BAO GIỜ được tự điền — xem docstring module.
#
# Đây phải là ĐÚNG tập trường mà `verification_report` tự đo (`_measured()`), không phải một danh sách viết tay
# đứng cạnh. Bản đầu chỉ liệt kê `verified_by`, và `sc-security` đo được hậu quả: `before`/`after` không bị lọc,
# nên một payload `{"before": {"exit_code": 1}, "after": {"exit_code": 0}}` ghi đè kết quả đo, `require_two_way`
# chấm trên chính lời khai đó, và `verified_by` vẫn là "workspace" vì nó đến từ phía đo. Model dựng được một
# `VerificationReport` hợp lệ mà KHÔNG lệnh CI nào chạy — thủng thẳng bất biến I2.
#
# `test_self_claim_fields_phu_kin_moi_truong_do_duoc` khoá hai tập này bằng nhau, nên thêm một trường đo mới mà
# quên lọc là CI đỏ, không phải là một lỗ im lặng.
SELF_CLAIM_FIELDS = frozenset({"verified_by", "before", "after"})

CommandRunner = Callable[..., RunOutcome]


def _measured(evidence: TwoWayEvidence) -> dict[str, object]:
    """Đúng những trường do CODE đo, không do model kể. `SELF_CLAIM_FIELDS` phải bằng đúng khoá của dict này."""
    return {
        "before": evidence.before.model_dump(),
        "after": evidence.after.model_dump(),
        "verified_by": evidence.verified_by,
    }


class EvidenceError(Exception):
    """Bằng chứng không đủ để rời pha quality (bất biến I2). Không bao giờ được bắt rồi bỏ qua."""


def run_command(
    argv: Sequence[str], cwd: Path, *, timeout: int = DEFAULT_TIMEOUT, tail: int | None = DEFAULT_TAIL,
) -> RunOutcome:
    """Chạy một lệnh THẬT và trả OUTPUT THẬT. Không ném ngoại lệ tiến trình — khuôn `github.py:_run()`.

    `tail=None` giữ nguyên output (cần khi output là JSON phải parse, ví dụ `pip-audit`); số nguyên thì cắt
    đuôi bấy nhiêu ký tự (đuôi chứ không phải đầu: dòng lỗi cuối cùng mới là dòng nói vì sao đỏ).
    """
    cmd = " ".join(argv)
    try:
        r = subprocess.run(
            list(argv), cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=clean_env(), timeout=timeout, check=False,
        )
    except FileNotFoundError:
        return RunOutcome(cmd=cmd, exit_code=MISSING_EXIT, output_tail=f"{argv[0]}: không có trên máy")
    except subprocess.TimeoutExpired:
        return RunOutcome(cmd=cmd, exit_code=TIMEOUT_EXIT, output_tail=f"{cmd}: quá {timeout}s")
    out = (r.stdout or "") + (r.stderr or "")
    return RunOutcome(cmd=cmd, exit_code=r.returncode, output_tail=out if tail is None else out[-tail:])


class TwoWayEvidence(BaseModel):
    """Hai lần chạy CÙNG một lệnh CI quanh cùng một patch: `before` = đã TẮT bản sửa (stash), `after` = đã bật
    lại. `verified_by` chỉ được đặt bởi code vừa chạy — xem docstring module."""
    cmd: str
    before: RunOutcome
    after: RunOutcome
    verified_by: str


@dataclass(frozen=True)
class EvidenceRule:
    """Một hàng kiểm tra cứu được theo tên — cùng lý do như `risk.RISK_RULES`/`budget.BUDGET_CHECKS`: ca chiều
    ngược phải BỎ ĐƯỢC đúng một hàng rồi đo lại trên cùng đầu vào."""
    name: str
    ok: Callable[[TwoWayEvidence], bool]
    why: str


# `pytest.ExitCode.TESTS_FAILED`, viết lại thành hằng vì pytest không phải phụ thuộc lúc chạy của gói. Các mã
# dương khác của pytest đều là KHÔNG test nào chạy xong: 2 bị ngắt/lỗi lúc thu thập, 3 lỗi nội bộ, 4 sai cách
# gọi (đường dẫn không có), 5 không thu được test nào.
PYTEST_TESTS_FAILED = 1
_PYTEST_NAMES = frozenset({"pytest", "py.test"})


def _is_pytest(cmd: str) -> bool:
    """`cmd` gọi thẳng pytest: một token là tệp chạy `pytest`/`py.test` (kể cả đường dẫn, `.exe`), hoặc `-m pytest`.
    Nhận nhầm chỉ làm luật CHẶT hơn (đòi mã 1), nên dò theo token là đủ."""
    tokens = cmd.split()
    return (any(PureWindowsPath(t).name.removesuffix(".exe") in _PYTEST_NAMES for t in tokens)
            or ("-m", "pytest") in pairwise(tokens))


# Lệnh BỌC: gom nhiều bước (ruff, mypy, pytest) vào MỘT mã thoát. `dev-task.sh gate` thoát 1 cho mọi bước hỏng,
# `make` thoát 2 cho mọi recipe hỏng — mã dương không còn nói "có test đỏ". Nhận theo TÊN lệnh, cùng cách `_is_pytest`.
_WRAPPER_NAMES = frozenset({"make", "gmake", "dev-task.sh"})
# Dòng tổng kết pytest, không bản địa hoá: `1 failed, 3 passed in 0.12s` (`-q`), bọc `=====` (chế độ thường), có thể
# kèm `(0:01:01)` sau thời gian; `no tests ran in 0.01s` khi không thu được test nào.
_PYTEST_SUMMARY = re.compile(
    r"(?:=+ )?(?:no tests ran|(?P<stats>\d+ \w+(?:, \d+ \w+)*)) in \d+(?:\.\d+)?s(?: \(\d+:\d{2}:\d{2}\))?(?: =+)?"
)
# Lượt chạy bị ngắt giữa chừng (lỗi thu thập, Ctrl-C): có `failed` ở dòng tổng kết cũng không đáng tin.
_RUN_ABORTED = ("error during collection", "Interrupted")


def _is_wrapper(cmd: str) -> bool:
    """`cmd` chạy qua `make` hoặc `dev-task.sh` (kể cả đường dẫn, `.exe`, `uv run make …`). Chỉ hai tên này: bọc lạ
    (`tox`, `sh -c`, script riêng) không nhận ra được nên rơi về luật `> 0` của hàng trên."""
    return any(PureWindowsPath(t).name.removesuffix(".exe") in _WRAPPER_NAMES for t in cmd.split())


def _pytest_failed(output: str) -> int:
    """Số test ĐỎ ở dòng tổng kết pytest CUỐI CÙNG của `output`; 0 nếu không có dòng tổng kết nào, hoặc dòng cuối
    là `no tests ran`. Dòng cuối thắng: `make test` chạy từng gói và dừng ở gói hỏng đầu tiên, còn một test có thể
    in ra nguyên văn một dòng giống dòng tổng kết."""
    last: re.Match[str] | None = None
    for line in output.splitlines():
        last = _PYTEST_SUMMARY.fullmatch(line.strip()) or last
    if last is None or last["stats"] is None:
        return 0
    return sum(int(n) for n, word in re.findall(r"(\d+) (\w+)", last["stats"]) if word == "failed")


def _wrapped_before_shows_test_failure(e: TwoWayEvidence) -> bool:
    """Lệnh bọc thoát dương: chiều đỏ chỉ hợp lệ khi output có test chạy xong và đỏ, và lượt chạy không bị ngắt.
    Mã ≤ 0 là việc của `before-must-fail`; lệnh không bọc là việc của hàng pytest-gọi-thẳng (hoặc giữ `> 0`)."""
    b = e.before
    if b.exit_code <= 0 or not _is_wrapper(b.cmd):
        return True
    return _pytest_failed(b.output_tail) >= 1 and not any(m in b.output_tail for m in _RUN_ABORTED)


EVIDENCE_RULES: tuple[EvidenceRule, ...] = (
    # `> 0`, không phải `!= 0`: mã âm là lần chạy KHÔNG hoàn tất (`TIMEOUT_EXIT`, `MISSING_EXIT`, bị giết bằng
    # tín hiệu) — không test nào chạy xong thì không có chiều đỏ nào được đo.
    EvidenceRule("before-must-fail", lambda e: e.before.exit_code > 0,
                 "tắt bản sửa mà lệnh CI vẫn xanh hoặc không chạy xong ⇒ không test nào đo bản sửa này"),
    # Chỉ xét mã DƯƠNG (mã ≤ 0 là việc của hàng trên): `--include-untracked` stash cả file test MỚI của patch, nên
    # lệnh nhắm thẳng nó thoát 4/5 — `> 0` mà không test nào chạy.
    EvidenceRule("pytest-before-must-be-test-failure",
                 lambda e: e.before.exit_code <= 0 or not _is_pytest(e.before.cmd)
                 or e.before.exit_code == PYTEST_TESTS_FAILED,
                 f"pytest chỉ thoát {PYTEST_TESTS_FAILED} khi có test chạy xong và ĐỎ; mã khác ⇒ không test nào "
                 "đo bản sửa này (vd file test mới bị stash cùng bản sửa)"),
    # Lệnh bọc (`make`, `dev-task.sh`) nuốt mã thoát nên hàng trên không soi được: đòi dòng tổng kết pytest ở output.
    # no-ky-thuat: chỉ nhận bọc theo tên make/gmake/dev-task.sh và đòi dòng pytest cho mọi target của chúng kể cả `make lint`; bọc lạ (tox hay `sh -c` hay script riêng) vẫn nhận mọi mã > 0, quay lại khi keeper đo hai chiều qua một bọc khác tên đó hoặc qua target không chạy pytest
    EvidenceRule("wrapped-before-must-show-test-failure", _wrapped_before_shows_test_failure,
                 "lệnh bọc (make, dev-task.sh) thoát dương cho MỌI bước hỏng (ruff, mypy, thu thập, pytest): chiều đỏ "
                 "chỉ hợp lệ khi dòng tổng kết pytest CUỐI trong output có `N failed` (N ≥ 1) và lượt chạy không bị "
                 "ngắt (`error during collection`/`Interrupted`) — không thì chưa test nào đo bản sửa này"),
    EvidenceRule("after-must-pass", lambda e: e.after.exit_code == 0,
                 "bật bản sửa mà lệnh CI vẫn đỏ ⇒ patch chưa xong"),
    EvidenceRule("verifier-must-be-workspace", lambda e: e.verified_by == TRUSTED_VERIFIER,
                 f"chỉ code vừa chạy lệnh mới đặt được verified_by={TRUSTED_VERIFIER!r}"),
)


def rules_without(*names: str) -> tuple[EvidenceRule, ...]:
    """Bảng kiểm thiếu đúng những hàng được nêu. Tên lạ thì NỔ (một ca chiều ngược gõ sai tên hàng sẽ tắt
    KHÔNG hàng nào và xanh vĩnh viễn — đúng khuôn hỏng đã gặp ba lần)."""
    known = {r.name for r in EVIDENCE_RULES}
    missing = sorted(set(names) - known)
    if missing:
        raise KeyError(f"không có hàng kiểm {missing} trong EVIDENCE_RULES")
    return tuple(r for r in EVIDENCE_RULES if r.name not in names)


def require_two_way(ev: TwoWayEvidence, *, rules: tuple[EvidenceRule, ...] = EVIDENCE_RULES) -> None:
    """Ném `EvidenceError` nêu TÊN hàng kiểm hỏng + lý do (bất biến I2)."""
    broken = [r for r in rules if not r.ok(ev)]
    if broken:
        detail = "; ".join(f"{r.name}: {r.why}" for r in broken)
        raise EvidenceError(f"bằng chứng hai chiều không đạt ({ev.cmd}) — {detail}")


def _stash_depth(runner: CommandRunner, repo: Path) -> int:
    r = runner(("git", "stash", "list"), repo)
    if r.exit_code != 0:
        raise EvidenceError(f"git stash list thất bại: {r.output_tail}")
    return len([ln for ln in r.output_tail.splitlines() if ln.strip()])


def collect_two_way(
    argv: Sequence[str], repo: Path, *, runner: CommandRunner = run_command,
) -> TwoWayEvidence:
    """`git stash` TOÀN BỘ thay đổi chưa commit → chạy lệnh CI (`before`) → `git stash pop` → chạy lại (`after`).

    Không phải "chỉ diff của patch": `--include-untracked` cất mọi thứ chưa commit trong `repo`. Vì thế `repo`
    BẮT BUỘC là worktree phụ của chính `keeper` — `refuse_shared_checkout` chặn ngay đầu hàm.

    Đây là NƠI DUY NHẤT đặt `verified_by`, và đặt được vì chính hàm này vừa chạy hai lệnh.

    Độ sâu stash được ĐẾM trước và sau `push` thay vì đọc chữ trong output: `git` bản địa hoá thông điệp
    ("No local changes to save") nên dò chuỗi là một cổng đúng-sai theo locale của máy — đúng khuôn
    "test đúng-sai theo nền tảng" mà `TRAPS.md` §2 cấm. Không tạo được mục stash nào ⇒ không có gì để TẮT ⇒
    `before` sẽ đo chính bản gốc, và con số thu được là vô nghĩa chứ không phải "may mà xanh".
    """
    # `git stash push --include-untracked` cất TOÀN BỘ worktree, không chỉ diff của patch — chạy nhầm trên
    # checkout chung là nuốt việc chưa commit của phiên khác. `repo` là tham số tự do, nên chốt phải đứng ngay
    # đây, trước lệnh stash đầu tiên. (`sc-security` chấm BT6: đây là phát hiện chặn thứ ba của gói.)
    refuse_shared_checkout(repo)
    cmd = " ".join(argv)
    depth = _stash_depth(runner, repo)
    push = runner(("git", "stash", "push", "--include-untracked", "-m", STASH_MESSAGE), repo)
    if push.exit_code != 0:
        raise EvidenceError(f"git stash push thất bại, không tắt được bản sửa: {push.output_tail}")
    if _stash_depth(runner, repo) != depth + 1:
        raise EvidenceError(f"git stash không tạo mục stash nào cho {cmd}: không có diff để TẮT")
    try:
        before = runner(tuple(argv), repo)
    finally:
        # `finally` chứ không phải dòng kế tiếp: lệnh CI nổ giữa chừng mà không pop thì patch của người dùng
        # nằm lại trong stash và worktree im lặng mất thay đổi.
        pop = runner(("git", "stash", "pop"), repo)
    if pop.exit_code != 0:
        # `pop` thất bại thường là XUNG ĐỘT: mục stash vẫn còn nguyên (chỉ `pop` = `apply` + `drop` mới xoá nó,
        # và `apply` xong xung đột thì KHÔNG `drop`). Nó vừa được `push` ngay phía trên nên gần như chắc chắn
        # là mục MỚI NHẤT — `stash@{0}` — nhưng "gần như chắc chắn" không đủ khi đây là lúc người mất việc:
        # nêu cả toạ độ đoán được lẫn thông điệp để tự tra, và không đoán thay bằng cách tự `apply`/`drop`.
        raise EvidenceError(
            f"git stash pop thất bại — PATCH CHƯA ĐƯỢC KHÔI PHỤC, tự khôi phục tay bằng "
            f"`git stash list` (tìm mục '{STASH_MESSAGE}', gần như chắc chắn là stash@{{0}} vì vừa push) rồi "
            f"`git stash apply stash@{{0}}` (không dùng `pop` — xung đột vẫn còn thì `pop` xoá mất mục stash "
            f"khi resolve xong): {pop.output_tail}"
        )
    after = runner(tuple(argv), repo)
    return TwoWayEvidence(cmd=cmd, before=before, after=after, verified_by=TRUSTED_VERIFIER)


def drop_self_claims(
    payload: Mapping[str, Any], *, fields: frozenset[str] = SELF_CLAIM_FIELDS,
) -> tuple[dict[str, Any], list[str]]:
    """(payload đã bỏ trường tự khai, danh sách trường đã bỏ). `fields` là tham số để ca chiều ngược TẮT được
    bộ lọc (`fields=frozenset()`) rồi đo lại trên cùng payload."""
    dropped = sorted(k for k in payload if k in fields)
    return {k: v for k, v in payload.items() if k not in fields}, dropped


def verification_report(
    payload: Mapping[str, Any], *, evidence: TwoWayEvidence,
    fields: frozenset[str] = SELF_CLAIM_FIELDS, rules: tuple[EvidenceRule, ...] = EVIDENCE_RULES,
) -> VerificationReport:
    """`payload` (JSON model trả về) + `evidence` (đo được) → `VerificationReport` đã qua `require_two_way`.

    Model chỉ đóng góp trường KỂ CHUYỆN. Xem docstring module về thứ tự hợp nhất."""
    clean, _dropped = drop_self_claims(payload, fields=fields)
    measured = _measured(evidence)
    # Hai lớp, cố ý thừa: (1) `drop_self_claims` bỏ hẳn mọi trường đo được khỏi payload; (2) `measured` hợp nhất
    # SAU nên kể cả khi lớp (1) bị nới, số đo vẫn thắng lời khai. Bản đầu chỉ có lớp (1) và hợp nhất theo chiều
    # ngược lại — một trường quên lọc là đủ để lời khai ghi đè.
    report = VerificationReport.model_validate({**clean, **measured})
    require_two_way(
        TwoWayEvidence(cmd=evidence.cmd, before=report.before, after=report.after,
                       verified_by=report.verified_by),
        rules=rules,
    )
    _require_family_from_report(report)
    return report


def _require_family_from_report(report: VerificationReport) -> None:
    """Nối `family.require_family_report()` vào đường dựng báo cáo: có `family_hits` mà `family_safe`
    rỗng — hoặc có mục `safe` thiếu lý do — thì `VerificationReport` KHÔNG được rời hàm này (`AGENTS.md`
    §1 mục 1, `TRAPS.md` §1). `line`/`text`/`mechanism` không tới được đây (bus chỉ mang `path`+`reason`,
    xem `events.FamilySafeEntry`) nên được điền giá trị rỗng — chúng không được `require_family_report()`
    đọc, chỉ tồn tại vì `FamilySite`/`SafeSite` khai chúng là bắt buộc ở lớp model nội bộ của `family.py`."""
    fr = FamilyReport(
        mechanisms=[],
        hits=[FamilySite(path=h, line=0, text="", mechanism="") for h in report.family_hits],
        safe=[FamilySafeSite(path=s.path, mechanism="", reason=s.reason) for s in report.family_safe],
    )
    try:
        require_family_report(fr)
    except FamilyReportInvalid as e:
        raise EvidenceError(f"báo cáo rà họ lỗi không hợp lệ: {e}") from e
