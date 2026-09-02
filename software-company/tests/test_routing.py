"""ADR-0019: điều phối nhiều gói tài khoản (RoutingClient), tier `light`, provider claude-code."""
import json
from pathlib import Path

import pytest

from company.llm import (
    TIERS,
    ClaudeCodeClient,
    Completion,
    FakeClient,
    LLMConfig,
    LLMError,
    Refused,
    TransientError,
    load_config,
    make_client,
    reported_model,
)
from company.routing import Backend, RoutingClient, is_missing_error, is_quota_error, retry_after_seconds
from company.tools import ToolSpec


class _Client:
    """Backend giả: `fail` = ngoại lệ ném ở N lần đầu; sau đó trả lời."""
    def __init__(self, name: str, fail: list[BaseException] | None = None):
        self.name, self.fail, self.calls = name, list(fail or []), []

    def complete(self, *, system, user, schema, model_tier, cache_key=None, tools=None, messages=None):
        self.calls.append(model_tier)
        if self.fail: raise self.fail.pop(0)
        return Completion(text="{}", input_tokens=10, output_tokens=1, model=f"{self.name}-{model_tier}")


def _router(*backends, clock=None, **kw):
    t = {"now": 1000.0}
    r = RoutingClient(list(backends), clock=clock or (lambda: t["now"]), **kw)
    r._t = t  # type: ignore[attr-defined]
    return r


def _call(r, tier="standard", tools=None):
    return r.complete(system="s", user="u", schema={"type": "object"}, model_tier=tier, tools=tools)


def test_quota_error_rotates_to_next_backend_and_rests_first():
    a, b = _Client("a", [TransientError("HTTP 429: quota exceeded, thử lại sau 120s")]), _Client("b")
    r = _router(Backend("a", a), Backend("b", b))
    c = _call(r)
    assert c.model == "b-standard" and a.calls == ["standard"] and b.calls == ["standard"]
    st = {s["name"]: s for s in r.status()}
    assert not st["a"]["ready"] and st["a"]["cooldown_remaining"] == 120 and st["b"]["ready"]
    notes = r.drain_retries()
    assert any("hết quota" in n and "nghỉ 120s" in n for n in notes) and any("đi backend b" in n for n in notes)
    assert r.drain_retries() == []
    # còn nghỉ → không gọi a; hết nghỉ → a lại đứng đầu
    _call(r); assert a.calls == ["standard"]
    r._t["now"] += 121
    _call(r); assert a.calls == ["standard", "standard"]


def test_transient_rest_is_short_and_content_errors_are_not_routed():
    a, b = _Client("a", [TransientError("lỗi mạng: timeout")]), _Client("b")
    r = _router(Backend("a", a), Backend("b", b), transient_cooldown_s=30, cooldown_s=3600)
    assert _call(r).model == "b-standard"
    assert r.status()[0]["cooldown_remaining"] == 30
    bad = _Client("x", [LLMError("đầu ra không phải JSON")])
    r2 = _router(Backend("x", bad), Backend("y", _Client("y")))
    with pytest.raises(LLMError, match="JSON"): _call(r2)
    ref = _Client("x", [Refused("model từ chối")])
    r3 = _router(Backend("x", ref), Backend("y", _Client("y")))
    with pytest.raises(Refused): _call(r3)


def test_prefer_per_tier_and_tools_skip_backend_without_tool_support():
    sub, free = _Client("claude-sub"), _Client("antigravity")
    r = _router(Backend("claude-sub", sub, supports_tools=False), Backend("antigravity", free),
                prefer={"light": "antigravity"})
    assert _call(r, "strong").model == "claude-sub-strong"
    assert _call(r, "light").model == "antigravity-light"
    tool = [ToolSpec(name="read_file", description="", parameters={"type": "object"})]
    assert _call(r, "strong", tools=tool).model == "antigravity-strong"
    r_only = _router(Backend("claude-sub", sub, supports_tools=False))
    with pytest.raises(LLMError, match="tool"): _call(r_only, tools=tool)


def test_all_backends_resting_raises_transient_with_soonest_wait():
    a = _Client("a", [TransientError("lỗi mạng: connection reset")]); b = _Client("b", [LLMError("HTTP 402: insufficient quota")])
    r = _router(Backend("a", a), Backend("b", b), cooldown_s=600, transient_cooldown_s=45)
    with pytest.raises(TransientError, match="thử lại sau 45s"): _call(r)   # a nghỉ 45s (mạng), b nghỉ 600s (quota)
    assert all(not s["ready"] for s in r.status()) and [s["failures"] for s in r.status()] == [1, 1]


def test_missing_binary_rests_backend_for_full_cooldown():
    a = _Client("a", [LLMError("không tìm thấy `claude` (cài Claude Code hoặc đổi provider)")]); b = _Client("b")
    r = _router(Backend("a", a), Backend("b", b), cooldown_s=900)
    assert _call(r).model == "b-standard" and r.status()[0]["cooldown_remaining"] == 900


