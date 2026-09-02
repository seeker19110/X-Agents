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
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "llm.yaml"
TIERS = ("strong", "standard")


class LLMError(Exception): ...
class Refused(LLMError):
    """Model từ chối trả lời. Không retry mù; để supervisor escalate."""


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str = "end_turn"

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

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
    """Một lời gọi = system + user + JSON Schema đầu ra + tier. Provider nào cũng phải trả `Completion`."""
    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str) -> Completion: ...


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
    env = os.environ
    cfg.provider = env.get("COMPANY_LLM_PROVIDER", cfg.provider)
    for t in TIERS:
        if env.get(f"COMPANY_MODEL_{t.upper()}"): cfg.models[t] = env[f"COMPANY_MODEL_{t.upper()}"]
    cfg.base_url = env.get("COMPANY_LLM_BASE_URL", cfg.base_url)
    cfg.api_key = env.get("COMPANY_LLM_API_KEY", cfg.api_key)
    return cfg


def make_client(cfg: LLMConfig | None = None) -> ModelClient:
    cfg = cfg or load_config()
    if cfg.provider == "anthropic": return AnthropicClient(cfg)
    if cfg.provider == "openai": return OpenAICompatClient(cfg)
    if cfg.provider == "fake": return FakeClient()
    raise LLMError(f"provider lạ: {cfg.provider} (anthropic | openai | fake)")


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

    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str) -> Completion:
        kwargs: dict[str, Any] = dict(
            model=self.cfg.model_for(model_tier), max_tokens=self.cfg.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": self.cfg.effort.get(model_tier, "medium"),
                           "format": {"type": "json_schema", "schema": strict_schema(schema)}},
            **self.cfg.extra,
        )
        try:
            with self._client.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
        except self._anthropic.APIConnectionError as e:
            raise LLMError(f"lỗi mạng: {e}") from e
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"API {e.status_code}: {e.message}") from e
        if msg.stop_reason == "refusal":
            raise Refused(f"model từ chối: {getattr(getattr(msg, 'stop_details', None), 'category', None)}")
        text = next((b.text for b in msg.content if b.type == "text"), "")
        return Completion(text=text, input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
                          model=msg.model, stop_reason=msg.stop_reason or "end_turn")


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

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise LLMError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"lỗi mạng: {e.reason}") from e

    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str) -> Completion:
        model = self.cfg.model_for(model_tier)
        base: dict[str, Any] = {"model": model, "max_tokens": self.cfg.max_tokens, **self.cfg.extra,
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        data: dict[str, Any] | None = None
        if self._json_schema_ok is not False:
            try:
                data = self._post({**base, "response_format": {"type": "json_schema", "json_schema": {
                    "name": "payload", "strict": True, "schema": strict_schema(schema)}}})
                self._json_schema_ok = True
            except LLMError as e:
                if not str(e).startswith("HTTP 400"): raise
                self._json_schema_ok = False
        if data is None:
            fallback_user = user + "\n\n# JSON Schema bắt buộc\n```json\n" + json.dumps(schema, ensure_ascii=False) + "\n```"
            data = self._post({**base, "response_format": {"type": "json_object"},
                               "messages": [{"role": "system", "content": system}, {"role": "user", "content": fallback_user}]})
        choice = (data.get("choices") or [{}])[0]
        finish = choice.get("finish_reason") or "stop"
        if finish == "content_filter":
            raise Refused("model từ chối (content_filter)")
        usage = data.get("usage") or {}
        return Completion(text=(choice.get("message") or {}).get("content") or "",
                          input_tokens=int(usage.get("prompt_tokens", 0)), output_tokens=int(usage.get("completion_tokens", 0)),
                          model=data.get("model", model), stop_reason=finish)


# ---------- provider: giả (test / eval offline) ----------

@dataclass
class FakeClient:
    """`responses` là hàng đợi dict trả về theo thứ tự, hoặc `handler(system, user)` sinh payload."""
    responses: list[dict[str, Any]] = field(default_factory=list)
    handler: Callable[[str, str], dict[str, Any]] | None = None
    tokens_per_call: tuple[int, int] = (1_000, 300)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str) -> Completion:
        self.calls.append({"system": system, "user": user, "schema": schema, "model_tier": model_tier})
        if self.handler:
            payload = self.handler(system, user)
        elif self.responses:
            payload = self.responses.pop(0)
        else:
            raise LLMError("FakeClient hết câu trả lời")
        return Completion(text=json.dumps(payload, ensure_ascii=False), input_tokens=self.tokens_per_call[0],
                          output_tokens=self.tokens_per_call[1], model=f"fake-{model_tier}")
