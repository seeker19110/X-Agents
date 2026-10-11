"""ADR-0019: điều phối nhiều gói tài khoản (RoutingClient), tier `light`, provider claude-code."""
import json
from pathlib import Path

import pytest

from company.llm import (
    TIERS,
    ClaudeCodeClient,
    CodexClient,
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

_TOOL = ToolSpec(name="t", description="", parameters={})
_CODEX_QUOTA_EXC = TransientError


class _Client:
    """Backend giả: `fail` = ngoại lệ ném ở N lần đầu; sau đó trả lời."""
    def __init__(self, name: str, fail: list[BaseException] | None = None):
        self.name, self.fail, self.calls = name, list(fail or []), []

    def complete(self, *, system, user, schema, model_tier, cache_key=None, tools=None, messages=None, workdir=None):
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


def test_bind_toolbox_chuyen_tiep_cho_backend_biet_bo_qua_backend_khong_biet():
    """ADR-0024: `bind_toolbox` phải gọi tới mọi backend có phương thức đó, và không sập với backend không có (vd. codex)."""
    class _WithBind(_Client):
        def __init__(self, name):
            super().__init__(name)
            self.bound = None

        def bind_toolbox(self, tb):
            self.bound = tb

    a, b = _WithBind("a"), _Client("b")   # b không có bind_toolbox
    r = _router(Backend("a", a), Backend("b", b))
    r.bind_toolbox("hop-tool-gia")
    assert a.bound == "hop-tool-gia"


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
    base_url: http://127.0.0.1:1123/v1
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
    assert free.base_url.endswith("1123/v1") and free.api_key == "gateway-local" and free.extra == {"temperature": 0.2}
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
    monkeypatch.setenv("COMPANY_LLM_BACKENDS", "claude-sub")   # prefer[light]=antigravity bị lọc → bỏ, không lỗi
    cfg = load_config(p); assert cfg.routing["prefer"] == {} and make_client(cfg).prefer == {}
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
    sp_contents: list[str] = []

    def runner(args, stdin):
        seen.append((args, stdin))
        sp_contents.append(Path(args[args.index("--system-prompt-file") + 1]).read_text(encoding="utf-8"))
        return "Warning: no stdin\n" + json.dumps({"result": '{"ticket_id": "T1"}', "stop_reason": "end_turn",
                                                   "usage": {"input_tokens": 100, "cache_read_input_tokens": 40,
                                                             "cache_creation_input_tokens": 10, "output_tokens": 7},
                                                   "modelUsage": {"claude-sonnet-5": {}}})

    c = _cc(runner=runner).complete(system="SYS", user="USER", schema={"type": "object"}, model_tier="standard")
    assert c.json() == {"ticket_id": "T1"} and c.input_tokens == 150 and c.cached_input_tokens == 40
    assert c.cache_write_tokens == 10 and c.output_tokens == 7 and c.model == "claude-sonnet-5"
    args, stdin = seen[0]
    assert args[1:3] == ["-p", "--output-format"] and args[args.index("--model") + 1] == "claude-sonnet-5"
    assert args[args.index("--tools") + 1] == ""
    assert args[-1] == args[args.index("--system-prompt-file") + 1], "user prompt không đi qua argv"
    assert sp_contents[0] == "SYS", "system prompt đi qua file tạm (--system-prompt-file), không qua argv"
    assert stdin.startswith("USER") and "JSON Schema" in stdin
    assert json.loads(args[args.index("--json-schema") + 1]) == {"type": "object"}, "ADR-0026: CLI ép schema"
    assert "--no-session-persistence" in args, "ADR-0026: không ghi transcript chứa repo khách ra ~/.claude"


def test_claude_code_json_schema_union_nhieu_kieu_thanh_anyof():
    """`claude -p --json-schema` kiểm bằng ajv strictTypes: `type: [X, "null"]` được, union ≥ 2 kiểu không-null bị
    từ chối "use allowUnionTypes" và CLI thoát mã 1 trước khi gọi model (đo được: security trên REL-004,
    2026-09-05, vì `review-results.scan_summary`). Chỉ union đó thành `anyOf`; nullable và phần còn lại giữ nguyên;
    schema nhúng trong prompt (stdin) vẫn là bản gốc."""
    from company.llm import cli_json_schema

    schema = {"type": "object", "properties": {
        "scan_summary": {"type": ["string", "object", "null"], "description": "tóm tắt"},
        "sbom_ref": {"type": ["string", "null"]},
        "items": {"type": "array", "items": {"type": ["integer", "string"]}}}}
    out = cli_json_schema(schema)
    assert out["properties"]["scan_summary"] == {"anyOf": [{"type": "string"}, {"type": "object"}, {"type": "null"}],
                                                 "description": "tóm tắt"}
    assert out["properties"]["sbom_ref"] == {"type": ["string", "null"]}, "nullable hai kiểu ajv chấp nhận, giữ nguyên"
    assert out["properties"]["items"]["items"] == {"anyOf": [{"type": "integer"}, {"type": "string"}]}
    assert schema["properties"]["scan_summary"]["type"] == ["string", "object", "null"], "không đổi schema gốc"

    seen: list[tuple[list[str], str]] = []

    def runner(args, stdin, **kw):
        seen.append((args, stdin))
        return json.dumps({"result": '{"ok": 1}', "stop_reason": "end_turn",
                           "usage": {"input_tokens": 1, "output_tokens": 1}, "modelUsage": {"claude-sonnet-5": {}}})

    _cc(runner=runner).complete(system="SYS", user="USER", schema=schema, model_tier="standard")
    args, stdin = seen[0]
    assert json.loads(args[args.index("--json-schema") + 1]) == out, "CLI nhận bản anyOf"
    assert '["string", "object", "null"]' in stdin, "prompt vẫn nhúng schema gốc để model đọc mô tả"


def test_claude_code_uu_tien_structured_output_va_doc_subtype_loi():
    """ADR-0026 bước 2: có `structured_output` (đã qua kiểm của CLI) thì dùng nó, kể cả khi `result` là văn xuôi;
    `subtype` lỗi (hết lượt, trần USD, không ép được schema) phải thành thông báo nói đúng việc — trước đây các JSON
    này thiếu `result` nên bị báo chung chung "thiếu trường result"."""
    so = json.dumps({"result": "Tôi đã làm xong, đây là JSON: ...", "subtype": "success",
                     "structured_output": {"ticket_id": "T9"}, "usage": {"input_tokens": 1, "output_tokens": 1}})
    c = _cc(runner=lambda a, s: so).complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")
    assert c.json() == {"ticket_id": "T9"}
    for sub, hint in (("error_max_turns", "hết lượt"), ("error_max_budget_usd", "trần chi phí"),
                      ("error_max_structured_output_retries", "JSON Schema"), ("error_during_execution", "lỗi khi đang chạy")):
        with pytest.raises(LLMError, match=f"{sub}.*{hint}"):
            _cc(runner=lambda a, s, sub=sub: json.dumps({"subtype": sub, "is_error": True})).complete(
                system="s", user="u", schema={}, model_tier="strong")
    with pytest.raises(LLMError, match="thiếu trường result"):
        _cc(runner=lambda a, s: json.dumps({"subtype": "success"})).complete(system="s", user="u", schema={}, model_tier="strong")


def test_claude_code_client_errors_and_limits():
    ok = json.dumps({"result": "{}", "stop_reason": "end_turn"})
    with pytest.raises(LLMError):
        _cc(runner=lambda a, s: "not json").complete(system="s", user="u", schema={}, model_tier="strong")
    with pytest.raises(LLMError, match="boom"):
        _cc(runner=lambda a, s: json.dumps({"is_error": True, "result": "boom"})).complete(system="s", user="u", schema={}, model_tier="strong")
    with pytest.raises(TransientError):
        _cc(runner=lambda a, s: json.dumps({"is_error": True, "result": "You've hit your usage limit"})).complete(system="s", user="u", schema={}, model_tier="strong")
    with pytest.raises(Refused):
        _cc(runner=lambda a, s: json.dumps({"result": "", "stop_reason": "refusal"})).complete(system="s", user="u", schema={}, model_tier="strong")
    with pytest.raises(LLMError, match="tool"):
        _cc(runner=lambda a, s: ok).complete(system="s", user="u", schema={}, model_tier="strong",
                                          tools=[ToolSpec(name="t", description="", parameters={})])
    with pytest.raises(LLMError, match="không tìm thấy"):
        ClaudeCodeClient(LLMConfig(provider="claude-code", models={"standard": "m"}), binary="claude-binary-khong-ton-tai-xyz")\
            .complete(system="s", user="u", schema={}, model_tier="strong")
    # hội thoại nhiều lượt được trải phẳng
    seen = []
    _cc(runner=lambda a, s: (seen.append(s), ok)[1]).complete(
        system="s", user="u", schema={}, model_tier="strong",
        messages=[{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}, {"role": "user", "content": "C"}])
    assert "[assistant]\nB" in seen[0] and seen[0].startswith("[user]\nA")


def test_claude_code_reports_requested_model_not_internal_haiku():
    """`claude -p` liệt kê Haiku (helper nội bộ) trước model chính trong modelUsage; audit phải ghi model chính."""
    out = json.dumps({"result": "{}", "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
                      "modelUsage": {"claude-haiku-4-5-20251001": {"outputTokens": 40}, "claude-opus-5": {"outputTokens": 9}}})
    c = _cc(runner=lambda a, s: out).complete(system="s", user="u", schema={}, model_tier="strong")
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


def test_claude_code_config_dir_isolates_login(tmp_path: Path, monkeypatch):
    """Mỗi backend claude-code có thể trỏ CLAUDE_CONFIG_DIR riêng → tài khoản Claude khác trên cùng máy."""
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    cfg = LLMConfig(provider="claude-code", models={"standard": "m"}, config_dir=str(tmp_path / "acc2"))
    c = ClaudeCodeClient(cfg, runner=lambda a, s: "{}")
    assert c.env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "acc2")
    assert "CLAUDE_CONFIG_DIR" not in ClaudeCodeClient(LLMConfig(provider="claude-code", models={"standard": "m"}), runner=lambda a, s: "{}").env
    p = tmp_path / "llm.yaml"
    p.write_text("provider: fake\nretries: 0\nbackends:\n  - {name: a, provider: claude-code, models: {standard: m}}\n"
                 "  - {name: b, provider: claude-code, config_dir: ~/.claude-acc2, models: {standard: m}}\n", encoding="utf-8")
    monkeypatch.delenv("COMPANY_LLM_BACKENDS", raising=False); monkeypatch.delenv("COMPANY_LLM_PROVIDER", raising=False)
    cfg = load_config(p)
    assert cfg.backend_config(cfg.backends[0]).config_dir is None
    assert cfg.backend_config(cfg.backends[1]).config_dir == "~/.claude-acc2"
    client = make_client(cfg)
    inner = client.backends[1].client
    inner = getattr(inner, "inner", inner)   # RetryingClient bọc ngoài khi retries > 0
    assert inner.env["CLAUDE_CONFIG_DIR"].endswith(".claude-acc2")


