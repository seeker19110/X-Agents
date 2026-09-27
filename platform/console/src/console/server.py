"""Server console: `http.server` thuần thư viện chuẩn, phục vụ trang tĩnh + `/api/*`.

Hợp đồng nằm ở console/API.md. Đây là bề mặt đầu tiên cho phép duyệt gate qua HTTP nên
mọi lớp phòng thủ ở dưới là bắt buộc, không phải tuỳ chọn:

  * chỉ bind loopback (muốn khác thì phải có `--i-know` và chịu cảnh báo),
  * mỗi lần chạy sinh token ngẫu nhiên, ghi `console/.console-token` quyền 0600,
  * `/api/*` bắt buộc header `X-Console-Token`, so sánh hằng thời gian,
  * từ chối `Host` không phải loopback (chống DNS rebinding) và `Origin` khác nguồn,
  * mặc định `--readonly`: mọi POST bị chặn cho tới khi chạy `--allow-decide`,
  * không bao giờ log token hay body.
"""

from __future__ import annotations

import atexit
import ipaddress
import json
import logging
import os
import secrets
import socket
import sys
import time
from collections.abc import Iterable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

logger = logging.getLogger("console.server")

PACKAGE_DIR = Path(__file__).resolve().parent
CONSOLE_DIR = PACKAGE_DIR.parents[1]          # .../console
REPO_ROOT = CONSOLE_DIR.parents[1]            # .../X-Agents (console nằm dưới platform/, ADR-0011)
STATIC_DIR = PACKAGE_DIR / "static"
TOKEN_FILE = CONSOLE_DIR / ".console-token"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8200
DEFAULT_COMPANY_DB = REPO_ROOT / "companies" / "software-company" / "company.sqlite"
DEFAULT_KEEPER_DB = REPO_ROOT / "companies" / "keeper" / "keeper.sqlite"

DEFAULT_ENGINE_INTERVAL = 30.0   # giây giữa hai nhịp `run --watch` khi trang không nói gì khác

MAX_BODY_BYTES = 1 << 20  # 1 MiB: body của /api/gate/decide chỉ là vài trường ngắn.

# `/api/stream`: đẩy trạng thái mới ngay khi bus đổi, thay cho việc trang tự hỏi 10 giây một lần.
# Nhịp dò rẻ (chỉ `stat()` hai file), nên để ngắn; nhịp tim giữ kết nối sống qua proxy và cho
# client biết server còn đó ngay cả khi chẳng có gì đổi.
STREAM_POLL_SECONDS = 1.0
STREAM_HEARTBEAT_SECONDS = 15.0

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
}


# Vỏ PWA: đường ở gốc -> tên file trong static/. Không phải dữ liệu, không cần token — giống
# hệt /static/*, và cả hai đều không nói gì về nội dung bus.
_ROOT_FILES = {"/sw.js": "sw.js", "/manifest.webmanifest": "manifest.webmanifest"}


