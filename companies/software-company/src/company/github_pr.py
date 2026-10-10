"""Mở PR thật trên GitHub từ nhánh giao hàng vào nhánh của khách — mở, KHÔNG merge (ADR-0038).

Khi `--deliver-pr` bật và `--push-remote` là một remote GitHub, sau khi `Integration.deliver` đã push
`company/release` + tag, orchestrator gọi `gh pr create` (hoặc tìm PR đang mở cùng head/base để dùng lại).
Khách review bằng UI quen thuộc rồi mới ký gate `acceptance`; đưa PR vào `main` vẫn là việc của khách
(ADR-0027 §5 giữ nguyên). Review nội bộ giữa các ticket vẫn theo nhánh tích hợp (ADR-0011), không đổi.

`gh` chạy trên máy vận hành với env đã lọc bí mật (`clean_env` bỏ `GH_*`/`GITHUB_*`), nên xác thực phải nằm
trong cấu hình của gh trên đĩa (`gh auth login`), cùng nguyên tắc với credential git của ADR-0027 §4. Thiếu gh,
chưa đăng nhập, mạng hỏng → `PrResult(ok=False, reason=…)`; orchestrator ghi audit `delivery.pr_failed` và đi
tiếp — bản giao (tag + nhánh) đã có, người mở PR tay.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from xagents_core.sandbox import clean_env

# https://github.com/o/r(.git) · git@github.com:o/r(.git) · ssh://git@github.com/o/r(.git)
_GITHUB = re.compile(r"^(?:https?://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def github_slug(url: str | None) -> str | None:
    """`owner/repo` nếu URL remote là GitHub; None với remote khác (GitLab, đường dẫn cục bộ, bare repo…)."""
    m = _GITHUB.match((url or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


class PrRecord(TypedDict, total=False):
    """Trường `pr` trong `delivery.done` (K6.3: kiểu hoá thay vì `dict[str, Any]`). Ba hình: có PR (`url`…);
    không có gì để mở (`skipped`); gh lỗi (`error`). `base`/`head` do orchestrator thêm."""
    url: str
    number: int | None
    created: bool
    slug: str
    base: str
    head: str
    skipped: str
    error: str


@dataclass
class PrResult:
    """`ok=False` kèm `reason` là lý do không có PR (không phải GitHub, gh lỗi…); `created=False` khi dùng lại PR đang mở."""
    ok: bool
    url: str = ""
    number: int | None = None
    created: bool = False
    slug: str = ""
    reason: str = ""

    def record(self) -> PrRecord:
        """Dạng ghi vào `delivery.done` / `Orchestrator.delivered[rid]["pr"]` — dựng lại được từ audit-log."""
        if self.ok: return {"url": self.url, "number": self.number, "created": self.created, "slug": self.slug}
        return {"error": self.reason, "slug": self.slug}


def _gh(repo: Path, *args: str, timeout: int = 60) -> tuple[bool, str]:
    """`gh …` trong repo khách; không ném — (ok, stdout) hoặc (False, lý do rút gọn). Ngoại lệ có lý do của
    test quy ước `test_sandbox_noi_vao_cong_ty.py` (như git: argv do code ghép, không chạy mã của khách)."""
    try:
        r = subprocess.run(["gh", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=clean_env(), timeout=timeout)
    except FileNotFoundError:
        return False, "gh: không có trên máy (cài GitHub CLI rồi `gh auth login`)"
    except subprocess.TimeoutExpired:
        return False, f"gh {' '.join(args[:2])}: quá {timeout}s"
    except OSError as e:   # có trên máy mà không chạy được (quyền, binary hỏng); `strerror`: không lộ đường dẫn
        return False, f"gh: không chạy được ({e.strerror or e})"
    return (True, r.stdout.strip()) if r.returncode == 0 else (False, (r.stderr or r.stdout).strip()[-300:])


def open_pr(repo: Path, remote_url: str | None, head: str, base: str, title: str, body: str) -> PrResult:
    """PR `head → base` trên repo GitHub của `remote_url`. Idempotent: PR đang mở cùng head/base thì trả lại nó."""
    slug = github_slug(remote_url)
    if slug is None:
        return PrResult(ok=False, reason=f"remote không phải GitHub: {remote_url or '(không có URL)'}")
    ok, out = _gh(repo, "pr", "list", "--repo", slug, "--head", head, "--base", base, "--state", "open",
                  "--json", "number,url", "--limit", "1")
    if not ok: return PrResult(ok=False, slug=slug, reason=out)
    try:
        found = json.loads(out or "[]")
    except json.JSONDecodeError:
        found = []
    if found:
        first = found[0]
        num = first.get("number")
        return PrResult(ok=True, url=str(first.get("url") or ""), number=int(num) if num is not None else None,
                        created=False, slug=slug)
    ok, out = _gh(repo, "pr", "create", "--repo", slug, "--base", base, "--head", head, "--title", title, "--body", body)
    if not ok: return PrResult(ok=False, slug=slug, reason=out)
    url = out.splitlines()[-1].strip() if out else ""
    m = re.search(r"/pull/(\d+)", url)
    return PrResult(ok=True, url=url, number=int(m.group(1)) if m else None, created=True, slug=slug)
