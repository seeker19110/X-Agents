"""Cầu MCP: đưa ĐÚNG bảng tool của công ty vào CLI `claude -p`, không mở tool riêng của CLI (ADR-0024).

Vấn đề: provider `claude-code` chạy tool bằng phong bì văn bản (ADR-0023) — mỗi lượt tool là một tiến trình
`claude -p` mới, nên không có prompt cache giữa các lượt và phụ thuộc model tuân thủ định dạng. MCP giải cả hai:
CLI chạy MỘT tiến trình cho cả vòng tool, dùng tool-use gốc, và tự lo cache.

Đổi lại phải trả lời được: tool chạy ở đâu? Nếu để CLI dùng tool riêng (`Read`/`Write`/`Bash`) thì mất sandbox
`tools.py`. Nên tool vẫn chạy trong TIẾN TRÌNH CHA, nơi `ToolBox` thật đang sống:

    claude -p ──stdio──> `python -m company.mcp_bridge` ──socket 127.0.0.1──> ToolBox của runner
    (MCP client)          (MCP server mỏng, không logic)                      (allowlist, audit, đếm lượt)

Tiến trình con không biết gì về worktree hay allowlist: nó chỉ chuyển tiếp `tools/list` và `tools/call`. Mọi kiểm
tra (ranh giới đường dẫn, file bí mật, allowlist lệnh), vết `ToolBox.calls` cho audit `tools_used`, và số lần gọi
trong metrics vẫn nằm nguyên ở tiến trình cha — không nhân bản guardrail, không có đường vòng qua nó.

Socket nghe trên 127.0.0.1 cổng ngẫu nhiên, chỉ sống trong lúc gọi CLI, và mỗi lời gọi phải mang token dùng một
phiên (`secrets.token_hex`) — tiến trình khác trên cùng máy không gọi được tool vào worktree khách.
"""
from __future__ import annotations

import json
import secrets
import socket
import socketserver
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .guard import sanitize_tool_output
from .tools import ToolBox, ToolCall

SERVER_NAME = "company"          # tool hiện ra với CLI là `mcp__company__<tên>`
PROTOCOL_VERSION = "2025-06-18"
LINE_MAX = 8 * 1024 * 1024       # trần một dòng trên socket (kết quả tool đã bị ToolBox cắt trước đó)


def tool_full_name(name: str) -> str:
    return f"mcp__{SERVER_NAME}__{name}"


# ---------- phía cha: socket giữ ToolBox thật ----------

