"""Thông báo đẩy khi có gate chờ người (ADR-0005).

Console tô màu gate theo tuổi (`remind_at` 12 h, `timeout` 24 h) nhưng chỉ khi có người đang MỞ trang. Người trực
rời máy thì gate chờ hàng giờ không ai hay — đúng "chế độ hỏng im lặng" mà ADR-0004 đã gọi tên cho động cơ. Lớp này
gửi một tin ra ngoài (ntfy hoặc Telegram, qua `urllib` thư viện chuẩn) mỗi khi một gate MỚI xuất hiện trong hàng đợi
của `collect()`, kèm link mở đúng ngăn kéo gate (`#/truc-ban/gate/<id>`, ADR-0002).

Bốn ràng buộc là một phần của thiết kế:

1. **Chỉ đọc.** Nguồn duy nhất là `collect(...)["gates"]` — console vẫn không dựng event, không ghi bus.
2. **Không bao giờ ném ra ngoài.** Mạng hỏng là `failed += 1` và `last_error` trong `status()`; thread theo dõi
   không chết, server không chết.
3. **Bí mật không đi qua dòng lệnh, không vào log, không vào `status()`.** Token Telegram chỉ đọc từ env
   `CONSOLE_TELEGRAM_TOKEN`; `last_error` ghi tên kênh + mã lỗi, không ghi URL (URL Telegram mang token).
4. **Trạng thái đo được** (ADR-0003): `status()` trả số tin đã gửi / hỏng / lần gửi cuối, không trả "đã bật".
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("console.notify")

Post = Callable[[str, bytes, dict[str, str]], int]

TELEGRAM_TOKEN_ENV = "CONSOLE_TELEGRAM_TOKEN"
DEFAULT_TIMEOUT = 5.0
SUMMARY_IDS = 5      # tin tóm tắt lúc khởi động liệt kê tối đa bấy nhiêu gate
WATCH_INTERVAL = 1.0  # giây giữa hai lần dò dấu vân tay bus — rẻ (chỉ `stat()`), như `/api/stream`

# Mức của ô Thông báo ở màn Trực ban. Tập ĐÓNG, khai một chỗ: `static/js/notify.js` tra pill theo đúng tập này
# (test_static_ui đối chiếu). off = ô xám (ADR-0003), không bao giờ xanh.
VERDICT_LEVELS = ("off", "good", "warn", "crit")
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")


class NotifyConfigError(Exception):
    """Cấu hình thông báo sai hoặc thiếu — nói ra lúc khởi động, không nhận rồi im."""


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    link: str
    priority: str  # "default" | "high"

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}\n{self.link}"


def http_post(url: str, data: bytes, headers: dict[str, str], *, timeout: float = DEFAULT_TIMEOUT) -> int:
    """POST bằng `urllib`, trả mã HTTP. 4xx/5xx trả về như một SỐ (Notifier đếm nó là một lần hỏng); chỉ lỗi
    mạng thật (không nối được, timeout) mới ném `OSError` — Notifier cũng bắt nốt."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as e:
        return int(e.code)


class NtfyChannel:
    """Một topic ntfy (`https://ntfy.sh/<topic>` hoặc máy chủ tự host). Thân là văn bản UTF-8, dòng đầu là tiêu đề;
    KHÔNG dùng header `Title` vì header HTTP không mang được tiếng Việt."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.name = f"ntfy:{url}"

    def send(self, msg: Message, post: Post) -> int:
        headers = {"Content-Type": "text/plain; charset=utf-8", "Click": msg.link}
        if msg.priority == "high":
            headers["Priority"] = "high"
        return post(self.url, msg.text.encode("utf-8"), headers)


class TelegramChannel:
    """Bot Telegram gửi vào một chat. Token nằm trong URL của API nên URL không bao giờ được log hay trả ra ngoài."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.name = f"telegram:{chat_id}"

    def __repr__(self) -> str:
        return f"TelegramChannel(chat_id={self.chat_id!r})"

    def send(self, msg: Message, post: Post) -> int:
        body = {"chat_id": self.chat_id, "text": msg.text, "disable_web_page_preview": True}
        return post(self._url, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    {"Content-Type": "application/json; charset=utf-8"})


Channel = NtfyChannel | TelegramChannel


def _key(gate: Mapping[str, Any]) -> tuple[str, str]:
    return str(gate.get("xuong", "")), str(gate.get("id", ""))