# ---------- provider codex ----------

OK_JSONL = """Reading additional input from stdin...
{"type":"thread.started","thread_id":"t1"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Model metadata for `x` not found. Defaulting to fallback metadata; this can degrade performance and cause issues."}}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"{\\"answer\\":\\"ok\\"}"}}
{"type":"turn.completed","usage":{"input_tokens":15131,"cached_input_tokens":11008,"cache_write_input_tokens":0,"output_tokens":9,"reasoning_output_tokens":0}}
"""
FAIL_JSONL = """{"type":"thread.started","thread_id":"t2"}
{"type":"turn.started"}
{"type":"error","message":"{\\"type\\":\\"error\\",\\"status\\":400,\\"error\\":{\\"message\\":\\"The 'gpt-x' model is not supported when using Codex with a ChatGPT account.\\"}}"}
{"type":"turn.failed","error":{"message":"..."}}
"""


def _cx(tmp_path, out, **kw):
    cfg = LLMConfig(provider="codex", models={"strong": "gpt-5.6-terra", "standard": "gpt-5.6-terra"}, effort={"strong": "high", "standard": "low"}, **kw)
    seen = []
    c = CodexClient(cfg, runner=lambda a, s: (seen.append((a, s)), out)[1])
    return c, seen


def test_codex_client_parses_jsonl_usage_and_builds_args(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    c, seen = _cx(tmp_path, OK_JSONL)
    r = c.complete(system="SYS", user="USER", schema={"type": "object", "properties": {"answer": {"type": "string"}}}, model_tier="standard")
    assert r.json() == {"answer": "ok"} and r.input_tokens == 15131 and r.cached_input_tokens == 11008 and r.output_tokens == 9
    assert r.model == "gpt-5.6-terra" and "CODEX_HOME" not in c.env
    a, stdin = seen[0]
    assert a[1] == "exec" and "--json" in a and "--ephemeral" in a and a[a.index("-m") + 1] == "gpt-5.6-terra"
    assert a[a.index("-s") + 1] == "read-only" and "model_reasoning_effort=low" in a
    assert "--output-schema" not in a   # strict mode của OpenAI không hợp schema topic có trường tuỳ chọn
    assert a[-1].startswith("model_reasoning_effort="), "prompt đi qua stdin, không phải argv"
    assert stdin.startswith("# Vai trò và quy tắc\nSYS") and "USER" in stdin and "JSON Schema" in stdin and '"answer"' in stdin


def test_codex_client_errors_config_dir_and_tools(tmp_path: Path):
    c, _ = _cx(tmp_path, FAIL_JSONL)
    with pytest.raises(LLMError, match="not supported"):
        c.complete(system="s", user="u", schema={}, model_tier="strong")
    c, _ = _cx(tmp_path, '{"type":"error","message":"429 usage limit reached, try again later"}\n{"type":"turn.failed","error":{"message":"x"}}\n')
    with pytest.raises(_CODEX_QUOTA_EXC):
        c.complete(system="s", user="u", schema={}, model_tier="strong")
    c, _ = _cx(tmp_path, '{"type":"turn.completed","usage":{}}\n')
    with pytest.raises(LLMError, match="agent_message"):
        c.complete(system="s", user="u", schema={}, model_tier="strong")
    c, _ = _cx(tmp_path, OK_JSONL, config_dir=str(tmp_path / "acc2"))
    assert c.env["CODEX_HOME"] == str(tmp_path / "acc2")
    with pytest.raises(LLMError, match="tool"):
        c.complete(system="s", user="u", schema={}, model_tier="strong", tools=[_TOOL])


def test_make_client_codex_backend_has_no_tools(tmp_path: Path, monkeypatch):
    p = tmp_path / "llm.yaml"
    p.write_text("provider: fake\nbackends:\n  - {name: gpt, provider: codex, models: {standard: gpt-5.6-terra}, binary: codex-khong-ton-tai}\n"
                 "  - {name: f, provider: fake}\n", encoding="utf-8")
    for v in ("COMPANY_LLM_BACKENDS", "COMPANY_LLM_PROVIDER", "STUDIO_LLM_BACKENDS", "STUDIO_LLM_PROVIDER"): monkeypatch.delenv(v, raising=False)
    client = make_client(load_config(p))
    assert [(b.name, b.supports_tools) for b in client.backends] == [("gpt", False), ("f", True)]
    inner = client.backends[0].client; inner = getattr(inner, "inner", inner)
    assert isinstance(inner, CodexClient) and inner.binary.endswith("codex-khong-ton-tai")


# ---------- provider claude-code: chế độ tool CLI (cli_tools) ----------

def _cc_tools(**kw):
    cfg = LLMConfig(provider="claude-code", models={"strong": "claude-opus-5"}, cli_tools=True,
                    cli_max_turns=12, cli_bash=["pytest:*", "ruff:*"])
    return ClaudeCodeClient(cfg, **kw)


_RW = [ToolSpec(name="read_file", description="", parameters={}),
       ToolSpec(name="write_file", description="", parameters={}),
       ToolSpec(name="search", description="", parameters={}),
       ToolSpec(name="run", description="", parameters={})]

_CC_OK = json.dumps({"result": '{"ticket_id": "T1"}', "stop_reason": "end_turn",
                     "usage": {"input_tokens": 10, "output_tokens": 2}})


def test_cli_tools_runs_claude_inside_worktree_with_narrow_permissions(tmp_path: Path):
    """cli_tools: CLI tự cầm tool trong worktree. Tool công ty phải ánh xạ sang tool CLI tương ứng, và mọi hàng rào
    thay cho tools.py (--restricted, --tools hẹp, Bash theo mẫu, deny file bí mật) phải có mặt trong argv."""
    seen: list = []
    c = _cc_tools(runner=lambda a, s, cwd=None: (seen.append((a, cwd)), _CC_OK)[1])
    out = c.complete(system="SYS", user="u", schema={"type": "object"}, model_tier="strong",
                     tools=_RW, workdir=str(tmp_path))
    assert out.json() == {"ticket_id": "T1"}
    assert out.tool_calls == [], "CLI đã tự chạy tool; không trả tool_calls ra vòng lặp của công ty"
    args, cwd = seen[0]
    assert cwd == str(tmp_path), "CLI phải chạy TRONG worktree của ticket"
    assert args[args.index("--tools") + 1] == "Read,Edit,Write,Grep,Bash"
    assert args[args.index("--max-turns") + 1] == "12"
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    assert "--restricted" in args and "--strict-mcp-config" in args
    assert args[args.index("--allowed-tools") + 1] == "Bash(pytest:*) Bash(ruff:*)"
    deny = json.loads(args[args.index("--settings") + 1])["permissions"]["deny"]
    assert "Read(**/.env)" in deny and "Write(**/*.pem)" in deny and "Edit(**/llm.yaml)" in deny


def test_claude_code_effort_xuong_cli_o_moi_che_do_va_gia_tri_sai_hong_to(tmp_path: Path):
    """ADR-0026: `effort` theo tier phải thành `--effort` của `claude -p` — trước đây adapter anthropic và codex truyền
    effort còn claude-code thì không, nên `effort: {strong: high}` với gói Claude bị bỏ qua ÂM THẦM (cùng loại lỗi #38).
    Bảng đóng: giá trị CLI không nhận (vd. `none` của codex) phải hỏng rõ, không rơi về mặc định."""
    def cfg(effort, **kw):
        return LLMConfig(provider="claude-code", models={"strong": "claude-opus-5"}, effort=effort, **kw)
    seen: list = []
    ClaudeCodeClient(cfg({"strong": "max", "light": "low"}), runner=lambda a, s: (seen.append(a), _CC_OK)[1]).complete(
        system="s", user="u", schema={}, model_tier="strong")
    assert seen[0][seen[0].index("--effort") + 1] == "max"
    ClaudeCodeClient(cfg({"strong": "xhigh"}, cli_tools=True), runner=lambda a, s, cwd=None: (seen.append(a), _CC_OK)[1]
                     ).complete(system="s", user="u", schema={}, model_tier="strong", tools=_RW, workdir=str(tmp_path))
    assert seen[1][seen[1].index("--effort") + 1] == "xhigh", "chế độ cli_tools cũng phải mang effort"
    # tier không khai effort → không thêm cờ, CLI dùng mặc định của nó (không bịa một mức nào)
    ClaudeCodeClient(cfg({"strong": "high"}), runner=lambda a, s: (seen.append(a), _CC_OK)[1]).complete(
        system="s", user="u", schema={}, model_tier="light")
    assert "--effort" not in seen[2]
    with pytest.raises(LLMError, match=r"effort `none`.*low\|medium\|high\|xhigh\|max"):
        ClaudeCodeClient(cfg({"strong": "none"}), runner=lambda a, s: _CC_OK).complete(
            system="s", user="u", schema={}, model_tier="strong")


def test_claude_code_tran_chi_phi_moi_luot_cli(tmp_path: Path):
    """ADR-0026: `--max-budget-usd` là cái hãm DUY NHẤT có tác dụng GIỮA phiên CLI — ngân sách của supervisor chỉ đo
    được sau khi CLI trả về (đánh đổi ADR-0023/0024). Khai riêng thì dùng nó; không khai thì `budget_usd` của dự án
    làm trần thảm hoạ; không có gì thì không thêm cờ."""
    seen: list = []
    def run(a, s, cwd=None): seen.append(a); return _CC_OK
    base = dict(provider="claude-code", models={"strong": "m"})
    ClaudeCodeClient(LLMConfig(**base, cli_max_budget_usd=0.5, budget_usd=100.0), runner=run).complete(
        system="s", user="u", schema={}, model_tier="strong")
    assert seen[0][seen[0].index("--max-budget-usd") + 1] == "0.5", "khai riêng thì thắng trần dự án"
    ClaudeCodeClient(LLMConfig(**base, budget_usd=12.0), runner=run).complete(
        system="s", user="u", schema={}, model_tier="strong")
    assert seen[1][seen[1].index("--max-budget-usd") + 1] == "12", "không khai riêng → trần dự án làm trần thảm hoạ"
    ClaudeCodeClient(LLMConfig(**base), runner=run).complete(system="s", user="u", schema={}, model_tier="strong")
    assert "--max-budget-usd" not in seen[2], "không cấu hình gì thì không bịa ra trần"


def test_cli_tools_off_still_refuses_tools_and_keeps_single_turn():
    """Mặc định (cli_tools=False) giữ nguyên hành vi cũ: có tool thì báo lỗi, không tool thì một lượt, không tool CLI.
    Không tool vẫn phải `--restricted` (ADR gốc 0027): không có nó, plugin/hook mà settings user/project của máy bật
    (vd. ECC — SessionStart chèn ngữ cảnh, Stop chạy cost-tracker/evaluate-session) chạy trong MỌI lượt agent của công ty."""
    with pytest.raises(LLMError, match="cli_tools"):
        _cc(runner=lambda a, s: _CC_OK).complete(system="s", user="u", schema={}, model_tier="strong", tools=_RW)
    seen: list = []
    _cc(runner=lambda a, s: (seen.append(a), _CC_OK)[1]).complete(system="s", user="u", schema={}, model_tier="strong")
    # không tool nhưng KHÔNG phải 1 lượt: `--json-schema` cần lượt ép JSON của CLI (đo: num_turns 2); 1 → error_max_turns
    assert seen[0][seen[0].index("--tools") + 1] == "" and int(seen[0][seen[0].index("--max-turns") + 1]) >= 2
    assert "--restricted" in seen[0]


def test_cli_tools_refuses_without_workdir_or_mappable_tool(tmp_path: Path):
    """Không có worktree thì CLI sẽ sửa file ở thư mục bất kỳ — thà hỏng còn hơn ghi nhầm chỗ.
    `run` mà không cấu hình cli_bash thì không có Bash: bảng tool rỗng cũng phải hỏng rõ ràng."""
    with pytest.raises(LLMError, match="workdir"):
        _cc_tools(runner=lambda a, s, cwd=None: _CC_OK).complete(
            system="s", user="u", schema={}, model_tier="strong", tools=_RW)
    cfg = LLMConfig(provider="claude-code", models={"strong": "m"}, cli_tools=True, cli_bash=[])
    with pytest.raises(LLMError, match="cli_bash"):
        ClaudeCodeClient(cfg, runner=lambda a, s, cwd=None: _CC_OK).complete(
            system="s", user="u", schema={}, model_tier="strong",
            tools=[ToolSpec(name="run", description="", parameters={})], workdir=str(tmp_path))


def test_cli_tools_readonly_toolbox_gets_no_write_or_bash(tmp_path: Path):
    """Reviewer/QA dùng toolbox chỉ đọc: CLI không được nhận Edit/Write/Bash."""
    seen: list = []
    ro = [ToolSpec(name="read_file", description="", parameters={}),
          ToolSpec(name="list_files", description="", parameters={})]
    _cc_tools(runner=lambda a, s, cwd=None: (seen.append(a), _CC_OK)[1]).complete(
        system="s", user="u", schema={}, model_tier="strong", tools=ro, workdir=str(tmp_path))
    names = seen[0][seen[0].index("--tools") + 1]
    assert names == "Read,Glob" and "--allowed-tools" not in seen[0]


def test_cli_tools_backend_is_routed_tool_work_unlike_plain_claude_code(tmp_path: Path):
    """ADR-0019: backend claude-code thường bị loại khi request có tool; bật cli_tools thì được chọn."""
    p = tmp_path / "llm.yaml"
    p.write_text("provider: fake\nretries: 0\nbackends:\n"
                 "  - {name: plain, provider: claude-code, models: {strong: m}}\n"
                 "  - {name: cli, provider: claude-code, cli_tools: true, cli_bash: ['pytest:*'], models: {strong: m}}\n",
                 encoding="utf-8")
    client = make_client(load_config(p))
    assert [(b.name, b.supports_tools) for b in client.backends] == [("plain", False), ("cli", True)]


def test_workspace_toolbox_carries_root_so_provider_knows_worktree(tmp_path: Path):
    """ToolBox phải mang gốc thư mục: runner lấy `root` làm `workdir` cho provider tự chạy tool."""
    from company.tools import WorkspaceTools
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert WorkspaceTools(tmp_path, allow_write=False, allow_run=False).toolbox().root == str(tmp_path.resolve())


# ---------- hồ sơ chạy thật: claude-code + gateway ----------

def test_claude_gateway_profile_loads_and_routes_as_documented(monkeypatch):
    """`llm.claude-gateway.yaml` phải chạy được thật, không chỉ đọc cho vui: đúng backend, đúng tier, đúng ưu tiên,
    và backend Claude bật cầu MCP nên khối kỹ thuật có tool."""
    for v in ("COMPANY_LLM_BACKENDS", "COMPANY_LLM_PROVIDER", "COMPANY_CLAUDE_MCP"):
        monkeypatch.delenv(v, raising=False)
    for t in TIERS:
        monkeypatch.delenv(f"COMPANY_MODEL_{t.upper()}", raising=False)
    client = make_client(load_config(Path(__file__).resolve().parents[1] / "llm.claude-gateway.yaml"))
    assert [b.name for b in client.backends] == ["claude-1", "antigravity"]
    assert client.prefer == {"light": "antigravity", "standard": "antigravity", "strong": "claude-1"}
    for b in client.backends:
        assert b.tiers == frozenset(TIERS), b.name
        assert b.supports_tools, f"{b.name}: khối kỹ thuật sẽ không có backend nào"
    assert [b.name for b in client.order("strong", needs_tools=True)] == ["claude-1", "antigravity"]
    assert [b.name for b in client.order("light", needs_tools=True)] == ["antigravity", "claude-1"]
    inner = client.backends[0].client.inner   # RetryingClient bọc ClaudeCodeClient
    assert inner.cfg.mcp_tools and not inner.cfg.cli_tools, "hồ sơ dùng cầu MCP (ADR-0024), không hạ hàng rào"
    assert inner.cfg.model_for("strong") == "claude-opus-5" and inner.cfg.model_for("light") == "claude-haiku-4-5"
    # mọi model trong hồ sơ đều có giá (kể cả giá 0 của gói subscription) → metrics không đếm `unpriced_calls`
    pricing = getattr(client, "pricing", None)
    assert pricing is not None
    for m in ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-sonnet-4-6",
              "gemini-3.8-flash-medium", "gemini-3.8-flash-low"):
        assert pricing.rate(m) is not None, m


