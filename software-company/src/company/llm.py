"""Lớp gọi model, trung lập provider. Runner chỉ biết interface `ModelClient`; provider và model cấu hình bằng
biến môi trường hoặc file `llm.yaml`, không hard-code vào code của công ty.

Cấu hình (ưu tiên: biến môi trường > llm.yaml > mặc định):
    COMPANY_LLM_PROVIDER   anthropic | openai | fake            (openai = mọi server OpenAI-compatible: OpenAI,
                                                                Ollama, Groq, vLLM, LM Studio, OpenRouter, Azure...)
    COMPANY_MODEL_STRONG   model cho tier `strong`  (vd. claude-opus-5, gpt-5, llama3.3, qwen2.5-coder)
    COMPANY_MODEL_STANDARD model cho tier `standard`
    COMPANY_LLM_BASE_URL   base URL cho provider openai (vd. http://localhost:11434/v1)
    COMPANY_LLM_API_KEY    key cho provider openai (Anthropic dùng ANTHROPIC_API_KEY / `ant auth login`)

Token trả về là số thật từ `usage` của provider, để runner ghi vào `audit-log.tokens` và supervisor cộng dồn.

ADR-0012:
- `TransientError` (mạng, 408/409/429/5xx) được `RetryingClient` thử lại với backoff mũ + jitter (`retries` trong
  llm.yaml / COMPANY_LLM_RETRIES, mặc định 3); lỗi nội dung (JSON hỏng, schema sai, từ chối) KHÔNG retry — vẫn là
  việc của delivery-lead/supervisor. Hết retry thì orchestrator hoãn event để nhịp sau thử lại, không tính lỗi agent.
- `Pricing` quy token ra USD theo bảng `prices` (USD / 1M token, khớp theo tiền tố tên model); model không có giá → 0
  và đánh dấu `unpriced` để không ai tưởng là miễn phí.
- `max_input_chars` là trần ký tự cho prompt (system + đầu vào + blackboard), runner cắt theo `context.py`.
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from .tools import ToolCall, ToolSpec

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "llm.yaml"
TIERS = ("strong", "standard")
TRANSIENT_HTTP = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})


class LLMError(Exception): ...
class Refused(LLMError):
    """Model từ chối trả lời. Không retry mù; để supervisor escalate."""
class TransientError(LLMError):
    """Lỗi vận chuyển (mạng, quá tải, rate limit): thử lại được, không phải lỗi của agent."""


@dataclass
class Completion:
    """`input_tokens` LUÔN là tổng input đã tính tiền, kể cả phần đọc từ cache và phần ghi cache — mỗi adapter
    tự quy đổi về nghĩa này vì provider đếm khác nhau (Anthropic tách cache ra khỏi `input_tokens`, OpenAI gộp vào
    `prompt_tokens`). `cached_input_tokens` và `cache_write_tokens` chỉ để báo cáo hiệu quả cache, không cộng thêm."""
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str = "end_turn"
    cached_input_tokens: int = 0  # phần input phục vụ từ cache (đã nằm trong input_tokens)
    cache_write_tokens: int = 0   # phần input ghi vào cache lần đầu (đã nằm trong input_tokens)
    tool_calls: list[ToolCall] = field(default_factory=list)  # model muốn gọi tool (rỗng = trả lời cuối)

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_ratio(self) -> float:
        return self.cached_input_tokens / self.input_tokens if self.input_tokens else 0.0

    def json(self) -> dict[str, Any]:
        text = self.text.strip()
        if text.startswith("```"):  # model nhỏ hay bọc JSON trong code fence
            text = text.strip("`").split("\n", 1)[1] if "\n" in text else text.strip("`")
            text = text.rsplit("```", 1)[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"đầu ra không phải JSON: {e}\n{self.text[:500]}") from e


class ModelClient(Protocol):
    """Một lời gọi = system + user + JSON Schema đầu ra + tier. Provider nào cũng phải trả `Completion`.

    `cache_key` (thường là agent id) giúp provider định tuyến request cùng một system prompt vào cùng một
    cache; provider không hỗ trợ thì bỏ qua.

    Tool-use (ADR-0010): `tools` là bảng tool trung lập; `messages` là hội thoại nhiều lượt theo định dạng trung lập
    (thay cho `user`): {"role": "user", "content"}, {"role": "assistant", "content", "tool_calls": [...]},
    {"role": "tool", "tool_call_id", "content"}. Model muốn gọi tool thì `Completion.tool_calls` khác rỗng."""
    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str,
                 cache_key: str | None = None, tools: list[ToolSpec] | None = None,
                 messages: list[dict[str, Any]] | None = None) -> Completion: ...


def neutral_messages(user: str, messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return list(messages) if messages else [{"role": "user", "content": user}]


# ---------- cấu hình ----------

@dataclass
class LLMConfig:
    provider: str = "anthropic"
    models: dict[str, str] = field(default_factory=lambda: {"strong": "", "standard": ""})
    base_url: str | None = None
    api_key: str | None = None
    max_tokens: int = 16_000
    effort: dict[str, str] = field(default_factory=lambda: {"strong": "high", "standard": "medium"})
    extra: dict[str, Any] = field(default_factory=dict)  # tham số provider-specific, truyền thẳng vào request
    retries: int = 3                 # số lần thử lại lỗi transport (0 = tắt)
    retry_base: float = 1.0          # giây; chờ = base × 2^i + jitter, trần 30s
    max_input_chars: int = 120_000   # trần ký tự prompt (≈ 37k token); runner cắt payload/blackboard theo context.py
    prices: dict[str, dict[str, float]] = field(default_factory=dict)  # model (tiền tố) → {input, output, cached_input, cache_write} USD/1M
    budget_usd: float | None = None  # trần chi phí mỗi dự án; supervisor pause dự án khi chạm (None = không giới hạn)

    def model_for(self, tier: str) -> str:
        m = self.models.get(tier) or self.models.get("standard") or ""
        if not m:
            raise LLMError(f"chưa cấu hình model cho tier `{tier}` (COMPANY_MODEL_{tier.upper()} hoặc llm.yaml)")
        return m


def load_config(path: Path | None = None) -> LLMConfig:
    cfg = LLMConfig()
    p = path or CONFIG_FILE
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cfg.provider = data.get("provider", cfg.provider)
        cfg.models.update({k: str(v) for k, v in (data.get("models") or {}).items()})
        cfg.effort.update(data.get("effort") or {})
        cfg.base_url = data.get("base_url", cfg.base_url)
        cfg.max_tokens = int(data.get("max_tokens", cfg.max_tokens))
        cfg.extra = dict(data.get("extra") or {})
        cfg.retries = int(data.get("retries", cfg.retries))
        cfg.retry_base = float(data.get("retry_base", cfg.retry_base))
        cfg.max_input_chars = int(data.get("max_input_chars", cfg.max_input_chars))
        cfg.prices = {str(k): {kk: float(vv) for kk, vv in (v or {}).items()} for k, v in (data.get("prices") or {}).items()}
        if data.get("budget_usd") is not None: cfg.budget_usd = float(data["budget_usd"])
    env = os.environ
    cfg.provider = env.get("COMPANY_LLM_PROVIDER", cfg.provider)
    for t in TIERS:
        if env.get(f"COMPANY_MODEL_{t.upper()}"): cfg.models[t] = env[f"COMPANY_MODEL_{t.upper()}"]
    cfg.base_url = env.get("COMPANY_LLM_BASE_URL", cfg.base_url)
    cfg.api_key = env.get("COMPANY_LLM_API_KEY", cfg.api_key)
    if env.get("COMPANY_LLM_RETRIES"): cfg.retries = int(env["COMPANY_LLM_RETRIES"])
    if env.get("COMPANY_MAX_INPUT_CHARS"): cfg.max_input_chars = int(env["COMPANY_MAX_INPUT_CHARS"])
    if env.get("COMPANY_BUDGET_USD"): cfg.budget_usd = float(env["COMPANY_BUDGET_USD"])
    return cfg


# ---------- giá tiền ----------

class Pricing:
    """USD cho một Completion theo bảng giá (USD / 1M token). Khớp tên model theo tiền tố dài nhất, không phân biệt hoa
    thường (`claude-opus-5` khớp `claude-opus-5-20260101`). Không có giá → (0.0, priced=False)."""

    def __init__(self, prices: dict[str, dict[str, float]] | None = None):
        self.prices = {k.lower(): v for k, v in (prices or {}).items()}

    def rate(self, model: str) -> dict[str, float] | None:
        m = (model or "").lower()
        best = max((k for k in self.prices if m.startswith(k)), key=len, default=None)
        return self.prices.get(best) if best else None

    def cost(self, c: Completion) -> tuple[float, bool]:
        r = self.rate(c.model)
        if not r: return 0.0, False
        inp, out = float(r.get("input", 0.0)), float(r.get("output", 0.0))
        cached_rate = float(r.get("cached_input", inp / 10))
        write_rate = float(r.get("cache_write", inp))
        fresh = max(c.input_tokens - c.cached_input_tokens - c.cache_write_tokens, 0)
        usd = (fresh * inp + c.cached_input_tokens * cached_rate + c.cache_write_tokens * write_rate + c.output_tokens * out) / 1e6
        return round(usd, 6), True


# ---------- retry lỗi transport ----------

class RetryingClient:
    """Bọc một ModelClient: thử lại `TransientError` với backoff mũ + jitter; lỗi khác đi thẳng. `drain_retries()` trả
    về (và xoá) ghi chú các lần thử lại từ lần gọi trước để runner ghi audit `llm_retry`."""

    def __init__(self, inner: ModelClient, retries: int = 3, base: float = 1.0, max_wait: float = 30.0,
                 sleep: Callable[[float], None] = time.sleep):
        self.inner, self.retries, self.base, self.max_wait, self.sleep = inner, retries, base, max_wait, sleep
        self.notes: list[str] = []

    def drain_retries(self) -> list[str]:
        n, self.notes = self.notes, []
        return n

    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str,
                 cache_key: str | None = None, tools: list[ToolSpec] | None = None,
                 messages: list[dict[str, Any]] | None = None) -> Completion:
        last: TransientError | None = None
        for i in range(self.retries + 1):
            try:
                return self.inner.complete(system=system, user=user, schema=schema, model_tier=model_tier,
                                           cache_key=cache_key, tools=tools, messages=messages)
            except TransientError as e:
                last = e
                if i >= self.retries: break
                wait = min(self.base * (2 ** i), self.max_wait) * (1 + random.random() * 0.25)
                self.notes.append(f"lần {i + 1}: {str(e)[:120]} → chờ {wait:.1f}s")
                self.sleep(wait)
        assert last is not None
        raise TransientError(f"hết {self.retries} lần thử lại: {last}") from last


def make_client(cfg: LLMConfig | None = None) -> ModelClient:
    """Client theo cấu hình, đã bọc retry (trừ fake) và gắn `pricing`, `max_input_chars`, `budget_usd` để runner/
    supervisor đọc mà không cần biết cấu hình."""
    cfg = cfg or load_config()
    client: Any
    if cfg.provider == "anthropic": client = AnthropicClient(cfg)
    elif cfg.provider == "openai": client = OpenAICompatClient(cfg)
    elif cfg.provider == "fake": client = FakeClient()
    else: raise LLMError(f"provider lạ: {cfg.provider} (anthropic | openai | fake)")
    if cfg.provider != "fake" and cfg.retries > 0:
        client = RetryingClient(client, retries=cfg.retries, base=cfg.retry_base)
    client.pricing = Pricing(cfg.prices)
    client.max_input_chars = cfg.max_input_chars
    client.budget_usd = cfg.budget_usd
    return client


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Structured output ở nhiều provider cần `additionalProperties: false` ở mọi object; bản sao, không đổi schema gốc."""
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: walk(v) for k, v in node.items() if k not in {"$schema", "$id", "format"}}
            if out.get("type") == "object":
                out["additionalProperties"] = False
                out.setdefault("properties", {})
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