class Notifier:
    def __init__(self, channels: Iterable[Channel], *, public_url: str, post: Post = http_post) -> None:
        self.channels = list(channels)
        self.public_url = public_url.rstrip("/")
        self.post = post
        self._seen: set[tuple[str, str]] | None = None  # None = chưa quan sát lần nào
        self.sent = 0
        self.failed = 0
        self.last_error: str | None = None
        self.last_sent_at: str | None = None
        self._failing: dict[str, str] = {}   # kênh -> lỗi của LẦN GỬI GẦN NHẤT qua kênh đó (hiện tại, không lịch sử)
        self.watch_error: str | None = None  # đọc hàng đợi gate hỏng (collect ném) — khác lỗi kênh

    @property
    def enabled(self) -> bool:
        return bool(self.channels)

    # --- dựng tin ---------------------------------------------------------------------------------------------

    def _gate_link(self, gid: str) -> str:
        return f"{self.public_url}/#/truc-ban/gate/{quote(gid, safe='')}"

    def _gate_message(self, g: Mapping[str, Any]) -> Message:
        hours = int(g.get("hours") or 0)
        sev = str(g.get("sev") or "calm")
        age = f"chờ {hours} giờ" + (" (quá hạn)" if sev == "over" else "")
        lines = [f"{g.get('xuong', '')} · {g.get('kind', '')} · {g.get('id', '')}"]
        title = str(g.get("title") or "")
        if title and title != f"{g.get('kind')} · {g.get('id')}":
            lines.append(title)
        effect = str(g.get("effect") or "")
        lines.append(age + (f" · duyệt → {effect}" if effect else ""))
        return Message(title=f"Gate chờ: {g.get('kind', '')} · {g.get('id', '')}", body="\n".join(lines),
                       link=self._gate_link(str(g.get("id", ""))), priority="high" if sev == "over" else "default")

    def _summary_message(self, gates: list[Mapping[str, Any]]) -> Message:
        ids = [f"{g.get('kind', '')} · {g.get('id', '')}" for g in gates[:SUMMARY_IDS]]
        more = f" … và {len(gates) - SUMMARY_IDS} gate nữa" if len(gates) > SUMMARY_IDS else ""
        return Message(title=f"{len(gates)} gate đang chờ khi console khởi động", body="; ".join(ids) + more,
                       link=f"{self.public_url}/#/truc-ban",
                       priority="high" if any(g.get("sev") == "over" for g in gates) else "default")

    # --- gửi ----------------------------------------------------------------------------------------------------

    def _deliver(self, msg: Message) -> None:
        for ch in self.channels:
            try:
                code = ch.send(msg, self.post)
            except Exception as e:  # mạng, DNS, timeout — không được ném lên thread theo dõi
                self._fail(ch.name, type(e).__name__)
                continue
            if 200 <= code < 300:
                self.sent += 1
                self.last_sent_at = datetime.now(UTC).isoformat(timespec="seconds")
                self._failing.pop(ch.name, None)
            else:
                self._fail(ch.name, f"HTTP {code}")

    def _fail(self, channel: str, why: str) -> None:
        self.failed += 1
        self.last_error = f"{channel}: {why}"
        self._failing[channel] = why
        logger.warning("thông báo qua %s hỏng: %s", channel, why)

    def observe(self, gates: list[Mapping[str, Any]]) -> list[Message]:
        """Một lần nhìn hàng đợi gate. Lần đầu: một tin tóm tắt nếu có gì chờ. Các lần sau: một tin cho mỗi gate
        MỚI (chưa có ở lần nhìn trước). Gate biến mất rồi quay lại cùng id là một lượt chờ người mới → báo lại."""
        current = {_key(g): g for g in gates}
        if not self.enabled:
            self._seen = set(current)
            return []
        if self._seen is None:
            msgs = [self._summary_message(list(current.values()))] if current else []
        else:
            msgs = [self._gate_message(g) for k, g in current.items() if k not in self._seen]
        self._seen = set(current)
        for m in msgs:
            self._deliver(m)
        return msgs

    def _loopback_link(self) -> bool:
        host = self.public_url.split("://", 1)[-1].split("/", 1)[0]
        return any(host == h or host.startswith(h + ":") for h in _LOOPBACK_HOSTS)

    def verdict(self) -> dict[str, str]:
        """Câu trả lời của ô Thông báo: *gate mới mở ra lúc tôi không nhìn thì tôi có được báo không?* Thứ tự là thứ
        tự nghiêm trọng — chỗ đầu tiên khớp thắng. Không bao giờ xanh khi chưa có bằng chứng (đã gửi được tin)."""
        if not self.enabled:
            return {"level": "off", "say": "Tắt — rời máy thì không ai báo bạn khi có gate mới. Bật bằng "
                                           "--notify-ntfy URL hoặc --notify-telegram CHAT_ID (ADR-0005)."}
        if self.watch_error:
            return {"level": "crit", "say": f"Không đọc được hàng đợi gate ({self.watch_error}) — gate mới sẽ "
                                            "không được báo cho tới khi đọc lại được."}
        if self._failing:
            hong = "; ".join(f"{k}: {v}" for k, v in sorted(self._failing.items()))
            return {"level": "crit", "say": f"Kênh đang hỏng — lần gửi gần nhất không tới: {hong}."}
        if self._loopback_link():
            return {"level": "warn", "say": f"Link trong tin trỏ {self.public_url} — điện thoại không mở được. "
                                            "Chạy lại với --public-url <địa chỉ console nhìn từ điện thoại>."}
        if not self.sent:
            return {"level": "warn", "say": "Chưa gửi tin nào — kênh chưa được chứng minh là thông. Tin đầu tiên đi "
                                            "khi có gate mới."}
        return {"level": "good", "say": f"Đã gửi {self.sent} tin, lần cuối {self.last_sent_at}."}

    def status(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "channels": [c.name for c in self.channels], "sent": self.sent,
                "failed": self.failed, "last_error": self.last_error, "last_sent_at": self.last_sent_at,
                "watching": len(self._seen or ()), "failing": sorted(self._failing), "watch_error": self.watch_error,
                "public_url": self.public_url, "verdict": self.verdict()}