def test_router_validation():
    with pytest.raises(LLMError, match="backend"): RoutingClient([])
    with pytest.raises(LLMError, match="trùng"): RoutingClient([Backend("a", _Client("a")), Backend("a", _Client("a"))])
    with pytest.raises(LLMError, match="prefer"): RoutingClient([Backend("a", _Client("a"))], prefer={"strong": "zzz"})


def test_quota_classifier():
    assert is_quota_error(LLMError("HTTP 429: {\"error\": \"RESOURCE_EXHAUSTED\"}"))
    assert is_quota_error(LLMError("You've hit your limit · resets 3pm"))
    assert not is_quota_error(LLMError("đầu ra không phải JSON"))
    assert retry_after_seconds("mọi tài khoản đều cooldown, thử lại sau 77s") == 77
    assert retry_after_seconds("Mọi tài khoản Antigravity đều đang cooldown hoặc hết hạn. Thử lại sau khoảng 77s.") == 77   # câu thật của gateway
    assert retry_after_seconds("Retry-After: 30") == 30 and retry_after_seconds("no hint") is None


# ---------- tier light + cấu hình backends ----------

def test_light_tier_falls_back_to_standard_then_strong():
    assert TIERS == ("strong", "standard", "light")
    cfg = LLMConfig(models={"strong": "big", "standard": "mid", "light": ""})
    assert cfg.model_for("light") == "mid" and cfg.tiers_configured() == {"strong", "standard"}
    assert LLMConfig(models={"strong": "big"}).model_for("light") == "big"
    with pytest.raises(LLMError): LLMConfig(models={}).model_for("light")


YAML = """
provider: fake
retries: 0
prices:
  fake: {input: 0.0, output: 0.0}
backends:
  - name: claude-sub
    provider: fake
    models: {strong: claude-opus-5, standard: claude-sonnet-5}
  - name: antigravity
    provider: fake
    base_url: http://127.0.0.1:8100/v1
    api_key: gateway-local
    models: {strong: claude-sonnet-4-6, standard: gemini-3.7-flash, light: gemini-3.7-flash-low}
    effort: {strong: medium}
    extra: {temperature: 0.2}
routing:
  cooldown_s: 1200
  transient_cooldown_s: 15
  prefer: {light: antigravity}
"""


def test_load_config_backends_and_make_routing_client(tmp_path: Path, monkeypatch):
    p = tmp_path / "llm.yaml"; p.write_text(YAML, encoding="utf-8")
    monkeypatch.delenv("COMPANY_LLM_BACKENDS", raising=False)
    cfg = load_config(p)
    assert [b["name"] for b in cfg.backends] == ["claude-sub", "antigravity"] and cfg.routing["cooldown_s"] == 1200
    sub, free = cfg.backend_config(cfg.backends[0]), cfg.backend_config(cfg.backends[1])
    assert sub.name == "claude-sub" and sub.models["light"] == "" and sub.model_for("light") == "claude-sonnet-5"
    assert free.base_url.endswith("8100/v1") and free.api_key == "gateway-local" and free.extra == {"temperature": 0.2}
    assert free.effort == {"strong": "medium", "standard": "medium", "light": "low"} and sub.effort["strong"] == "high"
    assert sub.retries == 0 and free.prices == cfg.prices   # khoá dùng chung thừa kế
    client = make_client(cfg)
    assert type(client).__name__ == "RoutingClient" and client.prefer == {"light": "antigravity"}
    assert client.cooldown_s == 1200 and client.transient_cooldown_s == 15
    assert [b.name for b in client.backends] == ["claude-sub", "antigravity"]
    assert client.backends[1].tiers == {"strong", "standard", "light"}
    assert client.pricing is not None and client.max_input_chars == cfg.max_input_chars
    client.backends[1].client.responses.append({"ok": True})   # FakeClient của backend antigravity
    c = client.complete(system="s", user="u", schema={"type": "object"}, model_tier="light")
    assert c.model == "fake-light" and client.backends[1].calls == 1 and client.backends[0].calls == 0


def test_env_filters_and_orders_backends(tmp_path: Path, monkeypatch):
    p = tmp_path / "llm.yaml"; p.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("COMPANY_LLM_BACKENDS", "antigravity")
    assert [b["name"] for b in load_config(p).backends] == ["antigravity"]
    monkeypatch.setenv("COMPANY_LLM_BACKENDS", "antigravity,claude-sub")
    assert [b["name"] for b in load_config(p).backends] == ["antigravity", "claude-sub"]
    monkeypatch.setenv("COMPANY_LLM_BACKENDS", "nope")
    with pytest.raises(LLMError, match="nope"): load_config(p)


def test_claude_code_backend_is_marked_without_tools(tmp_path: Path, monkeypatch):
    p = tmp_path / "llm.yaml"
    p.write_text("provider: fake\nretries: 0\nbackends:\n  - {name: cc, provider: claude-code, models: {standard: m}}\n"
                 "  - {name: f, provider: fake, supports_tools: true}\n", encoding="utf-8")
    monkeypatch.delenv("COMPANY_LLM_BACKENDS", raising=False)
    client = make_client(load_config(p))
    assert [(b.name, b.supports_tools) for b in client.backends] == [("cc", False), ("f", True)]
    assert isinstance(client.backends[1].client, FakeClient)


