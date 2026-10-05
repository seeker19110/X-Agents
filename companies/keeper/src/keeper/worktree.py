"""Worktree riêng cho một ticket bảo trì (BT5, `DAC-TA-KEEPER.md` §7).

╔══════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ LUẬT TUYỆT ĐỐI — đọc trước khi sửa một dòng nào của file này                                             ║
║                                                                                                          ║
║ KHÔNG BAO GIỜ chạy `git reset --hard`, `git clean`, `git checkout -- .` trên CHECKOUT CHUNG              ║
║ (`C:/Users/liend/Claude-Agents`). Có phiên khác đang mở đúng thư mục đó, với việc dở chưa commit —       ║
║ `git worktree list` cho thấy hàng chục worktree cùng lúc. Một lệnh dọn ở đó xoá việc của người khác,     ║
║ im lặng và không hoàn tác được.                                                                          ║
║                                                                                                          ║
║ Vì thế `keeper` CHỈ thao tác trong worktree của chính ticket, và mọi hàm có thể phá được (`close`,       ║
║ `discard_local_changes`) tự KIỂM rồi TỪ CHỐI (ném `SharedCheckoutRefused`) khi mục tiêu không phải một   ║
║ worktree phụ. "Cẩn thận thì không sao" không phải là một cơ chế — chốt phải nằm trong mã.                ║
║                                                                                                          ║
║ Cách kiểm (git tự trả lời, không đoán theo tên thư mục): trong một worktree PHỤ, `git rev-parse          ║
║ --git-dir` là `.git/worktrees/<tên>` còn `--git-common-dir` là `.git`; ở checkout CHÍNH hai cái BẰNG     ║
║ nhau. Kiểm theo tên thư mục thì đổi tên là thủng.                                                        ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════════╝

Khuôn lấy từ `software-company/src/company/workspace.py` (`TicketWorkspace`): `create()` idempotent,
`_git()` chạy không hook với `env=clean_env()` và `encoding="utf-8"`. **Sao khuôn, không import chéo** —
`keeper` không phụ thuộc `company` (bất biến I6: mỗi công ty chỉ điền trường của lõi).

Khác `TicketWorkspace` một chỗ có chủ ý: worktree của `keeper` nằm ở `../Claude-Agents-wt-keeper-<id>` (cạnh
repo) chứ không phải `.worktrees/` bên trong repo — vì `keeper` bảo trì CHÍNH repo đang chứa nó, và một thư
mục con lạ sẽ tự thành đầu vào của `drift-detector` ngay vòng quét sau.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from xagents_core.sandbox import clean_env

WORKTREE_PREFIX = "Claude-Agents-wt-keeper-"
BRANCH_PREFIX = "chore/keeper-"
# Hook của repo là mã chạy dưới quyền người vận hành lúc commit/checkout: orchestrator không bao giờ chạy hook.
NO_HOOKS: tuple[str, ...] = ("-c", "core.hooksPath=/dev/null")
_SLUG_BAD = re.compile(r"[^A-Za-z0-9._-]+")


class WorktreeError(Exception):
    """Lệnh git thất bại, hoặc tham số không dựng được worktree."""


class SharedCheckoutRefused(WorktreeError):
    """Từ chối thao tác vì mục tiêu là checkout CHUNG (hoặc không phải worktree phụ nào cả)."""


def git_env() -> dict[str, str]:
    """Env cho lệnh `git`: `clean_env()` rồi bỏ MỌI biến `GIT_*`.

    `clean_env()` chỉ lọc thứ trông như khoá, nên `GIT_DIR` / `GIT_WORK_TREE` / `GIT_INDEX_FILE` của tiến
    trình cha vẫn lọt qua. Chúng ghi đè phép dò repo của git: đặt `GIT_DIR` trỏ vào một worktree phụ rồi hỏi
    về thư mục khác là `is_linked_worktree` trả True cho nhầm chỗ — tức vòng qua đúng cái chốt bên dưới. Chốt
    nào hỏi git thì phải hỏi một `git` không bị môi trường lái."""
    return {k: v for k, v in clean_env().items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str, timeout: int = 120, env: Mapping[str, str] | None = None) -> str:
    """`env` chỉ để THÊM biến sau khi `git_env()` đã bỏ mọi `GIT_*` của tiến trình cha — vd `GIT_INDEX_FILE` của
    `content_tree`. Thứ tự hợp nhất cố ý: biến của chính hàm gọi thắng, biến thừa kế không lọt vào."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *NO_HOOKS, *args], capture_output=True, text=True,
                           encoding="utf-8", env=git_env() | dict(env or {}), timeout=timeout)
    except subprocess.TimeoutExpired as e:  # pragma: no cover - chỉ xảy ra khi git treo thật
        raise WorktreeError(f"git {' '.join(args)}: quá {timeout}s") from e
    if r.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def content_tree(path: Path) -> str:
    """Danh tính NỘI DUNG của worktree `path`: id cây git của mọi file track + chưa track (trừ file bị
    `.gitignore`), như thể `git add -A` rồi `write-tree` — nhưng trên một index TẠM, index thật không đổi.

    Đây là danh tính patch mà bằng chứng hai chiều gắn vào (ADR keeper 0001): xác định (cùng nội dung ⇒ cùng id,
    không phụ thuộc giờ hay locale), không phụ thuộc commit (worktree sạch ⇒ bằng `HEAD^{tree}`, nên commit đúng
    nội dung đã đo không làm đổi danh tính). `read-tree HEAD` trước `add -A` để file đã track mà khớp
    `.gitignore` vẫn được tính, đúng như index thật. Chỉ ghi blob rời vào kho object chung (git gc tự dọn).
    Lỗi git (thư mục không có, không phải repo) ⇒ `WorktreeError`."""
    with tempfile.TemporaryDirectory(prefix="keeper-index-") as tmp:
        idx = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(path, "read-tree", "HEAD", env=idx)
        _git(path, "add", "-A", env=idx)
        return _git(path, "write-tree", env=idx)


