"""Chống prompt injection (ADR-0012), thay cho danh sách 5 chuỗi cố định.

Hai chính sách theo nguồn của dữ liệu:
- Nguồn NỘI BỘ (event do agent phát): nghi injection → từ chối chạy (`injection_detected`), như trước. Agent nội bộ không
  có lý do gì để viết "ignore previous instructions"; thấy là có gì đó hỏng.
- Nguồn NGOÀI (khách, người dùng, web, diff của repo khách, incident/feedback): không thể từ chối vì đó chính là việc
  (support-docs phải đọc phản hồi của khách dù nó chứa lệnh). Đoạn khớp mẫu bị THAY bằng nhãn `[đã lọc: nghi prompt
  injection]`, phần còn lại đi tiếp, và audit `injection_sanitized` kèm mẫu đã khớp.

Mẫu là regex đa ngôn ngữ (Anh/Việt) nhắm vào cấu trúc lệnh điều khiển mô hình: bỏ qua/quên hướng dẫn trước, đổi vai
("you are now", "từ giờ bạn là"), giả mạo khung hội thoại (`<|im_start|>`, `[INST]`, `SYSTEM:` đầu dòng), đòi lộ
system prompt, ra lệnh cho công cụ. Không có mẫu nào bắt được hết; đây là lớp ngoài cùng — lớp trong là prompt bọc
đầu vào là DỮ LIỆU, tool có ranh giới, và người duyệt ở gate.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

LABEL = "[đã lọc: nghi prompt injection]"

PATTERNS: tuple[tuple[str, str], ...] = (
    ("ignore-instructions", r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your)\b[^.\n]{0,30}\b(instructions?|prompts?|rules?|guidelines?)\b"),
    ("new-instructions", r"\b(new|updated|real|actual)\s+(instructions?|system\s+prompt|rules?)\s*:"),
    ("role-switch", r"\b(you\s+are\s+now|from\s+now\s+on\s+you\s+are|act\s+as\s+(the\s+)?(system|admin|developer|root))\b"),
    ("system-prompt", r"\b(system\s+prompt|developer\s+message)\s*:"),
    ("reveal-prompt", r"\b(reveal|print|show|repeat|output)\b[^.\n]{0,30}\b(system\s+prompt|instructions|hidden\s+rules)\b"),
    ("chat-markup", r"(<\|im_start\|>|<\|system\|>|<\|user\|>|<\|assistant\|>|\[INST\]|<<SYS>>|</?system>)"),
    ("line-role", r"(?m)^\s*(SYSTEM|ASSISTANT|Human|Assistant)\s*:\s"),
    ("tool-command", r"\b(run|execute|call)\s+(the\s+)?(tool|command|shell)\b[^.\n]{0,30}\b(rm\s+-rf|curl|wget|delete|drop\s+table)\b"),
    ("vi-ignore", r"(bỏ\s+qua|quên|phớt\s+lờ|gạt\s+bỏ)\s+(mọi|tất\s+cả|các|những|toàn\s+bộ)?\s*(hướng\s+dẫn|chỉ\s+dẫn|chỉ\s+thị|quy\s+tắc|lệnh)\s*(trước|trên|cũ|ban\s+đầu|hệ\s+thống)"),
    ("vi-role", r"(từ\s+giờ|bây\s+giờ|kể\s+từ\s+nay)\s+(bạn|mày|ngươi)\s+(là|sẽ\s+là|đóng\s+vai)"),
    ("vi-reveal", r"(in|hiện|tiết\s+lộ|cho\s+xem|lặp\s+lại)\s+(ra\s+)?(system\s+prompt|prompt\s+hệ\s+thống|hướng\s+dẫn\s+hệ\s+thống)"),
)
_COMPILED = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in PATTERNS]

# Né mẫu bằng ký tự vô hình ("igno\u200bre") hoặc khoảng trắng lạ là cách rẻ nhất và hay gặp nhất, nên chuẩn hoá
# TRƯỚC khi so. Chỉ dùng cho việc dò: bản trả về cho agent vẫn là chuỗi gốc (đã lọc), không phải bản chuẩn hoá.
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_ODD_SPACE = re.compile(r"[\u00a0\u2000-\u200a\u3000]")


def normalize(text: str) -> str:
    return _ODD_SPACE.sub(" ", _ZERO_WIDTH.sub("", text))

# Topic mà payload đến từ ngoài công ty (khách, người dùng, hệ thống ngoài): lọc thay vì từ chối.
EXTERNAL_TOPICS = frozenset({"external-feedback", "research-requests", "clarification-answers", "acceptance-results",
                             "incidents", "change-requests"})
# Trường mang nội dung không tin cậy dù event là nội bộ (diff repo khách, kết quả tool, nội dung web).
EXTERNAL_FIELDS = frozenset({"diff", "web", "fetched", "attachments", "text", "description", "feedback"})


@dataclass
class ScanResult:
    hits: list[str] = field(default_factory=list)  # tên mẫu (kèm đoạn khớp rút gọn)

    @property
    def clean(self) -> bool: return not self.hits


def scan(text: str) -> ScanResult:
    r = ScanResult()
    norm = normalize(text)
    for name, rx in _COMPILED:
        m = rx.search(norm)
        if m: r.hits.append(f"{name}:{m.group(0)[:60]!r}")
    return r


def sanitize_text(text: str) -> tuple[str, list[str]]:
    hits: list[str] = []
    if _ZERO_WIDTH.search(text) or _ODD_SPACE.search(text):
        # Chuỗi có ký tự vô hình thì lọc trên bản đã chuẩn hoá, nếu không mẫu sẽ trượt và nhãn không bao giờ được đặt.
        text = normalize(text)
    for name, rx in _COMPILED:
        def _sub(m: re.Match[str], _n: str = name) -> str:
            hits.append(f"{_n}:{m.group(0)[:60]!r}"); return LABEL
        text = rx.sub(_sub, text)
    return text, hits


def sanitize(obj: Any) -> tuple[Any, list[str]]:
    """Lọc đệ quy mọi chuỗi trong payload; trả về (bản sạch, danh sách mẫu đã khớp)."""
    hits: list[str] = []
    def walk(x: Any) -> Any:
        if isinstance(x, str):
            y, h = sanitize_text(x); hits.extend(h); return y
        if isinstance(x, dict): return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list): return [walk(v) for v in x]
        return x
    return walk(obj), hits


def is_external(topic: str, actor: str) -> bool:
    """Event đến từ ngoài công ty? (topic của khách/người dùng, hoặc actor là người/khách/hệ thống ngoài)."""
    return topic in EXTERNAL_TOPICS or actor.split(":", 1)[0] in {"human", "customer", "user", "external", "webhook"}


def guard_payload(topic: str, actor: str, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str], bool]:
    """Áp chính sách lên payload đầu vào của một agent.
    Trả về (payload để dùng, mẫu đã khớp, refused). `refused=True` nghĩa là nguồn nội bộ chứa injection → không chạy.
    Nguồn ngoài, hoặc chỉ các trường không tin cậy (diff, text...) khớp → lọc và đi tiếp."""
    if is_external(topic, actor):
        clean, hits = sanitize(payload)
        return clean, hits, False
    # nội bộ: trường không tin cậy được lọc; trường khác khớp → từ chối
    trusted = {k: v for k, v in payload.items() if k not in EXTERNAL_FIELDS}
    r = scan(json.dumps(trusted, ensure_ascii=False))
    if not r.clean:
        return payload, r.hits, True
    untrusted = {k: v for k, v in payload.items() if k in EXTERNAL_FIELDS}
    clean, hits = sanitize(untrusted)
    return {**payload, **clean}, hits, False