# ---------- provider claude-code ----------

def _cc(**kw):
    return ClaudeCodeClient(LLMConfig(provider="claude-code", models={"strong": "claude-opus-5", "standard": "claude-sonnet-5"}), **kw)


def test_claude_code_client_parses_print_json_and_counts_cache_tokens():
    seen: list[list[str]] = []

    def runner(args):
        seen.append(args)
        return "Warning: no stdin\n" + json.dumps({"result": '{"ticket_id": "T1"}', "stop_reason": "end_turn",
                                                   "usage": {"input_tokens": 100, "cache_read_input_tokens": 40,
                                                             "cache_creation_input_tokens": 10, "output_tokens": 7},
                                                   "modelUsage": {"claude-sonnet-5": {}}})

    c = _cc(runner=runner).complete(system="SYS", user="USER", schema={"type": "object"}, model_tier="standard")
    assert c.json() == {"ticket_id": "T1"} and c.input_tokens == 150 and c.cached_input_tokens == 40
    assert c.cache_write_tokens == 10 and c.output_tokens == 7 and c.model == "claude-sonnet-5"
    args = seen[0]
    assert args[1:3] == ["-p", "--output-format"] and args[args.index("--model") + 1] == "claude-sonnet-5"
    assert args[args.index("--tools") + 1] == "" and args[args.index("--system-prompt") + 1] == "SYS"
    assert args[-1].startswith("USER") and "JSON Schema" in args[-1]


def test_claude_code_client_errors_and_limits():
    ok = json.dumps({"result": "{}", "stop_reason": "end_turn"})
    with pytest.raises(LLMError):
        _cc(runner=lambda a: "not json").complete(system="s", user="u", schema={}, model_tier="strong")
    with pytest.raises(LLMError, match="boom"):
        _cc(runner=lambda a: json.dumps({"is_error": True, "result": "boom"})).complete(system="s", user="u", schema={}, model_tier="strong")
    with pytest.raises(TransientError):
        _cc(runner=lambda a: json.dumps({"is_error": True, "result": "You've hit your usage limit"})).complete(system="s", user="u", schema={}, model_tier="strong")
    with pytest.raises(Refused):
        _cc(runner=lambda a: json.dumps({"result": "", "stop_reason": "refusal"})).complete(system="s", user="u", schema={}, model_tier="strong")
    with pytest.raises(LLMError, match="tool"):
        _cc(runner=lambda a: ok).complete(system="s", user="u", schema={}, model_tier="strong",
                                          tools=[ToolSpec(name="t", description="", parameters={})])
    with pytest.raises(LLMError, match="không tìm thấy"):
        ClaudeCodeClient(LLMConfig(provider="claude-code", models={"standard": "m"}), binary="claude-binary-khong-ton-tai-xyz")\
            .complete(system="s", user="u", schema={}, model_tier="strong")
    # hội thoại nhiều lượt được trải phẳng
    seen = []
    _cc(runner=lambda a: (seen.append(a), ok)[1]).complete(
        system="s", user="u", schema={}, model_tier="strong",
        messages=[{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}, {"role": "user", "content": "C"}])
    assert "[assistant]\nB" in seen[0][-1] and seen[0][-1].startswith("[user]\nA")


def test_claude_code_reports_requested_model_not_internal_haiku():
    """`claude -p` liệt kê Haiku (helper nội bộ) trước model chính trong modelUsage; audit phải ghi model chính."""
    out = json.dumps({"result": "{}", "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
                      "modelUsage": {"claude-haiku-4-5-20251001": {"outputTokens": 40}, "claude-opus-5": {"outputTokens": 9}}})
    c = _cc(runner=lambda a: out).complete(system="s", user="u", schema={}, model_tier="strong")
    assert c.model == "claude-opus-5"
    assert reported_model({"claude-haiku-4-5-20251001": {"outputTokens": 40}, "x": {"outputTokens": 90}}, "claude-opus-5") == "x"
    assert reported_model({}, "claude-opus-5") == "claude-opus-5"


def test_escaped_vietnamese_gateway_body_counts_as_missing_pool():
    """Gateway trả 503 với thân JSON escape tiếng Việt: pool trống phải nghỉ dài (cooldown_s), không phải 60s."""
    body = r'HTTP 503: {"error": {"message": "Ch\u01b0a c\u00f3 t\u00e0i kho\u1ea3n Antigravity n\u00e0o."}}'
    assert is_missing_error(LLMError(body))
    a, b = _Client("a", [LLMError(body)]), _Client("b")
    r = _router(Backend("a", a), Backend("b", b), cooldown_s=1800, transient_cooldown_s=60)
    assert _call(r).model == "b-standard" and r.status()[0]["cooldown_remaining"] == 1800