def is_loopback_host(host: str) -> bool:
    """Chỉ nhận địa chỉ CHẮC CHẮN trỏ về máy này. Không phân giải DNS: tên lạ = không loopback.

    Trước 2026-09-13 hàm này kết thúc bằng `startswith("127.")` — một lỗ thật, đo trong audit (mục S1 của
    `docs/reports/2026-09-13-audit.md`): mọi TÊN MIỀN bắt đầu bằng "127." cũng khớp, nên
    `127.0.0.1.evil.example` (kẻ tấn công chỉ cần một bản ghi A trỏ về 127.0.0.1, không cần rebinding) đi lọt
    cả hàng rào `Host` lẫn `Origin`, vì cả hai gọi chung hàm này.

    Nay quyết bằng `ipaddress`: một chuỗi hoặc PHÂN TÍCH ĐƯỢC thành IP loopback (127.0.0.0/8, ::1), hoặc là
    đúng chữ "localhost", hoặc không phải loopback. Siết chặt hơn ở một chỗ có chủ ý: dạng viết tắt `127.1`
    nay bị từ chối (`ip_address` đòi đủ bốn octet) — fail-closed, và người gõ tay vẫn còn `127.0.0.1`.
    """
    h = (host or "").strip().strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def host_header_is_loopback(header: str | None) -> bool:
    """`Host` có thể kèm cổng và IPv6 trong ngoặc vuông. Thiếu header (HTTP/1.0) thì cho qua."""
    if header is None:
        return True
    value = header.strip()
    if not value:
        return True
    if value.startswith("["):
        value = value[1 : value.find("]")] if "]" in value else value[1:]
    elif value.count(":") == 1:
        value = value.split(":", 1)[0]
    return is_loopback_host(value)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def write_token_file(token: str, path: Path = TOKEN_FILE) -> Path:
    """Tạo file token với quyền 0600 ngay từ lúc tạo (os.open), không phải ghi rồi mới chmod:
    khoảng giữa hai bước đó là lúc tiến trình khác đọc trộm được."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")
    return path


def db_fingerprint(paths: Iterable[Path | None]) -> str:
    """Dấu vân tay rẻ tiền của các file bus: đổi thì nghĩa là có event mới đáng đọc lại.

    Dùng `st_mtime_ns` chứ không phải `st_mtime`: đồng hồ giây của một số filesystem quá thô,
    hai lần ghi sát nhau sẽ trùng dấu vân tay và trang đứng im dù bus đã đổi. Kèm `st_size` để
    bắt cả trường hợp hiếm là ghi đè đúng bằng nano-giây cũ. File chưa có (công ty chưa chạy lần
    nào) là một trạng thái hợp lệ, không phải lỗi — nó có dấu vân tay riêng nên lúc file xuất
    hiện, trang tự cập nhật. Theo dõi cả WAL: commit chưa checkpoint chỉ đổi `<db>-wal`, không đổi file chính."""
    parts: list[str] = []
    for path in paths:
        for component in (path, Path(str(path) + "-wal")) if path is not None else (None,):
            try:
                stat = component.stat() if component is not None else None
            except OSError:
                stat = None
            parts.append("-" if stat is None else f"{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


def sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    """Một khung Server-Sent Events. `data` luôn một dòng vì JSON đã thoát sẵn xuống dòng."""
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n".encode()


class GateHTTPError(Exception):
    """Lỗi đã biết, kèm mã HTTP muốn trả về."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _gate_error_status(exc: BaseException) -> int:
    """decide.py ném GateError với thông điệp tiếng Việt. Ưu tiên mã do nó tự khai báo;
    nếu không có thì suy từ thông điệp: đã quyết rồi = 409, bị chặn = 403, còn lại = 400."""
    for attr in ("http_status", "status", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 400 <= value < 600:
            return value
    text = str(exc).lower()
    if any(k in text for k in ("đã quyết", "đã được quyết", "already decided", "trùng", "conflict")):
        return HTTPStatus.CONFLICT
    if any(k in text for k in ("không được phép", "four-eyes", "four eyes", "allowlist", "từ chối", "forbidden")):
        return HTTPStatus.FORBIDDEN
    return HTTPStatus.BAD_REQUEST


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Đóng tab hay tắt máy giữa chừng là chuyện thường của một công cụ cục bộ, nhất là khi
        `/api/stream` giữ kết nối mở lâu. Mặc định của `socketserver` là in cả traceback ra
        stderr cho mỗi lần như vậy — nhiễu terminal của người vận hành và làm chìm mất lỗi thật.
        Chỉ hạ những lỗi *mất kết nối*; mọi lỗi khác vẫn nổi lên nguyên vẹn."""
        exc = sys.exc_info()[1]
        if isinstance(exc, ConnectionError | TimeoutError):
            logger.debug("client %s ngắt kết nối: %s", client_address, exc)
            return
        super().handle_error(request, client_address)

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        token: str,
        readonly: bool = True,
        allow_config: bool = False,
        allow_submit: bool = False,
        allow_engine: bool = False,
        company_db: Path | None = None,
        keeper_db: Path | None = None,
        llm_yaml: dict[str, Path] | None = None,
        static_dir: Path = STATIC_DIR,
        stream_max_seconds: float | None = None,
        deliver_remote: str | None = None,
    ) -> None:
        if ":" in host and not host.startswith("["):
            self.address_family = socket.AF_INET6
        self.token = token
        self.readonly = readonly
        # Sửa llm.yaml là quyền RIÊNG, không đi kèm --allow-decide: duyệt gate và đổi model là hai rủi ro khác nhau.
        self.allow_config = allow_config
        # Giao việc (publish event vào bus) cũng là quyền RIÊNG: người nhận việc mới không nhất thiết là người được duyệt gate.
        self.allow_submit = allow_submit
        # Bật/tắt `orchestrator run --watch` là quyền RIÊNG và nặng nhất: nó tạo tiến trình con GỌI MODEL và
        # GHI vào bus, khác hẳn ba quyền trên (chỉ ghi một event hoặc một file cấu hình).
        self.allow_engine = allow_engine
        self.company_db = company_db
        self.keeper_db = keeper_db
        self.llm_yaml = llm_yaml
        self.static_dir = Path(static_dir)
        # None = stream sống tới khi client đóng (chế độ chạy thật). Test đặt một giá trị nhỏ
        # để vòng lặp tự kết thúc thay vì phải giết thread.
        self.stream_max_seconds = stream_max_seconds
        from console.engine import COMPANY, KEEPER, EngineManager
        self.engine = EngineManager({COMPANY: company_db, KEEPER: keeper_db}, deliver_remote=deliver_remote)
        # Con của console chết cùng console: cả đường đóng bình thường (`server_close`) lẫn đường thoát
        # đột ngột (`atexit`) đều phải dọn, nếu không một orchestrator mồ côi vẫn ghi bus sau khi tắt trang.
        atexit.register(self.engine.stop_all)
        super().__init__((host.strip("[]"), port), ConsoleHandler)

    def server_close(self) -> None:
        self.engine.stop_all()
        super().server_close()

    @property
    def port(self) -> int:
        return int(self.server_address[1])


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer  # type: ignore[assignment]
    server_version = "console"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # --- tiện ích trả lời ---------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str, csp_nonce: str | None = None) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if csp_nonce:
            # `'self'` cho các ES module ở /static/js/ (K7.1); `'nonce-…'` cho đúng một script inline là khối
            # bootstrap ngay trên. Không `unsafe-inline`, không CDN — trang cố ý không có phụ thuộc ngoài.
            self.send_header("Content-Security-Policy",
                             f"default-src 'self'; script-src 'self' 'nonce-{csp_nonce}'; "
                             # Trang nạp font từ Google Fonts (`index.html:8-10`) — đó là ngoại lệ DUY NHẤT với
                             # "không CDN" và nó có từ trước K7; siết CSP mà quên nó là trang mất hẳn phông chữ.
                             "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                             "font-src 'self' https://fonts.gstatic.com; "
                             "img-src 'self' data:; connect-src 'self'; "
                             "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def log_message(self, fmt: str, *args: Any) -> None:
        """Chỉ log dòng request thô của http.server. Token nằm ở header, body không bao giờ đi qua đây."""
        logger.debug("%s %s", self.address_string(), fmt % args)

    def log_error(self, fmt: str, *args: Any) -> None:
        logger.debug("%s %s", self.address_string(), fmt % args)

    # --- phòng thủ ----------------------------------------------------------

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin or origin == "null":
            return not origin  # "null" (sandbox/file://) coi như nguồn lạ.
        scheme, _, rest = origin.partition("://")
        if scheme not in {"http", "https"} or not rest:
            return False
        if not host_header_is_loopback(rest):
            return False
        port = rest.rsplit(":", 1)[-1] if (":" in rest and not rest.endswith("]")) else ""
        return port == str(self.server.port)

    def _authorized(self) -> bool:
        given = self.headers.get("X-Console-Token") or ""
        return secrets.compare_digest(given, self.server.token)

    def _guard(self) -> bool:
        """Kiểm tra chung cho mọi request. Trả False nghĩa là đã trả lời lỗi rồi."""
        if not host_header_is_loopback(self.headers.get("Host")):
            # 404 chứ không 403: không xác nhận cho kẻ tấn công rằng có server ở đây.
            self._error(HTTPStatus.NOT_FOUND, "không có")
            return False
        if not self._origin_allowed():
            self._error(HTTPStatus.FORBIDDEN, "Origin không hợp lệ")
            return False
        return True

    # --- định tuyến ---------------------------------------------------------

    def _path(self) -> str:
        return self.path.split("?", 1)[0].split("#", 1)[0]

    def do_GET(self) -> None:
        if not self._guard():
            return
        path = self._path()
        if path == "/healthz":
            self._json(HTTPStatus.OK, {"ok": True})
        elif path == "/":
            self._serve_index()
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/") :])
        elif path in _ROOT_FILES:
            # Phải phục vụ ở GỐC chứ không phải dưới /static/: service worker chỉ điều khiển
            # được những đường nằm trong thư mục chứa nó, mà nó cần điều khiển "/". Manifest đi
            # cùng cho tiện — cả hai đều là vỏ app, không mang dữ liệu nào.
            self._serve_static(_ROOT_FILES[path])
        elif path == "/api/state":
            if not self._authorized():
                self._error(HTTPStatus.UNAUTHORIZED, "thiếu hoặc sai X-Console-Token")
                return
            self._api_state()
        elif path == "/api/settings":
            if not self._authorized():
                self._error(HTTPStatus.UNAUTHORIZED, "thiếu hoặc sai X-Console-Token")
                return
            self._api_settings_get()
        elif path == "/api/gate/brief":
            if not self._authorized():
                self._error(HTTPStatus.UNAUTHORIZED, "thiếu hoặc sai X-Console-Token")
                return
            self._api_gate_brief()
        elif path == "/api/stream":
            if not self._authorized():
                self._error(HTTPStatus.UNAUTHORIZED, "thiếu hoặc sai X-Console-Token")
                return
            self._api_stream()
        elif path.startswith("/api/"):
            if not self._authorized():
                self._error(HTTPStatus.UNAUTHORIZED, "thiếu hoặc sai X-Console-Token")
                return
            self._error(HTTPStatus.NOT_FOUND, "không có đường dẫn này")
        else:
            self._error(HTTPStatus.NOT_FOUND, "không có đường dẫn này")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        if not self._guard():
            return
        path = self._path()
        if not path.startswith("/api/"):
            self._error(HTTPStatus.NOT_FOUND, "không có đường dẫn này")
            return
        if not self._authorized():
            self._error(HTTPStatus.UNAUTHORIZED, "thiếu hoặc sai X-Console-Token")
            return
        if path not in {"/api/gate/decide", "/api/settings", "/api/request", "/api/engine"}:
            self._error(HTTPStatus.NOT_FOUND, "không có đường dẫn này")
            return
        if path == "/api/gate/decide" and self.server.readonly:
            self._error(HTTPStatus.FORBIDDEN, "console đang ở chế độ chỉ đọc; chạy lại với --allow-decide để duyệt gate")
            return
        if path == "/api/settings" and not self.server.allow_config:
            self._error(HTTPStatus.FORBIDDEN, "sửa cấu hình model bị khoá; chạy lại với --allow-config")
            return
        if path == "/api/request" and not self.server.allow_submit:
            self._error(HTTPStatus.FORBIDDEN, "giao việc bị khoá; chạy lại với --allow-submit")
            return
        if path == "/api/engine" and not self.server.allow_engine:
            self._error(HTTPStatus.FORBIDDEN, "bật/tắt động cơ bị khoá; chạy lại với --allow-engine")
            return
        try:
            payload = self._read_json_body()
        except GateHTTPError as e:
            self._error(e.status, e.message)
            return
        if path == "/api/settings":
            self._api_settings_post(payload)
        elif path == "/api/engine":
            self._api_engine(payload)
        elif path == "/api/request":
            self._api_submit(payload)
        else:
            self._api_decide(payload)

    # --- xử lý ---------------------------------------------------------------

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise GateHTTPError(HTTPStatus.BAD_REQUEST, "Content-Length không hợp lệ") from None
        if length < 0 or length > MAX_BODY_BYTES:
            raise GateHTTPError(HTTPStatus.BAD_REQUEST, "body quá lớn")
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GateHTTPError(HTTPStatus.BAD_REQUEST, "body không phải JSON hợp lệ") from None
        if not isinstance(data, dict):
            raise GateHTTPError(HTTPStatus.BAD_REQUEST, "body phải là một object JSON")
        return data

    def _state(self) -> dict[str, Any]:
        """`/api/state` và `/api/stream` phải trả CÙNG một payload — trang đọc chung một hàm vẽ. Trạng thái
        động cơ đi kèm ở đây chứ không phải một route riêng: người trực hỏi "công ty có đang chạy không" cùng
        lúc với "có gate nào chờ tôi không", một lần đọc phải trả lời cả hai."""
        from console.collect import collect  # nhập trễ: lớp dữ liệu do agent khác viết song song.

        state = collect(self.server.company_db, self.server.keeper_db)
        state["engine"] = {**self.server.engine.status(), "allowed": self.server.allow_engine}
        return state

    def _api_state(self) -> None:
        try:
            state = self._state()
        except Exception:
            logger.exception("collect() thất bại")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "không đọc được trạng thái")
            return
        self._json(HTTPStatus.OK, state)

    def _api_gate_brief(self) -> None:
        """C8: hồ sơ bằng chứng của một gate, Markdown, để trang hiện cạnh nút Duyệt. GET và chỉ đọc — không cần
        `--allow-decide`: đọc bằng chứng phải rẻ hơn ký, nếu không thì người ta ký mà không đọc."""
        from console.brief import COMPANY, BriefUnavailable, gate_brief

        q = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
        subject = (q.get("id") or [""])[0]
        xuong = (q.get("xuong") or [COMPANY])[0]
        try:
            payload = gate_brief(self.server.company_db, subject, xuong=xuong,
                                 closed=(q.get("closed") or ["0"])[0] == "1")
        except BriefUnavailable as e:
            self._json(HTTPStatus.OK, {"ok": False, "subject_id": subject, "error": str(e)})
            return
        self._json(HTTPStatus.OK, {"ok": True, **payload})

    def _api_stream(self) -> None:
        """SSE: đẩy `/api/state` mỗi khi bus của một trong hai công ty đổi.

        Token đi ở header `X-Console-Token` như mọi `/api/*`, nên client dùng `fetch` +
        `ReadableStream` chứ không phải `EventSource` (`EventSource` không đặt được header, đẩy
        token vào query string thì `log_message` ghi thẳng token ra log).

        Không đặt `Content-Length` và đóng kết nối khi xong: thân bài kết thúc bằng chính việc
        đóng, đúng HTTP/1.1. Trang vẫn giữ nguyên đường `/api/state` để tự hỏi lại khi stream
        đứt, nên mất stream chỉ là chậm hơn, không phải hỏng.
        """
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command == "HEAD":
            return

        dbs = (self.server.company_db, self.server.keeper_db)
        fingerprint: str | None = None
        last_beat = 0.0
        deadline = None if self.server.stream_max_seconds is None else time.monotonic() + self.server.stream_max_seconds
        try:
            while deadline is None or time.monotonic() < deadline:
                # Dấu vân tay gồm cả động cơ: bấm Bật ở tab này phải hiện ngay ở tab kia, không chờ nhịp 10 giây.
                current = db_fingerprint(dbs) + "#" + self.server.engine.fingerprint()
                if current != fingerprint:
                    fingerprint = current
                    try:
                        state = self._state()
                    except Exception:
                        logger.exception("collect() thất bại trong /api/stream")
                        self.wfile.write(sse_frame("error", {"error": "không đọc được trạng thái"}))
                    else:
                        self.wfile.write(sse_frame("state", state))
                    self.wfile.flush()
                    last_beat = time.monotonic()
                elif time.monotonic() - last_beat >= STREAM_HEARTBEAT_SECONDS:
                    # Dòng bình luận SSE: client bỏ qua nội dung, nhưng việc ghi được là bằng
                    # chứng kết nối còn sống — và là chỗ duy nhất phát hiện client đã đóng.
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_beat = time.monotonic()
                time.sleep(STREAM_POLL_SECONDS)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # trang đã đóng tab hoặc tải lại — không có gì để dọn, thread tự kết thúc.

    def _api_decide(self, payload: dict[str, Any]) -> None:
        from console.decide import decide  # nhập trễ, xem _api_state.

        fields = ("subject_id", "xuong", "decision", "by", "reason")
        args: dict[str, str] = {}
        for name in fields:
            value = payload.get(name)
            if not isinstance(value, str) or not value.strip():
                self._error(HTTPStatus.BAD_REQUEST, f"thiếu hoặc sai trường '{name}'")
                return
            args[name] = value.strip()
        try:
            result = decide(
                self.server.company_db,
                self.server.keeper_db,
                subject_id=args["subject_id"],
                xuong=args["xuong"],
                decision=args["decision"],
                by=args["by"],
                reason=args["reason"],
            )
        except ValueError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
        except PermissionError as e:
            self._error(HTTPStatus.FORBIDDEN, str(e))
        except LookupError as e:
            self._error(HTTPStatus.NOT_FOUND, str(e))
        except Exception as e:
            if type(e).__name__ == "GateError" or hasattr(e, "http_status"):
                self._error(_gate_error_status(e), str(e))
                return
            logger.exception("decide() thất bại")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "lỗi không lường trước khi ghi quyết định")
        else:
            self._json(HTTPStatus.OK, result)

    def _api_engine(self, payload: dict[str, Any]) -> None:
        """Bật/tắt động cơ của một xưởng. Body: `{"xuong", "action": "start"|"stop", "interval"?, "by"}`."""
        from console.engine import EngineError

        action = payload.get("action")
        xuong = payload.get("xuong")
        by = payload.get("by")
        if action not in {"start", "stop"}:
            self._error(HTTPStatus.BAD_REQUEST, "trường 'action' phải là 'start' hoặc 'stop'")
            return
        if not isinstance(xuong, str) or not isinstance(by, str):
            self._error(HTTPStatus.BAD_REQUEST, "thiếu hoặc sai trường 'xuong'/'by'")
            return
        interval = payload.get("interval", DEFAULT_ENGINE_INTERVAL)
        try:
            if action == "start":
                result = self.server.engine.start(xuong, interval=interval, by=by)
            else:
                result = self.server.engine.stop(xuong, by=by)
        except EngineError as e:
            self._error(e.http_status, str(e))
        else:
            logger.info("động cơ %s: %s bởi %s", xuong, action, by)
            self._json(HTTPStatus.OK, result)

    def _api_submit(self, payload: dict[str, Any]) -> None:
        from console.submit import submit  # nhập trễ, xem _api_state.

        for field in ("xuong", "topic", "actor"):
            if not isinstance(payload.get(field), str):
                self._error(HTTPStatus.BAD_REQUEST, f"thiếu hoặc sai trường '{field}'")
                return
        if not isinstance(payload.get("payload"), dict):
            self._error(HTTPStatus.BAD_REQUEST, "thiếu hoặc sai trường 'payload' (phải là object JSON)")
            return
        try:
            result = submit(
                self.server.company_db,
                self.server.keeper_db,
                xuong=payload["xuong"],
                topic=payload["topic"],
                payload=payload["payload"],
                actor=payload["actor"],
            )
        except ValueError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
        except PermissionError as e:
            self._error(HTTPStatus.FORBIDDEN, str(e))
        except Exception as e:
            if type(e).__name__ == "SubmitError" or hasattr(e, "http_status"):
                self._error(_gate_error_status(e), str(e))
                return
            logger.exception("submit() thất bại")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "lỗi không lường trước khi giao việc")
        else:
            self._json(HTTPStatus.OK, result)

    def _api_settings_get(self) -> None:
        from console.settings import read_settings  # nhập trễ, xem _api_state.

        payload = read_settings(self.server.llm_yaml)
        payload["can_edit"] = self.server.allow_config
        self._json(HTTPStatus.OK, payload)

    def _api_settings_post(self, payload: dict[str, Any]) -> None:
        from console.settings import DEFAULT_LLM_YAML, SettingsError, update_settings

        company = payload.get("company")
        paths = self.server.llm_yaml or DEFAULT_LLM_YAML
        if not isinstance(company, str) or company not in paths:
            self._error(HTTPStatus.BAD_REQUEST, f"'company' phải là một trong {sorted(paths)}")
            return
        try:
            result = update_settings(
                paths[company],
                models=payload.get("models") or None,
                prefer=payload.get("prefer") or None,
                enable=payload.get("enable") or None,
                disable=payload.get("disable") or None,
            )
        except SettingsError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
        except OSError as e:
            logger.error("không ghi được llm.yaml: %s", e)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "không ghi được llm.yaml")
        else:
            result["company"] = company
            self._json(HTTPStatus.OK, result)

    # --- file tĩnh -----------------------------------------------------------

    def _serve_index(self) -> None:
        index = self.server.static_dir / "index.html"
        try:
            html = index.read_text(encoding="utf-8")
        except OSError:
            self._error(HTTPStatus.NOT_FOUND, "chưa có static/index.html")
            return
        # K7.2: giữ bootstrap INLINE (một trong hai phương án đặc tả cho phép), nhưng gắn nonce và bật CSP.
        #
        # Phương án kia — `GET /api/boot` — đổi token phiên sang query string ở lần tải đầu. Token đó là thứ
        # DUY NHẤT chặn một trang web khác trên cùng máy gọi vào console; đưa nó vào URL là đưa vào lịch sử
        # trình duyệt và `Referer`. Đổi một rủi ro nhỏ (script chèn được vào HTML) lấy một rủi ro lớn hơn thì
        # không đáng, nên chọn nonce: CSP chặn MỌI script inline khác, kể cả script chèn qua nội dung từ bus.
        nonce = secrets.token_urlsafe(16)
        boot = (
            f'<script nonce="{nonce}">window.__CONSOLE__='
            + json.dumps(
                {"token": self.server.token, "readonly": self.server.readonly,
                 "can_submit": self.server.allow_submit, "can_engine": self.server.allow_engine},
                ensure_ascii=False,
            )
            + ";</script>"
        )
        lowered = html.lower()
        cut = lowered.find("</head>")
        html = (html[:cut] + boot + html[cut:]) if cut != -1 else boot + html
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8", csp_nonce=nonce)

    def _serve_static(self, rel: str) -> None:
        root = self.server.static_dir.resolve()
        try:
            target = (root / rel).resolve()
        except OSError:
            self._error(HTTPStatus.NOT_FOUND, "không có file này")
            return
        if target != root and root not in target.parents:
            self._error(HTTPStatus.FORBIDDEN, "đường dẫn ra ngoài static/")
            return
        try:
            body = target.read_bytes()
        except OSError:
            self._error(HTTPStatus.NOT_FOUND, "không có file này")
            return
        self._send(HTTPStatus.OK, body, _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream"))


def make_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    token: str | None = None,
    readonly: bool = True,
    allow_config: bool = False,
    allow_submit: bool = False,
    allow_engine: bool = False,
    company_db: Path | None = None,
    keeper_db: Path | None = None,
    llm_yaml: dict[str, Path] | None = None,
    static_dir: Path = STATIC_DIR,
    stream_max_seconds: float | None = None,
    deliver_remote: str | None = None,
) -> ConsoleServer:
    return ConsoleServer(
        host,
        port,
        token=token or generate_token(),
        readonly=readonly,
        allow_config=allow_config,
        allow_submit=allow_submit,
        allow_engine=allow_engine,
        company_db=company_db,
        keeper_db=keeper_db,
        llm_yaml=llm_yaml,
        static_dir=static_dir,
        stream_max_seconds=stream_max_seconds,
        deliver_remote=deliver_remote,
    )