class NotifyWatcher:
    """Thread nền: dò dấu vân tay bus (như `/api/stream`), bus đổi thì `collect()` rồi `notifier.observe(gates)`.
    Chạy độc lập với trình duyệt — đó là toàn bộ lý do nó tồn tại: không ai mở trang vẫn có tin."""

    def __init__(self, notifier: Notifier, dbs: tuple[Path | None, Path | None], *,
                 collect: Callable[..., dict[str, Any]] | None = None, interval: float = WATCH_INTERVAL) -> None:
        self.notifier = notifier
        self.dbs = dbs
        self.interval = interval
        if collect is None:
            from console.collect import collect as real_collect  # nhập trễ, như server.py
            collect = real_collect
        self.collect = collect
        self._fingerprint: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def step(self) -> list[Message]:
        from console.server import db_fingerprint  # nhập trễ: server nhập notify, tránh vòng ở mức module

        current = db_fingerprint(self.dbs)
        if current == self._fingerprint:
            return []
        try:
            state = self.collect(self.dbs[0], self.dbs[1])
        except Exception as e:
            # Không ghi nhận dấu vân tay: lần sau thử lại. Lỗi hiện ở ô Thông báo (đỏ) để người trực thấy.
            self.notifier.watch_error = f"{type(e).__name__}: {e}"
            logger.exception("collect() thất bại trong NotifyWatcher")
            return []
        self._fingerprint = current
        self.notifier.watch_error = None
        return self.notifier.observe(list(state.get("gates") or []))

    def _run(self) -> None:
        while not self._stop.is_set():
            self.step()
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="console-notify", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def build_notifier(*, ntfy: str | None, telegram_chat: str | None, public_url: str,
                   env: Mapping[str, str], post: Post = http_post) -> Notifier:
    """Dựng từ cờ dòng lệnh + env. Thiếu/sai thì ném `NotifyConfigError` ngay lúc khởi động."""
    channels: list[Channel] = []
    if ntfy:
        if not ntfy.startswith("https://") and not ntfy.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
            raise NotifyConfigError("--notify-ntfy phải là https:// (topic ntfy là địa chỉ công khai; http chỉ cho máy chủ "
                                    "tự host trên loopback)")
        channels.append(NtfyChannel(ntfy))
    if telegram_chat:
        token = env.get(TELEGRAM_TOKEN_ENV, "").strip()
        if not token:
            raise NotifyConfigError(f"--notify-telegram cần biến môi trường {TELEGRAM_TOKEN_ENV} (token bot; không nhận qua "
                                    "dòng lệnh vì `ps` thấy được)")
        channels.append(TelegramChannel(token, telegram_chat))
    return Notifier(channels, public_url=public_url, post=post)


__all__ = ["VERDICT_LEVELS", "Message", "Notifier", "NotifyConfigError", "NotifyWatcher", "NtfyChannel", "TelegramChannel",
           "build_notifier", "http_post"]
