"""`release-clerk`: dòng `CHANGELOG.md` + mục `docs/sessions/<ngày>.md` (BT7, `DAC-TA-KEEPER.md` §9).

## Vì sao có chỗ trống `(#PR)` thay vì chờ tới khi biết số

`AGENTS.md` §10: tài liệu đi CÙNG PR, không đi sau nó — nhưng số PR **chỉ tồn tại sau `gh pr create`**. Nên
thứ tự bắt buộc là: `record()` ghi dòng mang chỗ trống → commit → mở PR → `fill_pr_number()` thay chỗ trống
bằng `(#n)` → **commit tiếp vào CHÍNH PR đó**. Không bao giờ mở PR thứ hai để vá số: một PR "dọn dẹp" là đúng
thứ §10 cấm, và nó tiêu mất suất PR duy nhất mà bất biến I3 cho phép (`budget.can_open_pr`).

## Vì sao không có thao tác ghi nào ở file này

Mọi lần chạm đĩa đi qua `patcher` (`fix_docs` để THÊM, `apply_edits` để SỬA TẠI CHỖ). Nhờ vậy đường cấm I4
(`.git/`, `.github/`, `llm.yaml`, `*.sqlite*`), chốt worktree (`refuse_shared_checkout`) và chốt coverage áp
cho cả đường release mà không phải nhắc lại — một bản sao thứ hai của bảng chặn là một bản sẽ lệch.

`fill_pr_number` NỔ khi không tìm thấy chỗ trống. Im lặng bỏ qua thì một dòng CHANGELOG thiếu số PR vĩnh viễn
mà không ai thấy — đúng khuôn "số xanh vì rỗng".

## Vì sao file này cũng nói "cái gì được đổi sau lần đo" (ADR keeper 0002)

`record`/`fill_pr_number` là thứ DUY NHẤT `keeper` ghi vào worktree SAU lần đo hai chiều. `unmeasured_changes`
nằm cạnh chúng để tập đường dẫn và dòng được phép không lệch khỏi thứ hai hàm ấy thật sự ghi.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .events import PatchProposal, ReleaseNote, Ticket
from .patcher import Edit, apply_edits, fix_docs
from .worktree import blob_text, refuse_shared_checkout, tree_changes

__all__ = ["CHANGELOG_PATH", "PR_PLACEHOLDER", "compose", "fill_pr_number", "record", "unmeasured_changes"]

#: Chỗ trống cho số PR. Cố ý mang hình dạng `(#…)` y như dòng thật để `grep '(#'` thấy nó, chứ không phải một
#: dấu hiệu vô hình kiểu chuỗi rỗng.
PR_PLACEHOLDER = "(#PR)"

#: Hai chỗ duy nhất dòng release được ghi (`record` → `fix_docs`, `fill_pr_number`). Hằng số trong MÃ, không lấy từ
#: payload model hay từ note: tập đường dẫn được đổi sau lần đo mà ai ghi được topic cũng nới được thì không còn
#: là một tập (ADR keeper 0002).
CHANGELOG_PATH = "CHANGELOG.md"
_SESSION_LOG = re.compile(r"docs/sessions/(\d{4}-\d{2}-\d{2})\.md")


def _ref(pr_number: int | None) -> str:
    return PR_PLACEHOLDER if pr_number is None else f"(#{pr_number})"


def compose(ticket: Ticket, *, pr_number: int | None = None) -> ReleaseNote:
    """Dòng CHANGELOG + mục nhật ký phiên cho một ticket bảo trì.

    Dòng CHANGELOG theo khuôn của repo (`fix|feat|chore(<scope>): <việc> (#n)`); mục nhật ký mang mã ticket
    để người đọc lần ngược về signal đã sinh ra nó."""
    ref = _ref(pr_number)
    return ReleaseNote(
        ticket_id=ticket.ticket_id,
        pr_number=pr_number,
        changelog_line=f"- fix(keeper): {ticket.subject} — bảo trì tự động, tier {ticket.risk_tier} {ref}",
        session_line=f"- `{ticket.ticket_id}` — {ticket.subject} (tier {ticket.risk_tier}) {ref}",
    )


def record(root: Path, note: ReleaseNote, *, session_date: str,
           changelog: str = CHANGELOG_PATH) -> PatchProposal:
    """Ghi cả hai dòng vào worktree PHỤ của ticket. Đi qua `patcher.fix_docs`, không tự mở file."""
    return fix_docs(root, note.ticket_id, changelog_line=note.changelog_line,
                    session_line=note.session_line, session_date=session_date, changelog=changelog)


def fill_pr_number(root: Path, note: ReleaseNote, pr_number: int, *, session_date: str,
                   changelog: str = CHANGELOG_PATH) -> ReleaseNote:
    """Thay `(#PR)` bằng `(#<pr_number>)` TẠI CHỖ, trong chính worktree của PR đang mở.

    Không thêm dòng nào: dòng đã nằm trong PR từ commit trước, đây chỉ là commit thứ hai vào cùng PR.

    Chốt worktree đứng TRƯỚC lần đọc file đầu tiên. `apply_edits` cũng có chốt ấy, nhưng nó chỉ chạy sau khi
    hàm này đã `read_text` cả `CHANGELOG.md` lẫn nhật ký phiên — gọi nhầm trên checkout chung là đọc nội dung
    đang làm dở của phiên KHÁC (và để nó lọt vào thông điệp lỗi / `Edit`) trước khi bị từ chối. Một chốt đứng
    sau thao tác nó bảo vệ thì không phải là chốt."""
    refuse_shared_checkout(root)
    if note.pr_number is not None:
        raise ValueError(f"note của {note.ticket_id} đã có số PR (#{note.pr_number}) — không điền lần hai")
    moi = note.model_copy(update={
        "pr_number": pr_number,
        "changelog_line": note.changelog_line.replace(PR_PLACEHOLDER, _ref(pr_number)),
        "session_line": note.session_line.replace(PR_PLACEHOLDER, _ref(pr_number)),
    })
    edits: list[Edit] = []
    for rel in (changelog, f"docs/sessions/{session_date}.md"):
        target = root / rel
        # Nhật ký phiên có thể chưa tồn tại (note chỉ có dòng CHANGELOG); CHANGELOG thiếu chỗ trống thì rơi
        # xuống `raise` bên dưới — không có nhánh nào im lặng.
        if not target.exists():
            continue
        cu = target.read_text(encoding="utf-8")
        if PR_PLACEHOLDER not in cu:
            continue
        edits.append(Edit(rel, cu.replace(PR_PLACEHOLDER, _ref(pr_number))))
    if not edits:
        # Lần `publish()` trước đã điền + commit nhưng push hỏng → gọi lại: số đã nằm trong CHANGELOG, chỉ cần
        # trả note mang số để push nốt. Không có số nào thì vẫn nổ như cũ.
        if (root / changelog).exists() and _ref(pr_number) in (root / changelog).read_text(encoding="utf-8"):
            return moi
        raise ValueError(
            f"không tìm thấy {PR_PLACEHOLDER} trong {changelog}/docs/sessions/{session_date}.md — "
            f"`record()` chưa chạy, hay số PR đã điền rồi?")
    apply_edits(root, edits, operation="fix_docs", ticket_id=note.ticket_id,
                summary=f"điền số PR #{pr_number}")
    return moi


def _allowed_lines(rel: str, note: ReleaseNote) -> list[re.Pattern[str]] | None:
    """Dòng được THÊM vào `rel` sau lần đo: dòng trống, dòng của chính note (`(#PR)` hoặc đã điền `(#<số>)`), và
    tiêu đề `# Phiên <ngày>` mà `fix_docs` đặt cho nhật ký mới. `None` ⇒ `rel` không phải file release."""
    if rel == CHANGELOG_PATH:
        lines = [note.changelog_line]
    elif m := _SESSION_LOG.fullmatch(rel):
        lines = [note.session_line, f"# Phiên {m.group(1)}"]
    else:
        return None
    so = r"\(\#(?:PR|\d+)\)"
    return [re.compile(re.escape(x).replace(re.escape(PR_PLACEHOLDER), so)) for x in ["", *lines]]


def unmeasured_changes(path: Path, measured: str, pushed: str, note: ReleaseNote) -> list[str]:
    """Mọi khác biệt từ cây ĐÃ ĐO (`patch_id`) tới cây SẮP PUSH không phải dòng release của chính `note`.
    Rỗng ⇒ thứ sắp push là đúng thứ đã đo cộng dòng release (ADR keeper 0002).

    Chỉ THÊM dòng, không sửa/xoá: patch chỉ-tài-liệu (đúng `CHANGELOG.md`) vẫn bị gắn trọn, vì dòng nó đã đo
    không được đổi sau lần đo — tập đường dẫn được phép không phải cửa sau cho nội dung tuỳ ý. Đọc blob thẳng từ
    kho object, không qua văn bản diff (lệ thuộc cấu hình, ADR keeper 0001). Lỗi git ⇒ `WorktreeError`."""
    bad: list[str] = []
    for status, rel in tree_changes(path, measured, pushed):
        allowed = _allowed_lines(rel, note)
        if allowed is None or status not in ("A", "M"):
            bad.append(f"{status} {rel}")
            continue
        old = blob_text(path, measured, rel).splitlines() if status == "M" else []
        new = blob_text(path, pushed, rel).splitlines()
        it = iter(new)
        if not all(line in it for line in old):
            bad.append(f"{rel}: sửa/xoá dòng đã đo")
            continue
        if la := [ln for ln in Counter(new) - Counter(old) if not any(p.fullmatch(ln) for p in allowed)]:
            bad.append(f"{rel}: thêm dòng không phải của note {note.ticket_id}: {la[0][:80]!r}")
    return bad