def repo_root(path: Path) -> Path:
    """Gốc cây git chứa `path`; `path` nguyên trạng khi nó không nằm trong repo git nào.

    Lệnh CLI nhận một đường dẫn repo rồi dùng nó cho HAI việc: chạy `git` (tự dò lên gốc) và ghép đường dẫn file
    (không dò). Trỏ vào thư mục con là hai việc lệch nhau — `drift` báo tín hiệu giả, `run` ghi lạc chỗ,
    `publish` tìm worktree sai chỗ hoặc dựng worktree mới ngay trong checkout chung (đo 2026-09-28). Quy về gốc
    một lần ở cửa vào thì hết lệch."""
    try:
        return Path(_git(path, "rev-parse", "--show-toplevel"))
    except WorktreeError:
        return path


def slug(ticket_id: str) -> str:
    """Mã ticket (`KEEP:0:dependency:pydantic`) → mảnh dùng được cho tên thư mục và tên nhánh."""
    out = _SLUG_BAD.sub("-", ticket_id).strip("-")
    if not out:
        raise WorktreeError(f"ticket_id {ticket_id!r} không còn ký tự nào dùng được cho tên nhánh")
    return out


def is_linked_worktree(path: Path) -> bool:
    """True chỉ khi `path` là một worktree PHỤ (xem khung luật ở đầu file). Không phải repo git → False."""
    try:
        git_dir = _git(path, "rev-parse", "--absolute-git-dir")
        common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    except WorktreeError:
        return False
    return Path(git_dir) != Path(common)