# ---------- ADR-0023 bổ sung: chế độ cli mang cả tool công ty KHÔNG ánh xạ được sang tool CLI (read_artifact) ----------

_RA = ToolSpec(name="read_artifact", description="", parameters={"type": "object", "properties": {"namespace": {"type": "string"}},
                                                                 "required": ["namespace"]})


def _bridge_call(args, name, **kw):
    """Đóng vai CLI: đọc --mcp-config rồi gọi một tool qua cầu."""
    from company.mcp_bridge import SERVER_NAME, ProxyServer
    cfg = json.loads(Path(args[args.index("--mcp-config") + 1]).read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]
    a = cfg["args"]
    return ProxyServer(int(a[a.index("--port") + 1]), a[a.index("--token") + 1]).ask({"op": "call", "name": name, "args": kw})


def test_cli_tools_mang_read_artifact_qua_cau_mcp_hep(tmp_path: Path):
    """Chế độ `cli` (ADR-0023) trước đây chỉ mở tool riêng của CLI, nên `read_artifact` (ADR-0049) — tool đọc
    blackboard, không có tool CLI tương đương — biến mất và nhãn cắt `tool read_artifact("prd")` trỏ vào hư không.
    Nay tool công ty không ánh xạ được đi qua cầu MCP HẸP (chỉ chúng), tool CLI gốc vẫn như cũ."""
    from company.tools import ToolBox, ToolCall
    tb = ToolBox(); tb.root = str(tmp_path)
    tb.add(_RA, lambda namespace: f"## PRD {namespace}\nAC-1")
    seen: list = []

    def runner(args, stdin, cwd=None):
        seen.append((args, stdin))
        r = _bridge_call(args, "read_artifact", namespace="prd")
        assert r == {"ok": True, "result": "## PRD prd\nAC-1"}
        return _CC_OK

    c = _cc_tools(runner=runner); c.bind_toolbox(tb)
    out = c.complete(system="SYS", user="u", schema={"type": "object"}, model_tier="strong",
                     tools=[*_RW, _RA], workdir=str(tmp_path))
    assert out.json() == {"ticket_id": "T1"} and out.tool_mode == "cli"
    args, stdin = seen[0]
    assert args[args.index("--tools") + 1] == "Read,Edit,Write,Grep,Bash", "tool CLI gốc không đổi"
    assert "--strict-mcp-config" in args and "--mcp-config" in args
    assert args[args.index("--allowed-tools") + 1] == "Bash(pytest:*) Bash(ruff:*) mcp__company__read_artifact", \
        "cầu chỉ mang tool không ánh xạ được; tên MCP vào CÙNG cờ với mẫu Bash"
    assert "mcp__company__read_artifact" in stdin, "prompt phải nói tên tool như CLI thấy nó"
    assert [x["name"] for x in tb.calls] == ["read_artifact"], "vết gọi nằm ở ToolBox thật của runner (audit tools_trace)"
    assert isinstance(tb.call(ToolCall(id="x", name="read_artifact", args={"namespace": "prd"})), str)


