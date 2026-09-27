"""Workspace cô lập theo ticket: git worktree trên branch `ticket/<id>`, chạy lint/test thật, trả `local_checks`.
Tool xác định cho khối kỹ thuật; kết quả là bằng chứng để đưa vào `pull-requests.local_checks`.

`Integration` (ADR-0011): nhánh tích hợp của công ty (`company/integration`, rẽ từ `base` lần đầu). Ticket rẽ từ đây
và được merge vào đây (--no-ff) khi đủ review pass; xung đột thì huỷ merge, trả lại danh sách file để ticket làm lại
trên nền mới. Nhánh của khách (`main`) không bị chạm.

Giao hàng (ADR-0027): `Integration.deliver` đặt tag `v<version>` tại sha tích hợp và fast-forward nhánh `company/release`
tới đó; `rollback_delivery` lùi con trỏ nhánh về lần giao trước (tag giữ nguyên). Tuỳ chọn push lên remote của khách."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xagents_core.sandbox import SECRET_ENV as SECRET_ENV  # re-export: `llm.py` và test nhập từ đây
from xagents_core.sandbox import clean_env

from .stacks import Stack, detect


class WorkspaceError(Exception): ...


# K3.2: `SECRET_ENV` và `clean_env` sống ở `xagents_core.sandbox` (sandbox là chỗ CUỐI CÙNG env đi qua, nên
# danh sách chặn phải ở đó chứ không phải ở một trong các nơi gọi). Nhập lại tên cũ vì 5 module và test của
# company vẫn `from .workspace import clean_env` — đổi chúng là sửa code cạnh bên, không thuộc PR này.


# Hook của repo khách (`.git/hooks`, hay `core.hooksPath=.husky` — thư mục nằm TRONG worktree nên model ghi được)
# là mã của khách chạy dưới quyền người vận hành lúc commit/merge. Orchestrator không bao giờ chạy hook: trỏ
# hooksPath vào chỗ không tồn tại. Người muốn hook chạy thì chạy tay khi đưa nhánh tích hợp lên `main`.
NO_HOOKS: tuple[str, ...] = ("-c", "core.hooksPath=/dev/null")


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    # env đã lọc khoá (hook/filter/credential helper của khách không thấy secret của công ty), không hook.
    r = subprocess.run(["git", "-C", str(repo), *NO_HOOKS, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       input=stdin, env=clean_env())
    if r.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


# Rác do agent chạy lint/test sinh ra trong worktree. `commit_all` dùng `git add -A`: không loại thì `.pyc` của hai
# ticket cùng vào branch rồi xung đột nhị phân lúc merge (mô phỏng donghanhcungban, F14). Ghi vào `.git/info/exclude`
# (áp cho mọi worktree, không chạm `.gitignore` của khách) và không bao giờ add vào index.
# File sinh tự động / hợp đồng: vẫn gửi reviewer nhưng XUỐNG CUỐI diff, để khi cắt thì mã nguồn còn nguyên.
GENERATED_PATTERNS = ("openapi", ".lock", "-lock.json", ".snap", ".min.js", ".map", "sbom", "third-party")


def is_generated(path: str) -> bool:
    low = path.lower()
    return any(pat in low for pat in GENERATED_PATTERNS)


JUNK_PATTERNS = (".worktrees/", "__pycache__/", "*.pyc", "*.pyo", ".ruff_cache/", ".pytest_cache/", ".mypy_cache/",
                 ".hypothesis/", ".venv/", "*.egg-info/")


def exclude_worktrees(repo: Path) -> None:
    """`.worktrees/` và rác lint/test là của công ty, không phải của khách: ghi vào `.git/info/exclude` để `git status`
    của khách không thấy untracked và `git add -A` của `commit_all` không vơ vào."""
    git_dir = Path(_git(repo, "rev-parse", "--git-common-dir"))
    if not git_dir.is_absolute(): git_dir = repo / git_dir
    f = git_dir / "info" / "exclude"
    try:
        current = f.read_text(encoding="utf-8") if f.exists() else ""
    except OSError:
        return
    have = set(current.splitlines())
    missing = [x for x in JUNK_PATTERNS if x not in have]
    if not missing: return
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(current + ("" if not current or current.endswith("\n") else "\n") + "\n".join(missing) + "\n", encoding="utf-8")


@dataclass
class CheckResult:
    ok: bool
    output: str


@dataclass
class TicketWorkspace:
    repo: Path
    ticket_id: str
    base: str = "HEAD"
    # ADR-0035 (K2.4): sandbox chạy lint/test của repo KHÁCH. `None` = `SubprocessSandbox` (hành vi trước ADR)
    # — mặc định phải là hành vi cũ vì `TicketWorkspace` được dựng ở rất nhiều nơi, kể cả trong test; tiến trình
    # thật nhận sandbox theo cấu hình từ `Orchestrator.sandbox` (xem `orch/worktree_flow.workspace`).
    # Kiểu để `Any` chứ không phải `Sandbox`: giữ nguyên từ trước K3.2. Vòng lặp import cũ (`sandbox.py` nhập
    # `clean_env` từ file này) đã hết — cả hai nay nhập từ `xagents_core.sandbox` — nhưng đổi chú kiểu ở đây là
    # sửa code cạnh bên, không thuộc PR chuyển mã.
    sandbox: Any = None

    @property
    def branch(self) -> str: return f"ticket/{self.ticket_id}"
    @property
    def path(self) -> Path: return self.repo / ".worktrees" / self.ticket_id

    def create(self) -> Path:
        if self.path.exists():
            return self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exclude_worktrees(self.repo)
        if _git(self.repo, "branch", "--list", self.branch):
            _git(self.repo, "worktree", "add", str(self.path), self.branch)
        else:
            _git(self.repo, "worktree", "add", "-b", self.branch, str(self.path), self.base)
        return self.path

    def remove(self, delete_branch: bool = False) -> None:
        if self.path.exists():
            _git(self.repo, "worktree", "remove", "--force", str(self.path))
        if delete_branch:
            _git(self.repo, "branch", "-D", self.branch)

    def _sandbox(self) -> Any:
        """Nhập lười: giữ từ trước K3.2, khi `sandbox.py` còn nhập `clean_env` từ module này. Vòng lặp đó đã hết
        (cả hai nhập từ core) nên đây chỉ còn là hoãn import, không còn là bắt buộc."""
        if self.sandbox is None:
            from .sandbox import SubprocessSandbox
            self.sandbox = SubprocessSandbox()
        return self.sandbox

    def _run(self, *cmd: str, timeout: int = 600) -> CheckResult:
        # Env đã lọc khoá API (như tool của model): lint/test của repo khách không được thấy secret của công ty.
        # Qua `Sandbox` từ ADR-0035: cùng cách cắt output (4000), cùng timeout; backend `container` thêm mạng tắt
        # và hạn mức. `env=clean_env()` truyền TƯỜNG MINH — `RunSpec.env` mặc định là `{}` (rỗng thật, không phải
        # "chưa khai"), để rỗng là lệnh chạy không có cả `PATH`.
        from .sandbox import RunSpec
        r = self._sandbox().run(RunSpec(argv=list(cmd), cwd=self.path, env=clean_env(), timeout=float(timeout),
                                        max_output=4000))
        if r.timed_out:
            return CheckResult(ok=False, output=r.stderr[-4000:])
        return CheckResult(ok=r.exit_code == 0, output=(r.stdout + r.stderr)[-4000:])

    def stack(self) -> Stack:
        """Stack của repo khách (ADR-0013); quyết định lệnh lint/test thật sự chạy được."""
        return detect(self.path)

    def lint(self, *paths: str) -> CheckResult:
        argv = self.stack().lint
        if argv is None: return CheckResult(ok=False, output="không có lệnh lint cho stack này")
        return self._run(*argv, *paths)

    def test(self, *args: str) -> CheckResult:
        argv = self.stack().test
        if argv is None: return CheckResult(ok=False, output="không có lệnh test cho stack này")
        return self._run(*argv, *args)

    def run_checks(self) -> dict[str, Any]:
        """Đúng định dạng `pull-requests.local_checks`. Không có coverage thì bỏ trống chứ không bịa.
        Stack không nhận ra (hoặc không có lệnh) → `lint`/`tests` là False và `stack` nói rõ lý do:
        thà nói không kiểm được còn hơn báo pass bằng một lệnh không liên quan đến code vừa sửa."""
        st = self.stack()
        lint, test = self.lint(), self.test()
        # K2.5: `sandbox` là BẰNG CHỨNG, không phải trang trí — người đọc PR phải biết lint/test vừa chạy bằng
        # quyền người vận hành (`subprocess`) hay trong container mạng tắt. `sandbox=subprocess` không phải lỗi,
        # nhưng nó nói rõ lớp bảo vệ nào ĐANG có, thay vì để người đọc suy từ tài liệu.
        return {"lint": lint.ok, "tests": test.ok, "lint_output": lint.output, "test_output": test.output,
                "stack": st.name, "sandbox": self._sandbox().name}

    def commit_all(self, message: str) -> str:
        exclude_worktrees(self.repo)  # rác lint/test không vào index (F14), kể cả khi worktree được tạo bởi bản cũ
        _git(self.path, "add", "-A")
        # Rác đã bị theo dõi từ trước (branch cũ commit nhầm) thì gỡ khỏi index ở ticket này — không xoá file trên đĩa.
        tracked = [x for x in _git(self.path, "ls-files", "--cached").splitlines()
                   if "__pycache__/" in x or x.endswith((".pyc", ".pyo")) or x.startswith((".ruff_cache/", ".pytest_cache/", ".mypy_cache/"))]
        if tracked:
            _git(self.path, "rm", "-r", "-q", "--cached", "--", *tracked)
        # message qua stdin: argv trên Windows đi qua codepage console, tiếng Việt thành mojibake
        _git(self.path, "-c", "user.name=agent", "-c", "user.email=agent@company.local", "commit", "-F", "-", stdin=message)
        return _git(self.path, "rev-parse", "--short", "HEAD")

    def fresh(self) -> Path:
        """Bỏ worktree + branch cũ và tạo lại từ `base` hiện tại (ticket làm lại sau xung đột tích hợp)."""
        self.remove(delete_branch=True)
        return self.create()

    def base_sha(self) -> str:
        """Điểm rẽ nhánh thật (merge-base) — diff/changed_files so với đây, không phụ thuộc HEAD của repo đã đi tiếp."""
        return _git(self.repo, "merge-base", self.base, self.branch)

    def changed_files(self) -> list[str]:
        out = _git(self.path, "diff", "--name-only", self.base_sha())
        return [x for x in out.splitlines() if x]

    def has_changes(self) -> bool:
        return bool(_git(self.path, "status", "--porcelain")) or bool(self.changed_files())

    def head_sha(self) -> str:
        return _git(self.path, "rev-parse", "--short", "HEAD")

    def head_is_wip(self) -> bool:
        """Commit đầu nhánh là WIP do `keep_wip` tạo (lượt trước giữ lại) — chưa từng thành PR."""
        return _git(self.path, "log", "-1", "--format=%s").startswith("wip(")

    def keep_wip(self, message: str) -> str | None:
        """Lần chạy trước dừng giữa chừng (hết lượt tool / ngân sách) để lại file dở: GIỮ LẠI thành một commit WIP
        trên branch ticket để lần này làm tiếp, thay vì `reset()` vứt hết. Đo được 2026-09-06 (TCK-CR-DEV-001-02):
        40 lượt tool viết devserver dở, `workspace_reset` xoá sạch, lần 2 bắt đầu từ số 0 và lại vượt 40 lượt.
        Trả về sha WIP, hoặc None nếu không có gì dở."""
        if not self.dirty(): return None
        return self.commit_all(message)

    def reset(self) -> bool:
        """Bỏ mọi sửa đổi chưa commit (tracked + untracked, kể cả thư mục) để về đúng HEAD của branch ticket.
        Lần chạy trước lỗi giữa chừng có thể để lại file dở; không dọn thì lần làm lại commit luôn rác đó.
        Trả về True nếu có gì để dọn."""
        if not self.dirty(): return False
        _git(self.path, "checkout", "--", ".")
        _git(self.path, "clean", "-fd")
        return True

    def dirty(self) -> bool:
        """Có sửa đổi chưa commit (so với HEAD của branch ticket). Khác `has_changes` (so với điểm rẽ nhánh): lần làm lại
        sau một PR bị từ chối vẫn thấy commit cũ trên branch, nên chỉ `dirty()` mới nói agent lần này có làm gì không."""
        return bool(_git(self.path, "status", "--porcelain"))

    def diff(self, max_chars: int = 20_000) -> str:
        """Diff so với điểm rẽ nhánh (gồm cả phần chưa commit) để reviewer/QA đọc; cắt để không phá ngữ cảnh.

        Ghép theo TỪNG FILE, mã nguồn trước — file sinh tự động/hợp đồng (openapi, lockfile, snapshot) xuống cuối
        — rồi mới cắt, và NÓI RÕ file nào bị bỏ. `git diff` xếp theo đường dẫn nên `api/QLKH/openapi.yaml` đứng
        trước `qlkh/**.py`: đo được 2026-09-06 (QLKH-012) một lần sinh lại openapi.yaml 804 dòng ăn hết hạn mức,
        đẩy toàn bộ code thật ra ngoài; security-engineer kết luận "thiếu diff của erasure_*.py" — đọc đúng cái nó
        nhận được, nhưng cái nó nhận được không phải sự thật. Reviewer bị cắt mà KHÔNG BIẾT mình bị cắt là chỗ hại
        nhất: nó kết luận thiếu bằng chứng, ticket bị chặn oan."""
        files = [f for f in _git(self.path, "diff", "--name-only", self.base_sha()).splitlines() if f]
        if not files:
            return ""
        ordered = sorted(files, key=lambda f: (1 if is_generated(f) else 0, f))
        parts: list[str] = []
        used, bo_qua = 0, []
        for f in ordered:
            d = _git(self.path, "diff", self.base_sha(), "--", f)
            if not d:
                continue
            if used + len(d) > max_chars:
                bo_qua.append(f)
                continue
            parts.append(d); used += len(d)
        out = "\n".join(parts)
        if bo_qua:
            out += ("\n… (cắt cho vừa hạn mức; KHÔNG có diff của: " + ", ".join(bo_qua) +
                    " — đừng kết luận các file này thiếu, hãy đọc `changed_files` hoặc xin diff riêng)")
        return out


@dataclass
class MergeResult:
    ok: bool
    sha: str = ""
    conflicts: list[str] | None = None
    # Merge hỏng mà KHÔNG có file xung đột (file chưa track bị ghi đè, index khoá...): lỗi môi trường, không phải
    # lỗi của ticket — người gọi không được coi là xung đột (audit 2026-09-23).
    error: str = ""


@dataclass
class DeliveryResult:
    """Kết quả một lần giao (ADR-0027). `problems` là chuỗi `tag_conflict:<tag>@<sha>` / `diverged:<sha>`; `pushed` là
    None khi không push, True/False khi có push (lỗi push nằm ở `push_error`, không làm `ok` sai vì bản giao cục bộ đã có)."""
    ok: bool
    sha: str = ""            # sha ĐẦY ĐỦ đã giao (để rollback đối chiếu bằng --force-with-lease)
    short: str = ""
    tag: str = ""
    branch: str = ""
    previous: str | None = None   # sha nhánh release TRƯỚC lần giao này (None = nhánh vừa được tạo)
    tag_created: bool = False
    branch_moved: bool = False
    problems: list[str] = field(default_factory=list)
    pushed: bool | None = None
    push_error: str = ""


def _git_ok(repo: Path, *args: str, timeout: int = 120) -> tuple[bool, str]:
    """Như `_git` nhưng không ném: (ok, stdout hoặc stderr rút gọn). Dùng cho thao tác được phép thất bại (push)."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *NO_HOOKS, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=clean_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"git {' '.join(args)}: quá {timeout}s"
    return (True, r.stdout.strip()) if r.returncode == 0 else (False, (r.stderr or r.stdout).strip()[-300:])