def refuse_shared_checkout(path: Path) -> None:
    """Chốt. Gọi TRƯỚC mọi thao tác có thể mất dữ liệu."""
    if not is_linked_worktree(path):
        raise SharedCheckoutRefused(
            f"{path} không phải worktree riêng của keeper — từ chối. Checkout chung có thể đang được phiên khác "
            f"dùng; xem khung luật ở đầu keeper/src/keeper/worktree.py")


def _discard(path: Path) -> bool:
    """Thao tác dọn THẬT, không có chốt. Private có chủ ý: ngoài `discard_local_changes` (đã kiểm) thì chỉ ca
    "chiều ngược" gọi nó, để chứng minh chốt không phải trang trí. Đừng gọi từ mã sản xuất."""
    if not _git(path, "status", "--porcelain"):
        return False
    _git(path, "checkout", "--", ".")
    _git(path, "clean", "-fd")
    return True


@dataclass
class KeeperWorktree:
    """Worktree `../Claude-Agents-wt-keeper-<id>` trên nhánh `chore/keeper-<id>`.

    `repo` là checkout chung; nó CHỈ nhận lệnh quản lý worktree (`worktree add/remove`, `branch`) — không
    lệnh nào trong file này chạy `reset`/`clean`/`checkout` lên nó."""

    repo: Path
    ticket_id: str
    base: str = "HEAD"

    @property
    def slug(self) -> str: return slug(self.ticket_id)
    @property
    def branch(self) -> str: return f"{BRANCH_PREFIX}{self.slug}"
    @property
    def path(self) -> Path: return self.repo.parent / f"{WORKTREE_PREFIX}{self.slug}"

    def create(self) -> Path:
        """Idempotent: đã có thư mục thì trả về nguyên trạng, KHÔNG dọn — việc dở của lượt trước phải sống sót
        (bài học `keep_wip`: `reset` mỗi lần vào lại làm lượt hai bắt đầu từ số 0)."""
        if self.path.exists():
            return self.path
        if _git(self.repo, "branch", "--list", self.branch):
            _git(self.repo, "worktree", "add", str(self.path), self.branch)
        else:
            _git(self.repo, "worktree", "add", "-b", self.branch, str(self.path), self.base)
        return self.path

    def close(self, delete_branch: bool = True) -> None:
        """Dọn worktree (và mặc định cả nhánh). Từ chối nếu `path` vì lý do gì đó lại là checkout chung."""
        if self.path.exists():
            refuse_shared_checkout(self.path)
            _git(self.repo, "worktree", "remove", "--force", str(self.path))
        else:
            _git(self.repo, "worktree", "prune")
        if delete_branch and _git(self.repo, "branch", "--list", self.branch):
            _git(self.repo, "branch", "-D", self.branch)

    def commit_tracked(self, message: str) -> None:
        """`git commit -a` TRONG worktree của ticket (I1 cho phép commit ở đây, không ở nơi nào khác). Chỉ file
        đã được theo dõi — không vơ file lạ chưa track vào PR. Không hook (`NO_HOOKS`), chốt checkout chung
        đứng trước."""
        refuse_shared_checkout(self.path)
        if not _git(self.path, "status", "--porcelain", "--untracked-files=no").strip():
            return  # không có gì để commit (lần gọi lại sau khi đã commit) — không phải lỗi
        _git(self.path, "commit", "-a", "-m", message)

    def discard_local_changes(self, target: Path | None = None) -> bool:
        """Bỏ sửa đổi chưa commit TRONG worktree của ticket. `target` chỉ để ca kiểm thử trỏ vào chỗ sai và
        chứng minh chốt bắt được; mã sản xuất luôn để mặc định."""
        path = self.path if target is None else target
        refuse_shared_checkout(path)
        return _discard(path)


def open_worktree(ticket_id: str, repo: Path, base: str = "HEAD") -> KeeperWorktree:
    """Mở (hoặc dùng lại) worktree của ticket. Gọi hai lần là an toàn."""
    wt = KeeperWorktree(repo=repo, ticket_id=ticket_id, base=base)
    wt.create()
    return wt