def test_cli_tools_khong_co_tool_ngoai_bang_thi_khong_mo_cau(tmp_path: Path):
    """Bảng toàn tool ánh xạ được (read_file/write_file/search/run) → không mở cầu, argv y như trước."""
    from company.tools import ToolBox
    tb = ToolBox(); tb.root = str(tmp_path)
    seen: list = []
    c = _cc_tools(runner=lambda a, s, cwd=None: (seen.append(a), _CC_OK)[1]); c.bind_toolbox(tb)
    c.complete(system="SYS", user="u", schema={"type": "object"}, model_tier="strong", tools=_RW, workdir=str(tmp_path))
    assert "--mcp-config" not in seen[0] and seen[0][seen[0].index("--allowed-tools") + 1] == "Bash(pytest:*) Bash(ruff:*)"
    # `delete_file` cũng ngoài CLI_TOOL_MAP nhưng là tool worktree: KHÔNG bắc cầu (ADR-0023 §3 không mở rộng)
    c.complete(system="SYS", user="u", schema={"type": "object"}, model_tier="strong",
               tools=[*_RW, ToolSpec(name="delete_file", description="", parameters={})], workdir=str(tmp_path))
    assert "--mcp-config" not in seen[1]
    # không bind ToolBox (gọi ngoài vòng tool của runner) thì cũng không có gì để bắc cầu — không nổ, chạy như cũ
    c2 = _cc_tools(runner=lambda a, s, cwd=None: (seen.append(a), _CC_OK)[1])
    c2.complete(system="SYS", user="u", schema={"type": "object"}, model_tier="strong", tools=[*_RW, _RA], workdir=str(tmp_path))
    assert "--mcp-config" not in seen[2]