class ToolBridge:
    """Mở socket cục bộ phục vụ một `ToolBox` trong lúc CLI chạy. Dùng như context manager."""

    def __init__(self, toolbox: ToolBox, host: str = "127.0.0.1"):
        self.toolbox = toolbox
        self.sanitized: list[str] = []  # đoạn nghi injection đã lọc khỏi kết quả tool (runner ghi audit sau lượt)
        self.token = secrets.token_hex(16)
        self.host = host
        self._lock = threading.Lock()   # CLI gọi tuần tự, khoá chỉ để chắc chắn
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    # -- vòng đời --

    def __enter__(self) -> ToolBridge:
        bridge = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                for raw in self.rfile:
                    if len(raw) > LINE_MAX: break
                    try:
                        req = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        break
                    if not isinstance(req, dict) or not secrets.compare_digest(str(req.get("token", "")), bridge.token):
                        self.wfile.write(json.dumps({"ok": False, "error": "token sai"}).encode("utf-8") + b"\n")
                        break
                    self.wfile.write(json.dumps(bridge.serve(req), ensure_ascii=False).encode("utf-8") + b"\n")
                    self.wfile.flush()

        self._server = socketserver.ThreadingTCPServer((self.host, 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown(); self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = self._thread = None

    @property
    def port(self) -> int:
        if self._server is None: raise RuntimeError("ToolBridge chưa mở")
        return int(self._server.server_address[1])

    # -- nội dung phục vụ --

    def serve(self, req: dict[str, Any]) -> dict[str, Any]:
        op = req.get("op")
        if op == "list":
            return {"ok": True, "tools": [{"name": s.name, "description": s.description, "parameters": s.parameters}
                                          for s in self.toolbox.specs()]}
        if op == "call":
            name, args = str(req.get("name") or ""), req.get("args")
            with self._lock:
                try:
                    out = self.toolbox.call(ToolCall(id=str(req.get("id") or name), name=name,
                                                     args=args if isinstance(args, dict) else {}))
                except Exception as e:   # tool không tồn tại: là dữ liệu cho model, không phải sự cố của cầu
                    return {"ok": False, "error": f"{type(e).__name__}: {e}"}
            out, hits = sanitize_tool_output(out)  # cùng bộ lọc như vòng tool của runner (nội dung repo khách)
            if hits: self.sanitized.extend(f"{name}: {h}" for h in hits[:5])
            return {"ok": True, "result": out}
        return {"ok": False, "error": f"op lạ: {op}"}

    # -- tham số cho CLI --

    def allowed_tools(self) -> str:
        return ",".join(tool_full_name(s.name) for s in self.toolbox.specs())

    def mcp_config(self) -> dict[str, Any]:
        """`--mcp-config`: một server stdio duy nhất, chạy chính module này ở chế độ chuyển tiếp."""
        root = str(Path(__file__).resolve().parents[1])   # src/ — tiến trình con import được `company`
        # PYTHONIOENCODING: CLI sinh tiến trình con này, và locale của máy không chắc là UTF-8 — stdio khi ấy mang
        # bảng mã hệ thống. Xem chú thích ở `run`.
        env = {"PYTHONPATH": root, "PYTHONIOENCODING": "utf-8"}
        return {"mcpServers": {SERVER_NAME: {
            "command": sys.executable,
            "args": ["-m", "company.mcp_bridge", "--port", str(self.port), "--token", self.token],
            "env": env,
        }}}

    @contextmanager
    def config_file(self, dirpath: Path | None = None) -> Iterator[Path]:
        """File cấu hình MCP tạm, xoá ngay sau khi CLI xong (chứa token của phiên)."""
        import tempfile
        with tempfile.TemporaryDirectory(dir=str(dirpath) if dirpath else None) as d:
            p = Path(d) / "mcp.json"
            p.write_text(json.dumps(self.mcp_config(), ensure_ascii=False), encoding="utf-8")
            yield p


# ---------- phía con: MCP server stdio, chỉ chuyển tiếp ----------

class ProxyServer:
    """MCP server tối giản trên stdio (JSON-RPC 2.0): `initialize`, `tools/list`, `tools/call`, `ping`.
    Không có logic tool — mọi thứ hỏi ngược tiến trình cha qua socket."""

    def __init__(self, port: int, token: str, host: str = "127.0.0.1", timeout: float = 900.0):
        self.port, self.token, self.host, self.timeout = port, token, host, timeout

    def ask(self, req: dict[str, Any]) -> dict[str, Any]:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                s.sendall(json.dumps({**req, "token": self.token}, ensure_ascii=False).encode("utf-8") + b"\n")
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = s.recv(65536)
                    # Test `test_ask_server_dong_ket_noi_giua_chung_khong_co_dong_moi` và
                    # `test_ask_tra_loi_qua_line_max_thi_bao_loi_thay_vi_doc_het` (test_mcp_bridge.py) CHỨNG
                    # MINH cả hai nhánh chạy đúng. coverage.py không ghi được arc "->178"/"->exit" của chúng vì
                    # `break`/`return` ở đây thoát qua `with socket.create_connection(...) as s:` — cùng loại
                    # bounce-về-dòng-`with` đã thấy ở `llm.py::_complete_mcp` (đo được: arc thật là
                    # `(175, 170)`/`(177, 170)`, không phải `(175, 178)`/`(177, -170)`).
                    if not chunk: break  # pragma: no branch
                    buf += chunk
                    if len(buf) > LINE_MAX: return {"ok": False, "error": "trả lời quá dài"}  # pragma: no branch
            return dict(json.loads(buf.decode("utf-8"))) if buf.strip() else {"ok": False, "error": "cha không trả lời"}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            return {"ok": False, "error": f"không nối được tiến trình cha: {e}"}

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:   # notification (vd. notifications/initialized): không trả lời
            return None
        def ok(result: dict[str, Any]) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        if method == "initialize":
            return ok({"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                       "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"}})
        if method == "ping":
            return ok({})
        if method == "tools/list":
            r = self.ask({"op": "list"})
            if not r.get("ok"):
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(r.get("error"))}}
            return ok({"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["parameters"]}
                                 for t in r.get("tools", [])]})
        if method == "tools/call":
            p = msg.get("params") or {}
            r = self.ask({"op": "call", "name": p.get("name"), "args": p.get("arguments") or {}})
            text = str(r.get("result")) if r.get("ok") else f"lỗi: {r.get('error')}"
            return ok({"content": [{"type": "text", "text": text}], "isError": not r.get("ok")})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method lạ: {method}"}}

    def run(self, stdin: Any = None, stdout: Any = None) -> None:
        stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
        for line in stdin:
            if not line.strip(): continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict): continue
            resp = self.handle(msg)
            if resp is not None:
                # `ensure_ascii=True` (mặc định) là CỐ Ý, khác với đường socket ở trên.
                #
                # Kênh này là stdio của một tiến trình con do CLI sinh ra. Locale không phải UTF-8 thì
                # stdio đó mang bảng mã hệ thống — mà mọi thông điệp của
                # repo này đều là tiếng Việt, nên chỉ cần một lượt tool trả về chữ có dấu là
                # `UnicodeEncodeError` giết tiến trình con, và cả chế độ `mcp_tools: true` sập theo.
                #
                # Thoát thành `\uXXXX` làm đường dây thuần ASCII: đúng JSON, mọi client giải mã lại
                # nguyên vẹn, và không còn phụ thuộc bảng mã của console. Đây là lớp bảo vệ CUỐI —
                # `main()` vẫn ép stdio về UTF-8, và `mcp_config()` vẫn đặt PYTHONIOENCODING.
                stdout.write(json.dumps(resp) + "\n"); stdout.flush()


def force_utf8_stdio() -> None:
    """Ép stdio của tiến trình này về UTF-8.

    JSON-RPC qua stdio của MCP là UTF-8. Locale không phải UTF-8 thì stdio mang bảng mã hệ thống, nên
    chiều ĐỌC cũng hỏng chứ không riêng chiều ghi: tham số tool có chữ có dấu do CLI gửi sang sẽ bị
    giải mã sai hoặc ném lỗi. Chỉ làm ở `main()` — `run()` nhận stream do người gọi truyền vào thì
    không được tự ý đụng vào."""
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:      # stream bị thay bằng thứ khác (test, pipe lạ) thì bỏ qua
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    import argparse
    force_utf8_stdio()
    ap = argparse.ArgumentParser(description="MCP server chuyển tiếp tool của công ty cho CLI `claude -p`")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--token", required=True)
    a = ap.parse_args(argv)
    ProxyServer(a.port, a.token).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
