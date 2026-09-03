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

import json
import logging
import os
import secrets
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

logger = logging.getLogger("console.server")

PACKAGE_DIR = Path(__file__).resolve().parent
CONSOLE_DIR = PACKAGE_DIR.parents[1]          # .../console
REPO_ROOT = CONSOLE_DIR.parent                # .../X-Agents
STATIC_DIR = PACKAGE_DIR / "static"
TOKEN_FILE = CONSOLE_DIR / ".console-token"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8200
DEFAULT_COMPANY_DB = REPO_ROOT / "software-company" / "company.sqlite"
DEFAULT_STUDIO_DB = REPO_ROOT / "Studio-creators" / "studio.sqlite"

MAX_BODY_BYTES = 1 << 20  # 1 MiB: body của /api/gate/decide chỉ là vài trường ngắn.

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
    ".map": "application/json; charset=utf-8",
}


def is_loopback_host(host: str) -> bool:
    """Chỉ nhận tên/địa chỉ chắc chắn trỏ về máy này. Không phân giải DNS: tên lạ = không loopback."""
    h = (host or "").strip().strip("[]").lower()
    return h in {"localhost", "::1", "0:0:0:0:0:0:0:1"} or h == "127.0.0.1" or h.startswith("127.")


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

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        token: str,
        readonly: bool = True,
        allow_config: bool = False,
        company_db: Path | None = None,
        studio_db: Path | None = None,
        llm_yaml: dict[str, Path] | None = None,
        static_dir: Path = STATIC_DIR,
    ) -> None:
        if ":" in host and not host.startswith("["):
            self.address_family = socket.AF_INET6
        self.token = token
        self.readonly = readonly
        # Sửa llm.yaml là quyền RIÊNG, không đi kèm --allow-decide: duyệt gate và đổi model là hai rủi ro khác nhau.
        self.allow_config = allow_config
        self.company_db = company_db
        self.studio_db = studio_db
        self.llm_yaml = llm_yaml
        self.static_dir = Path(static_dir)
        super().__init__((host.strip("[]"), port), ConsoleHandler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer  # type: ignore[assignment]
    server_version = "console"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # --- tiện ích trả lời ---------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
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
        if path not in {"/api/gate/decide", "/api/settings"}:
            self._error(HTTPStatus.NOT_FOUND, "không có đường dẫn này")
            return
        if path == "/api/gate/decide" and self.server.readonly:
            self._error(HTTPStatus.FORBIDDEN, "console đang ở chế độ chỉ đọc; chạy lại với --allow-decide để duyệt gate")
            return
        if path == "/api/settings" and not self.server.allow_config:
            self._error(HTTPStatus.FORBIDDEN, "sửa cấu hình model bị khoá; chạy lại với --allow-config")
            return
        try:
            payload = self._read_json_body()
        except GateHTTPError as e:
            self._error(e.status, e.message)
            return
        if path == "/api/settings":
            self._api_settings_post(payload)
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

    def _api_state(self) -> None:
        from console.collect import collect  # nhập trễ: lớp dữ liệu do agent khác viết song song.

        try:
            state = collect(self.server.company_db, self.server.studio_db)
        except Exception:
            logger.exception("collect() thất bại")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "không đọc được trạng thái")
            return
        self._json(HTTPStatus.OK, state)

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
                self.server.studio_db,
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
        boot = (
            "<script>window.__CONSOLE__="
            + json.dumps({"token": self.server.token, "readonly": self.server.readonly}, ensure_ascii=False)
            + ";</script>"
        )
        lowered = html.lower()
        cut = lowered.find("</head>")
        html = (html[:cut] + boot + html[cut:]) if cut != -1 else boot + html
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

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
    company_db: Path | None = None,
    studio_db: Path | None = None,
    llm_yaml: dict[str, Path] | None = None,
    static_dir: Path = STATIC_DIR,
) -> ConsoleServer:
    return ConsoleServer(
        host,
        port,
        token=token or generate_token(),
        readonly=readonly,
        allow_config=allow_config,
        company_db=company_db,
        studio_db=studio_db,
        llm_yaml=llm_yaml,
        static_dir=static_dir,
    )
