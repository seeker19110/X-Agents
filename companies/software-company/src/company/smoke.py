"""Smoke test do ORCHESTRATOR tự chạy (ADR-0029): khởi động sản phẩm theo `runtime` ghi trong spec, gọi một request
thật, ghi lại lệnh / mã thoát / mã HTTP. Kết quả là bằng chứng máy sinh gắn vào `release-events.smoke` — cùng
nguyên tắc với `local_checks.verified_by=workspace` của PR (ADR-0010): model chỉ khai, code mới chứng.

Vì sao có module này: 2026-09-06 (QLKH) bốn gate xanh, 389 test pass, 25 release, nhưng sản phẩm KHÔNG có điểm vào
nào chạy được — `status=deployed` của release-engineer là lời khai, `regression-staging` của QA là verdict đọc diff,
không ai từng khởi động một tiến trình. Bảng "claim nào cần bằng chứng nào" trong skill `verification-before-completion`
(obra/superpowers) nói thẳng: *Agent completed → xem diff; agent tự báo "success" là KHÔNG ĐỦ*.

Ranh giới tin cậy: `runtime.command` là của spec — spec-writer viết, người ký ở Gate 1 — chạy trong worktree tích hợp
với env đã lọc bí mật (`clean_env`), có timeout, và bị giết khi xong. Nó không mạnh hơn lệnh lint/test của khách mà
`run_checks` đã chạy từ ADR-0013."""
from __future__ import annotations

import shlex
import socket
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .workspace import clean_env

VERIFIED_BY = "orchestrator"
DEFAULT_TIMEOUT_S = 30
STDERR_TAIL = 800


@dataclass(frozen=True)
class Runtime:
    """`approved-specs.payload.runtime`: cách khởi động sản phẩm để kiểm bằng máy.

    `command` có thể chứa `{port}`; `port=0` = orchestrator chọn cổng trống rồi thế vào. `python` ở đầu lệnh được
    thay bằng interpreter đang chạy orchestrator (cùng .venv với lint/test của `Stack`), để "python" trên Windows
    không rơi vào Store alias."""
    command: tuple[str, ...]
    port: int = 0
    path: str = "/"
    timeout_s: int = DEFAULT_TIMEOUT_S
    expect_status: int = 200
    # ADR-0039: đường dẫn compose file TRONG repo khách để `company.deploy` dựng môi trường chạy thật. Đọc ở đây
    # vì nó là cùng một khối `runtime` của spec; rỗng = không khai (deploy tự dò `docker-compose.yml`).
    deploy: str = ""

    def argv(self, port: int) -> list[str]:
        out = [a.replace("{port}", str(port)) for a in self.command]
        if out and out[0] in {"python", "python3"}:
            out[0] = sys.executable
        return out


def parse_runtime(spec_payload: dict[str, Any] | None) -> Runtime | None:
    """Đọc `runtime` từ payload của `approved-specs`; thiếu hoặc không đủ trường → None (không đoán)."""
    rt = (spec_payload or {}).get("runtime")
    if not isinstance(rt, dict):
        return None
    cmd = rt.get("command")
    if isinstance(cmd, str):
        cmd = shlex.split(cmd, posix=True)
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
        return None
    try:
        port = int(rt.get("port", 0) or 0)
        timeout = int(rt.get("timeout_s", DEFAULT_TIMEOUT_S) or DEFAULT_TIMEOUT_S)
        expect = int(rt.get("expect_status", 200) or 200)
    except (TypeError, ValueError):
        return None
    path = str(rt.get("health") or rt.get("path") or "/")
    if not path.startswith("/"):
        path = "/" + path
    return Runtime(tuple(cmd), port=port, path=path, timeout_s=max(1, min(timeout, 300)), expect_status=expect,
                   deploy=str(rt.get("deploy") or ""))


def unverified(reason: str) -> dict[str, Any]:
    """Không chạy được smoke — nói thẳng, không báo pass giả (đúng tinh thần `local_checks.unverified`)."""
    return {"unverified": True, "reason": reason, "verified_by": VERIFIED_BY}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# Mọi probe ở đây (smoke + `deploy._smoke_running`) nhắm 127.0.0.1: `urlopen` mặc định theo `http_proxy` kể cả cho
# loopback, nên máy có proxy sẽ đo nhầm proxy thay vì sản phẩm (audit 2026-09-23). Opener không proxy.
_LOOPBACK = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _probe(url: str) -> int | None:
    try:
        with _LOOPBACK.open(url, timeout=2) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def run_smoke(root: Path, rt: Runtime, sandbox: Any = None,
              probe: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Khởi động `rt.command` trong `root`, poll `http://127.0.0.1:<port><path>` tới khi có phản hồi hoặc hết
    `timeout_s`, rồi giết tiến trình. Trả về bằng chứng: lệnh thật đã chạy, cổng, mã HTTP, thời gian, mã thoát nếu
    tiến trình chết trước khi trả lời, đuôi stderr để người đọc hiểu vì sao, và `sandbox` — TÊN lớp bảo vệ đã
    dùng (K2.5), vì "sản phẩm chạy được" và "sản phẩm chạy được bằng quyền của người vận hành" là hai bằng chứng
    khác nhau.

    Đây là điểm gọi rủi ro nhất trong ba điểm của ADR-0035: `rt.command` do spec-writer viết (người ký ở Gate 1),
    và không như lint/test, nó phải MỞ mạng để probe được — nên `RunSpec(network=True, port=port)`: backend
    container mở đúng một cổng loopback thay vì tắt mạng.

    `probe(base_url)` (ADR-0047, DAST): gọi khi sản phẩm vừa trả lời đúng health, TRƯỚC khi bị giết — để đo thêm
    trên chính tiến trình đang chạy thay vì khởi động lần hai."""
    from .sandbox import RunSpec, SubprocessSandbox
    sb = sandbox if sandbox is not None else SubprocessSandbox()
    port = rt.port or free_port()
    argv = rt.argv(port)
    url = f"http://127.0.0.1:{port}{rt.path}"
    out: dict[str, Any] = {"verified_by": VERIFIED_BY, "command": argv, "cwd": str(root), "port": port, "url": url,
                           "ok": False, "http_status": None, "exit_code": None, "elapsed_s": 0.0,
                           "sandbox": sb.name}
    t0 = time.monotonic()
    try:
        proc = sb.spawn(RunSpec(argv=argv, cwd=root, env=clean_env(), timeout=float(rt.timeout_s),
                                network=True, port=port))
    except OSError as e:
        out["error"] = f"{type(e).__name__}: {e}"[:300]
        out["elapsed_s"] = round(time.monotonic() - t0, 2)
        return out
    try:
        while time.monotonic() - t0 < rt.timeout_s:
            rc = proc.poll()
            if rc is not None:  # chết trước khi trả lời: mã thoát là bằng chứng
                out["exit_code"] = rc
                break
            st = _probe(url)
            if st is not None:
                out["http_status"] = st
                out["ok"] = st == rt.expect_status
                if out["ok"] and probe is not None:
                    probe(f"http://127.0.0.1:{port}")
                break
            time.sleep(0.25)
        else:
            out["error"] = f"không trả lời {url} trong {rt.timeout_s}s"
    finally:
        out["elapsed_s"] = round(time.monotonic() - t0, 2)
        if proc.poll() is None:
            proc.kill()
        if err := proc.stderr_tail(STDERR_TAIL):
            out["stderr_tail"] = err
    return out
