"""Quản lý cửa sổ ngữ cảnh (ADR-0012): prompt gửi model không được vượt `max_input_chars` (llm.yaml / COMPANY_MAX_INPUT_CHARS).

Trước đây prompt = system + toàn bộ payload + toàn bộ snapshot blackboard + diff 20k ký tự, không giới hạn: dự án lớn
vượt context hoặc đốt token vô ích. Giờ phân bổ theo ưu tiên, cắt có nhãn để model biết mình đang thiếu gì:

1. System prompt (prompt + skill) là cố định, trừ trước.
2. Payload đầu vào được ưu tiên: nếu vượt phần dành cho nó, chuỗi dài nhất bị cắt dần (diff, log, text...) — cắt giữa,
   giữ đầu và cuối, gắn nhãn `… (cắt N ký tự) …`.
3. Blackboard: mỗi namespace có `content`; phần còn lại của hạn mức chia đều, namespace nào ngắn hơn phần của mình thì
   nhường phần thừa cho namespace khác (water-filling). Bị cắt thì ghi rõ đường dẫn artifact để agent có tool đọc thêm.

Ước lượng token = ký tự / CHARS_PER_TOKEN (thô, đủ để không vượt trần; số token thật vẫn lấy từ `usage`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

CHARS_PER_TOKEN = 3.2  # tiếng Việt có dấu + JSON: ~3 ký tự/token với tokenizer phổ biến
MIN_KEEP = 400         # không cắt chuỗi xuống dưới mức này (mất nghĩa)


def cut_middle(s: str, limit: int, note: str = "") -> str:
    """Giữ đầu và cuối, cắt giữa có nhãn. `limit` tính cả nhãn."""
    if len(s) <= limit: return s
    tag = f"\n… (cắt {len(s) - limit} ký tự{'; ' + note if note else ''}) …\n"
    keep = max(limit - len(tag), MIN_KEEP // 2)
    head, tail = int(keep * 0.7), keep - int(keep * 0.7)
    return s[:head] + tag + (s[-tail:] if tail > 0 else "")


def _strings(obj: Any, path: tuple = ()) -> list[tuple[tuple, str]]:
    out: list[tuple[tuple, str]] = []
    if isinstance(obj, str): out.append((path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items(): out += _strings(v, (*path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj): out += _strings(v, (*path, i))
    return out


def _set(obj: Any, path: tuple, value: str) -> None:
    cur = obj
    for p in path[:-1]: cur = cur[p]
    cur[path[-1]] = value


def trim_payload(payload: dict[str, Any], limit: int) -> tuple[dict[str, Any], int]:
    """Cắt chuỗi dài nhất trước cho tới khi JSON của payload ≤ limit ký tự. Trả về (payload mới, số ký tự đã cắt)."""
    data = json.loads(json.dumps(payload, ensure_ascii=False))  # bản sao sâu
    removed = 0
    for _ in range(64):
        size = len(json.dumps(data, ensure_ascii=False, indent=2))
        if size <= limit: break
        strs = [(p, s) for p, s in _strings(data) if len(s) > MIN_KEEP]
        if not strs: break
        path, s = max(strs, key=lambda x: len(x[1]))
        target = max(MIN_KEEP, len(s) - (size - limit) - 80)
        cut = cut_middle(s, target, note=f"trường {'.'.join(map(str, path))}")
        removed += len(s) - len(cut); _set(data, path, cut)
    return data, removed


@dataclass
class ContextBudget:
    max_input_chars: int
    system_chars: int
    payload_chars: int = 0
    context_chars: int = 0
    trimmed_payload: int = 0
    trimmed_context: dict[str, int] = field(default_factory=dict)

    @property
    def est_tokens(self) -> int:
        return int((self.system_chars + self.payload_chars + self.context_chars) / CHARS_PER_TOKEN)

    def report(self) -> dict[str, Any]:
        return {"max_input_chars": self.max_input_chars, "system": self.system_chars, "payload": self.payload_chars,
                "context": self.context_chars, "trimmed_payload": self.trimmed_payload,
                "trimmed_context": self.trimmed_context, "est_tokens": self.est_tokens}

    @property
    def trimmed(self) -> bool:
        return bool(self.trimmed_payload or self.trimmed_context)


def fit(system: str, payload: dict[str, Any], context: dict[str, dict[str, Any]], max_input_chars: int,
        payload_share: float = 0.6, paths: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, dict[str, Any]], ContextBudget]:
    """Ép payload + blackboard vào hạn mức. `context` = {namespace: {version, content_ref, summary, content?}}.
    `paths` = {namespace: đường dẫn artifact} để nhãn cắt chỉ chỗ đọc thêm."""
    b = ContextBudget(max_input_chars=max_input_chars, system_chars=len(system))
    room = max(max_input_chars - len(system) - 1_500, MIN_KEEP * 4)  # 1 500 cho khung prompt (tiêu đề, yêu cầu)
    ctx_wanted = sum(len(str(v.get("content") or "")) for v in context.values()) + 200 * len(context)
    payload_limit = max(int(room * payload_share), room - ctx_wanted)  # blackboard nhỏ thì payload được rộng hơn
    payload, b.trimmed_payload = trim_payload(payload, min(payload_limit, room))
    b.payload_chars = len(json.dumps(payload, ensure_ascii=False, indent=2))
    ctx_room = room - b.payload_chars
    out: dict[str, dict[str, Any]] = {}
    fixed = sum(len(json.dumps({k: v for k, v in c.items() if k != "content"}, ensure_ascii=False)) + 40 for c in context.values())
    ctx_room -= fixed
    contents = {ns: str(c.get("content") or "") for ns, c in context.items()}
    # water-filling: namespace ngắn lấy đúng phần mình, phần thừa chia cho namespace dài
    remaining, pending = max(ctx_room, 0), dict(contents)
    alloc: dict[str, int] = {}
    while pending:
        share = remaining // len(pending)
        small = {ns: s for ns, s in pending.items() if len(s) <= share}
        if not small:
            for ns in pending: alloc[ns] = share
            break
        for ns, s in small.items():
            alloc[ns] = len(s); remaining -= len(s); pending.pop(ns)
    for ns, c in context.items():
        item = {k: v for k, v in c.items() if k != "content"}
        s = contents[ns]
        if s:
            lim = alloc.get(ns, 0)
            if lim < len(s):
                note = f"đọc đầy đủ ở {paths[ns]}" if paths and paths.get(ns) else "artifact đầy đủ trên blackboard"
                cut = cut_middle(s, max(lim, MIN_KEEP), note=note) if lim >= MIN_KEEP else f"… (bỏ {len(s)} ký tự; {note}) …"
                b.trimmed_context[ns] = len(s) - len(cut); s = cut
            item["content"] = s
        out[ns] = item
    b.context_chars = len(json.dumps(out, ensure_ascii=False, indent=2))
    return payload, out, b