# ---------- provider: Anthropic ----------

def anthropic_input_tokens(usage: Any) -> tuple[int, int, int]:
    """(tổng input tính tiền, đọc từ cache, ghi vào cache) từ `usage` của Anthropic.

    Anthropic để token cache RA NGOÀI `input_tokens`. Không cộng lại thì `audit-log.tokens` bỏ sót gần hết
    system prompt (phần lặp giữa các lượt nằm hết trong cache) và hạn mức của supervisor sẽ không bao giờ chạm."""
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return usage.input_tokens + read + write, read, write

class AnthropicClient:
    """Claude qua SDK chính thức: streaming, adaptive thinking, structured output theo JSON Schema."""

    def __init__(self, cfg: LLMConfig | None = None):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("cài SDK: uv sync --extra anthropic") from e
        self.cfg = cfg or load_config()
        self._anthropic = anthropic
        self._client = anthropic.Anthropic()

    @staticmethod
    def _messages(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Định dạng trung lập → content block của Anthropic (tool_use / tool_result)."""
        out: list[dict[str, Any]] = []
        for m in msgs:
            if m["role"] == "assistant":
                blocks: list[dict[str, Any]] = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocks += [{"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["args"]} for t in m.get("tool_calls", [])]
                out.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)  # nhiều tool_result cùng một lượt user
                else:
                    out.append({"role": "user", "content": [block]})
            else:
                out.append({"role": "user", "content": m["content"]})
        return out

    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str,
                 cache_key: str | None = None, tools: list[ToolSpec] | None = None,
                 messages: list[dict[str, Any]] | None = None) -> Completion:
        kwargs: dict[str, Any] = dict(
            model=self.cfg.model_for(model_tier), max_tokens=self.cfg.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=self._messages(neutral_messages(user, messages)),
            thinking={"type": "adaptive"},
            output_config={"effort": self.cfg.effort.get(model_tier, "medium"),
                           "format": {"type": "json_schema", "schema": strict_schema(schema)}},
            **self.cfg.extra,
        )
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        try:
            with self._client.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
        except self._anthropic.APIConnectionError as e:
            raise TransientError(f"lỗi mạng: {e}") from e
        except self._anthropic.APIStatusError as e:
            if e.status_code in TRANSIENT_HTTP:
                raise TransientError(f"API {e.status_code}: {e.message}") from e
            raise LLMError(f"API {e.status_code}: {e.message}") from e
        if msg.stop_reason == "refusal":
            raise Refused(f"model từ chối: {getattr(getattr(msg, 'stop_details', None), 'category', None)}")
        text = next((b.text for b in msg.content if b.type == "text"), "")
        calls = [ToolCall(id=b.id, name=b.name, args=dict(b.input or {})) for b in msg.content if b.type == "tool_use"]
        inp, read, write = anthropic_input_tokens(msg.usage)
        return Completion(text=text, input_tokens=inp, output_tokens=msg.usage.output_tokens,
                          model=msg.model, stop_reason=msg.stop_reason or "end_turn",
                          cached_input_tokens=read, cache_write_tokens=write, tool_calls=calls)


# ---------- provider: OpenAI-compatible (không cần SDK) ----------

class OpenAICompatClient:
    """POST {base_url}/chat/completions. Dùng `response_format: json_schema` nếu server hỗ trợ; nếu server từ chối
    (400) thì lùi về `json_object` + schema nhúng trong prompt. Chạy với OpenAI, Ollama, Groq, vLLM, LM Studio..."""

    def __init__(self, cfg: LLMConfig | None = None, timeout: float = 600.0):
        self.cfg = cfg or load_config()
        self.base_url = (self.cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = self.cfg.api_key or os.environ.get("OPENAI_API_KEY", "")
        self.timeout = timeout
        self._json_schema_ok: bool | None = None
        self._cache_key_ok: bool | None = None

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}"
            raise (TransientError if e.code in TRANSIENT_HTTP else LLMError)(msg) from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise TransientError(f"lỗi mạng: {getattr(e, 'reason', e)}") from e

    def _post_cacheable(self, body: dict[str, Any]) -> dict[str, Any]:
        """Như `_post`, nhưng nếu server từ chối vì không biết `prompt_cache_key` thì gỡ ra và thôi gửi từ lần sau.
        Tách riêng khỏi dò `json_schema` để một lỗi 400 không bị quy sai cho tính năng kia."""
        try:
            data = self._post(body)
        except LLMError as e:
            if "prompt_cache_key" not in body or not str(e).startswith("HTTP 400"):
                raise
            self._cache_key_ok = False
            data = self._post({k: v for k, v in body.items() if k != "prompt_cache_key"})
        else:
            if "prompt_cache_key" in body:
                self._cache_key_ok = True
        return data

    @staticmethod
    def _messages(system: str, msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in msgs:
            if m["role"] == "assistant":
                a: dict[str, Any] = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    a["tool_calls"] = [{"id": t["id"], "type": "function", "function": {
                        "name": t["name"], "arguments": json.dumps(t["args"], ensure_ascii=False)}} for t in m["tool_calls"]]
                out.append(a)
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                out.append({"role": "user", "content": m["content"]})
        return out

    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str,
                 cache_key: str | None = None, tools: list[ToolSpec] | None = None,
                 messages: list[dict[str, Any]] | None = None) -> Completion:
        model = self.cfg.model_for(model_tier)
        msgs = self._messages(system, neutral_messages(user, messages))
        base: dict[str, Any] = {"model": model, "max_tokens": self.cfg.max_tokens, **self.cfg.extra, "messages": msgs}
        if tools:
            base["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.parameters}} for t in tools]
        # Prompt cache: system prompt của mỗi agent là bất biến (ADR-0004) nên định tuyến theo agent id cho tỉ lệ
        # hit cao nhất. Server không hiểu tham số này thì bỏ qua; nếu từ chối (400) thì gửi lại không có nó.
        if cache_key and self._cache_key_ok is not False:
            base["prompt_cache_key"] = cache_key
        data: dict[str, Any] | None = None
        if self._json_schema_ok is not False:
            try:
                data = self._post_cacheable({**base, "response_format": {"type": "json_schema", "json_schema": {
                    "name": "payload", "strict": True, "schema": strict_schema(schema)}}})
                self._json_schema_ok = True
            except LLMError as e:
                if not str(e).startswith("HTTP 400"): raise
                self._json_schema_ok = False
        if data is None:
            hint = "\n\n# JSON Schema bắt buộc\n```json\n" + json.dumps(schema, ensure_ascii=False) + "\n```"
            fb = [*msgs]; i = max(k for k, m in enumerate(fb) if m["role"] == "user")
            fb[i] = {**fb[i], "content": fb[i]["content"] + hint}
            # json_object ép mọi lượt là JSON, kể cả lượt model muốn gọi tool → có tool thì không ép; runner chốt JSON sau
            data = self._post_cacheable({**base, "messages": fb, **({} if tools else {"response_format": {"type": "json_object"}})})
        choice = (data.get("choices") or [{}])[0]
        finish = choice.get("finish_reason") or "stop"
        if finish == "content_filter":
            raise Refused("model từ chối (content_filter)")
        calls = []
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            try: args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError: args = {"_raw": fn.get("arguments")}
            calls.append(ToolCall(id=tc.get("id") or f"call_{len(calls)}", name=fn.get("name", ""), args=args))
        usage = data.get("usage") or {}
        # OpenAI-compatible: `prompt_tokens` ĐÃ gồm phần cache, nên `cached_tokens` chỉ để báo cáo, không cộng thêm.
        cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0)
        return Completion(text=(choice.get("message") or {}).get("content") or "",
                          input_tokens=int(usage.get("prompt_tokens", 0)), output_tokens=int(usage.get("completion_tokens", 0)),
                          model=data.get("model", model), stop_reason=finish, cached_input_tokens=cached, tool_calls=calls)


# ---------- provider: giả (test / eval offline) ----------

@dataclass
class FakeClient:
    """`responses` là hàng đợi dict trả về theo thứ tự, hoặc `handler(system, user)` sinh payload."""
    responses: list[dict[str, Any]] = field(default_factory=list)
    handler: Callable[[str, str], dict[str, Any]] | None = None
    tokens_per_call: tuple[int, int] = (1_000, 300)
    calls: list[dict[str, Any]] = field(default_factory=list)
    # tool_handler(messages, tools) → danh sách ToolCall; rỗng = model trả lời cuối (qua handler/responses như thường)
    tool_handler: Callable[[list[dict[str, Any]], list[ToolSpec]], list[ToolCall]] | None = None

    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str,
                 cache_key: str | None = None, tools: list[ToolSpec] | None = None,
                 messages: list[dict[str, Any]] | None = None) -> Completion:
        msgs = neutral_messages(user, messages)
        user = next(m["content"] for m in msgs if m["role"] == "user")
        self.calls.append({"system": system, "user": user, "schema": schema, "model_tier": model_tier,
                           "cache_key": cache_key, "tools": [t.name for t in tools or []], "messages": msgs})
        if tools and self.tool_handler:
            wanted = self.tool_handler(msgs, tools)
            if wanted:
                return Completion(text="", input_tokens=self.tokens_per_call[0], output_tokens=self.tokens_per_call[1],
                                  model=f"fake-{model_tier}", stop_reason="tool_use", tool_calls=list(wanted))
        if self.handler:
            payload = self.handler(system, user)
        elif self.responses:
            payload = self.responses.pop(0)
        else:
            raise LLMError("FakeClient hết câu trả lời")
        return Completion(text=json.dumps(payload, ensure_ascii=False), input_tokens=self.tokens_per_call[0],
                          output_tokens=self.tokens_per_call[1], model=f"fake-{model_tier}")