@dataclass
class Integration:
    """Nhánh tích hợp trong worktree riêng `.worktrees/_integration`; merge ticket vào đây, không checkout repo gốc."""
    repo: Path
    branch: str = "company/integration"
    base: str = "HEAD"
    release_branch: str = "company/release"  # ADR-0027: con trỏ "đang chạy production"; tag v* là lịch sử bất biến

    @property
    def path(self) -> Path: return self.repo / ".worktrees" / "_integration"

    def rev(self, ref: str) -> str | None:
        """Sha đầy đủ của một ref (commit mà tag trỏ tới, không phải object tag); None nếu ref không tồn tại."""
        ok, out = _git_ok(self.repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        return out if ok and out else None

    def deliver(self, version: str, message: str, sha: str | None = None,
                push_remote: str | None = None) -> DeliveryResult:
        """Tag `v<version>` tại `sha` (mặc định: đầu nhánh tích hợp; orchestrator truyền sha đã kiểm trên staging) +
        fast-forward `release_branch` tới đó (ADR-0027). Idempotent; không bao giờ ghi đè tag đã có ở sha khác, không
        bao giờ ép nhánh release khi nó không fast-forward được."""
        sha = self.rev(sha) if sha else self.rev(self.branch)
        if sha is None:
            raise WorkspaceError(f"nhánh tích hợp {self.branch} chưa tồn tại (hoặc sha không có): chưa có gì để giao")
        tag = f"v{version}"
        res = DeliveryResult(ok=True, sha=sha, short=sha[:7], tag=tag, branch=self.release_branch,
                             previous=self.rev(self.release_branch))
        existing = self.rev(f"refs/tags/{tag}")
        if existing is None:
            msg = self.repo / ".worktrees" / "_tag_msg.txt"
            msg.parent.mkdir(parents=True, exist_ok=True)
            msg.write_text(message, encoding="utf-8", newline="\n")
            try:
                _git(self.repo, "-c", "user.name=ops", "-c", "user.email=release@company.local",
                     "tag", "-a", "-F", str(msg), tag, sha)
            finally:
                msg.unlink(missing_ok=True)
            res.tag_created = True
        elif existing != sha:
            res.problems.append(f"tag_conflict:{tag}@{existing[:7]}")
        prev = res.previous
        if prev is None:
            _git(self.repo, "branch", self.release_branch, sha); res.branch_moved = True
        elif prev != sha:
            if _git_ok(self.repo, "merge-base", "--is-ancestor", prev, sha)[0]:
                _git(self.repo, "branch", "-f", self.release_branch, sha); res.branch_moved = True
            elif _git_ok(self.repo, "merge-base", "--is-ancestor", sha, prev)[0]:
                pass  # nhánh release đã đi qua sha này (release sau lên production trước): không lùi, không phải lỗi
            else:
                res.problems.append(f"diverged:{prev[:7]}")
        res.ok = not res.problems
        if push_remote:
            refs = [f"refs/heads/{self.release_branch}"] if res.branch_moved else []
            if res.tag_created or existing == sha: refs.append(f"refs/tags/{tag}")
            res.pushed, res.push_error = self.push(push_remote, *refs) if refs else (True, "")
        return res

    def rollback_delivery(self, to_sha: str | None, expected: str, push_remote: str | None = None) -> DeliveryResult:
        """Lùi `release_branch` về `to_sha` (lần giao trước); None = xoá nhánh (đây là lần giao đầu). Tag giữ nguyên.
        Chỉ lùi khi nhánh đang trỏ đúng sha đã giao (`expected`): release sau đã lên thì bản này bị thay thế, không
        lùi đè lên nó (`superseded`). Push dùng `--force-with-lease` với `expected` để không đè thứ người khác vừa đẩy."""
        res = DeliveryResult(ok=True, sha=to_sha or "", short=(to_sha or "")[:7], branch=self.release_branch, previous=expected)
        cur = self.rev(self.release_branch)
        if cur is None:
            res.problems.append("missing:nhánh release không còn")
        elif cur != expected:
            res.problems.append(f"superseded:{cur[:7]}")
        elif to_sha is None:
            _git(self.repo, "branch", "-D", self.release_branch); res.branch_moved = True
        elif cur != to_sha:
            _git(self.repo, "branch", "-f", self.release_branch, to_sha); res.branch_moved = True
        res.ok = not res.problems
        if push_remote and res.branch_moved:
            spec = f"{to_sha}:refs/heads/{self.release_branch}" if to_sha else f":refs/heads/{self.release_branch}"
            res.pushed, res.push_error = self.push(push_remote, spec, lease=(self.release_branch, expected))
        return res

    def remote_url(self, remote: str) -> str | None:
        """URL của một remote trong repo khách (None nếu remote không có) — để biết nó có phải GitHub không (ADR-0038)."""
        ok, out = _git_ok(self.repo, "remote", "get-url", remote)
        return out if ok and out else None

    def base_branch(self) -> str | None:
        """Tên nhánh của `base` (ví dụ `main`); None khi `base` là commit/HEAD tách rời — PR cần một nhánh đích thật."""
        ok, out = _git_ok(self.repo, "rev-parse", "--abbrev-ref", self.base)
        return out if ok and out and out != "HEAD" else None

    def push(self, remote: str, *refspecs: str, lease: tuple[str, str] | None = None) -> tuple[bool, str]:
        """`git push` với env đã lọc bí mật và không hook; thất bại trả (False, stderr rút gọn) chứ không ném —
        bản giao cục bộ đã có, push hỏng là việc người xử lý (audit `delivery.push_failed`)."""
        args = ["push"]
        if lease: args.append(f"--force-with-lease=refs/heads/{lease[0]}:{lease[1]}")
        ok, out = _git_ok(self.repo, *args, remote, *refspecs)
        return ok, ("" if ok else out)

    def ensure(self) -> str:
        """Tạo nhánh (từ `base`) và worktree nếu chưa có; trả về sha hiện tại của nhánh tích hợp."""
        if not _git(self.repo, "branch", "--list", self.branch):
            _git(self.repo, "branch", self.branch, self.base)
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            exclude_worktrees(self.repo)
            _git(self.repo, "worktree", "add", str(self.path), self.branch)
        return self.sha()

    def sha(self) -> str:
        return _git(self.repo, "rev-parse", "--short", self.branch)

    def checkout_at(self, sha: str) -> Path:
        """Worktree tách rời (detached) ở ĐÚNG `sha` — nơi deploy/hồi quy chạy thứ đã staged, không phải đầu nhánh
        tích hợp vốn tiếp tục nhận merge của ticket approved sau staging (audit 2026-09-23). Thư mục đặt theo sha
        đầy đủ nên không bao giờ phải checkout lại và không va nhau giữa các RC; đã có thì dùng lại."""
        full = _git(self.repo, "rev-parse", "--verify", f"{sha}^{{commit}}")
        # no-ky-thuat: một thư mục mỗi sha đã staged không bao giờ dọn, ổn tới vài chục release, quay lại khi .worktrees/_releases vượt ~50 thư mục hoặc repo khách lớn hơn ~100MB
        path = self.repo / ".worktrees" / "_releases" / full
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            exclude_worktrees(self.repo)
            _git(self.repo, "worktree", "add", "--detach", str(path), full)
        return path

    def rev_list_count(self, ticket_branch: str) -> int:
        """Số commit của `ticket_branch` chưa có trong nhánh tích hợp (0 = không có gì mới để merge)."""
        self.ensure()
        out = _git(self.path, "rev-list", "--count", f"{self.branch}..{ticket_branch}")
        return int(out.strip() or 0)

    def merge(self, ticket_branch: str, message: str) -> MergeResult:
        """merge --no-ff ticket vào nhánh tích hợp. Xung đột → abort, trả về file xung đột; hỏng vì lý do khác → `error`
        (không có `conflicts`). Nhánh tích hợp không đổi trong cả hai trường hợp."""
        self.ensure()
        # `merge -F -` không đọc stdin như `commit`; ghi message ra file UTF-8 để tránh mojibake argv trên Windows
        msg = self.repo / ".worktrees" / "_merge_msg.txt"
        msg.write_text(message, encoding="utf-8", newline="\n")
        r = subprocess.run(["git", "-C", str(self.path), *NO_HOOKS, "-c", "user.name=delivery-lead",
                            "-c", "user.email=lead@company.local", "merge", "--no-ff", "-F", str(msg), ticket_branch],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=clean_env())
        msg.unlink(missing_ok=True)
        if r.returncode == 0:
            return MergeResult(ok=True, sha=self.sha())
        conflicts = [x for x in _git(self.path, "diff", "--name-only", "--diff-filter=U").splitlines() if x]
        ab = subprocess.run(["git", "-C", str(self.path), *NO_HOOKS, "merge", "--abort"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=clean_env())
        if conflicts and ab.returncode != 0:  # worktree tích hợp còn dở merge: lỗi môi trường, không phải xung đột
            return MergeResult(ok=False, conflicts=[],
                               error=f"merge --abort hỏng, worktree tích hợp còn dở merge: {ab.stderr.strip()[:200]}")
        if not conflicts:
            return MergeResult(ok=False, conflicts=[], error=r.stderr.strip()[:300])
        return MergeResult(ok=False, conflicts=conflicts)

    def files(self) -> list[str]:
        return [x for x in _git(self.repo, "ls-tree", "-r", "--name-only", self.branch).splitlines() if x]