def test_cli_tools_cli_cu_khong_biet_mcp_thi_lui_ve_cli_thuan(tmp_path: Path):
    """CLI cũ không biết `--mcp-config`: bỏ cầu, chạy lại chế độ cli thuần như trước (mất read_artifact, không mất lượt)."""
    from company.tools import ToolBox
    tb = ToolBox(); tb.root = str(tmp_path); tb.add(_RA, lambda namespace: "x")
    modes: list[str] = []

    def runner(args, stdin, cwd=None):
        if "--mcp-config" in args:
            modes.append("bridge"); raise LLMError("claude -p thoát mã 1: error: unknown option '--mcp-config'")
        modes.append("cli"); return _CC_OK

    c = _cc_tools(runner=runner); c.bind_toolbox(tb)
    out = c.complete(system="SYS", user="u", schema={"type": "object"}, model_tier="strong", tools=[*_RW, _RA], workdir=str(tmp_path))
    assert modes == ["bridge", "cli"] and out.json() == {"ticket_id": "T1"}
    # mcp_tools bật + CLI cũ: MCP lùi về cli, và cầu hẹp KHÔNG thử `--mcp-config` lần nữa (đã biết CLI không có MCP)
    modes.clear()
    c = ClaudeCodeClient(LLMConfig(provider="claude-code", models={"strong": "m"}, cli_tools=True, mcp_tools=True), runner=runner)
    c.bind_toolbox(tb)
    c.complete(system="SYS", user="u", schema={"type": "object"}, model_tier="strong", tools=[*_RW, _RA], workdir=str(tmp_path))
    assert modes == ["bridge", "cli"], "MCP thử một lần (bridge) rồi cli thuần; không có lần bắc cầu hẹp thứ hai"
    # lỗi KHÁC (hết hạn mức) thì ném thẳng, không lùi
    boom = _cc_tools(runner=lambda a, s, cwd=None: (_ for _ in ()).throw(LLMError("usage limit"))); boom.bind_toolbox(tb)
    with pytest.raises(LLMError, match="usage limit"):
        boom.complete(system="SYS", user="u", schema={"type": "object"}, model_tier="strong", tools=[*_RW, _RA], workdir=str(tmp_path))
