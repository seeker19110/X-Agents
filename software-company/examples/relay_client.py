"""RelayClient: `ModelClient` không gọi API — mỗi lời gọi model được ghi ra file để một "người điều phối" bên ngoài
(vd. Claude Code giao cho subagent theo tier) trả lời, rồi kết quả đi ngược vào orchestrator.

Giao thức (thư mục `dir`):
    <n>.req.json  do client ghi: {id, agent, model_tier, system, user, messages, schema, tools, workspace, can_write}
    <n>.res.json  do người điều phối ghi: {payload: <object đúng schema>, model?, input_tokens?, output_tokens?}
Client chờ (poll) tới khi có .res.json rồi trả `Completion`. Tool-use: thay vì vòng lặp tool của runner, bên trả lời
được chỉ đường dẫn worktree (`workspace`) để sửa/đọc trực tiếp; runner vẫn tự kiểm `dirty()`, chạy lint/test, commit
và lấy diff — bằng chứng PR không đổi (ADR-0010). Không có tool → `workspace` = null.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from company.llm import Completion, LLMError, Pricing, ToolSpec, neutral_messages


def _input_json(user: str) -> dict[str, Any]:
    try:
        return json.loads(user.split("```json\n", 1)[1].split("\n```", 1)[0])
    except (IndexError, json.JSONDecodeError):
        return {}


# Giá USD/1M token để runner tính cost_usd theo tên model mà người điều phối khai trong .res.json (ví dụ định dạng;
# chỉnh theo bảng giá hiện hành). Token của subagent do người điều phối báo, thiếu thì ước lượng theo ký tự/4.
DEFAULT_PRICES = {"claude-opus-5": {"input": 15.0, "output": 75.0, "cached_input": 1.5},
                  "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cached_input": 0.3},
                  "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cached_input": 0.1}}


class RelayClient:
    budget_usd: float | None = None
    max_input_chars: int | None = None

    def __init__(self, dir: Path, repo: Path | None = None, timeout: float = 3600.0, poll: float = 1.0,
                 prices: dict[str, dict[str, float]] | None = None, clear: bool = True):
        self.dir, self.repo, self.timeout, self.poll = Path(dir), repo, timeout, poll
        self.dir.mkdir(parents=True, exist_ok=True)
        if clear:
            for f in self.dir.glob("*.json"): f.unlink()
        ids = [int(f.name.split(".")[0]) for f in self.dir.glob("*.req.json") if f.name.split(".")[0].isdigit()]
        self.n = max(ids, default=0); self.pricing = Pricing(prices if prices is not None else DEFAULT_PRICES)
        self.calls: list[dict[str, Any]] = []

    def _workspace(self, user: str, tools: list[ToolSpec]) -> tuple[str | None, bool]:
        names = {t.name for t in tools}
        if self.repo is None or not tools: return None, False
        p = _input_json(user)
        tid = p.get("ticket_id"); rid = p.get("release_id")
        if tid and (self.repo / ".worktrees" / str(tid)).exists():
            return str(self.repo / ".worktrees" / str(tid)), "write_file" in names
        if rid and (self.repo / ".worktrees" / "_integration").exists():
            return str(self.repo / ".worktrees" / "_integration"), False
        if "run" not in names:  # researcher: repo khách chỉ đọc
            return str(self.repo), False
        return None, False

    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str,
                 cache_key: str | None = None, tools: list[ToolSpec] | None = None,
                 messages: list[dict[str, Any]] | None = None) -> Completion:
        msgs = neutral_messages(user, messages)
        user = next(m["content"] for m in msgs if m["role"] == "user")
        self.n += 1; rid = f"{self.n:03d}"
        ws, can_write = self._workspace(user, tools or [])
        req = {"id": rid, "agent": cache_key, "model_tier": model_tier, "system": system, "user": user, "messages": msgs,
               "schema": schema, "tools": [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools or []],
               "workspace": ws, "can_write": can_write}
        (self.dir / f"{rid}.req.json").write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
        self.calls.append({"id": rid, "agent": cache_key, "model_tier": model_tier, "tools": [t.name for t in tools or []]})
        res_path = self.dir / f"{rid}.res.json"
        t0 = time.time()
        while not res_path.exists():
            if time.time() - t0 > self.timeout: raise LLMError(f"relay {rid}: không có phản hồi sau {self.timeout}s")
            time.sleep(self.poll)
        for _ in range(10):  # file có thể đang được ghi dở
            try:
                res = json.loads(res_path.read_text(encoding="utf-8")); break
            except json.JSONDecodeError:
                time.sleep(0.2)
        else:
            raise LLMError(f"relay {rid}: .res.json không phải JSON")
        payload = res.get("payload")
        if not isinstance(payload, dict): raise LLMError(f"relay {rid}: thiếu payload")
        text = json.dumps(payload, ensure_ascii=False)
        return Completion(text=text, input_tokens=int(res.get("input_tokens") or (len(system) + len(user)) // 4),
                          output_tokens=int(res.get("output_tokens") or len(text) // 4),
                          model=str(res.get("model") or f"relay-{model_tier}"))
