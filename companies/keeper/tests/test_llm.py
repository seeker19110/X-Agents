"""Lớp gọi model của `keeper` (`src/keeper/llm.py`): cấu hình, chọn provider, adapter CLI không tool.

Không ca nào chạm mạng hay gọi `claude` thật — `ClaudeCodeClient` nhận `runner` giả (args, stdin) → stdout,
đúng seam mà `xagents_core.llm` mở sẵn cho việc này.
"""
from __future__ import annotations

import json

import pytest
from xagents_core.llm import ARGV_LIMIT, FakeClient

from keeper import llm as llm_mod
from keeper.core import CORE
from keeper.llm import ClaudeCodeClient, LLMConfig, LLMError, load_config, make_client

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}


def _cfg(**kw) -> LLMConfig:
    c = LLMConfig(**kw)
    c.models = {"strong": "m-strong", "standard": "m-standard", "light": "m-light"}
    return c


# ---------- cấu hình: tiền tố KEEPER_, provider mặc định `fake` ----------

def test_prefix_la_cua_keeper_va_provider_mac_dinh_la_fake():
    assert LLMConfig.PREFIX == CORE.prefix == "KEEPER"
    assert LLMConfig().provider == "fake"


def test_load_config_doc_yaml_roi_bien_moi_truong_de_len(tmp_path, monkeypatch):
    p = tmp_path / "llm.yaml"
    p.write_text("provider: openai\nmodels: {standard: tu-yaml}\n", encoding="utf-8")
    monkeypatch.delenv("KEEPER_LLM_PROVIDER", raising=False)
    assert load_config(p).models["standard"] == "tu-yaml"
    monkeypatch.setenv("KEEPER_MODEL_STANDARD", "tu-env")
    assert load_config(p).models["standard"] == "tu-env"


def test_load_config_khong_co_file_thi_ve_mac_dinh(tmp_path, monkeypatch):
    monkeypatch.delenv("KEEPER_LLM_PROVIDER", raising=False)
    assert load_config(tmp_path / "khong-co.yaml").provider == "fake"


# ---------- chọn provider ----------

@pytest.mark.parametrize(("provider", "attr"), [("anthropic", "AnthropicClient"), ("openai", "OpenAICompatClient"),
                                                ("codex", "CodexClient"), ("claude-code", "ClaudeCodeClient")])
def test_moi_provider_dung_dung_adapter_cua_no(provider, attr, monkeypatch):
    """Dựng adapter thật ở đây là ép cài SDK / có CLI trên máy CI; điều ca này đo là phép ĐỊNH TUYẾN
    provider → lớp, nên mỗi lớp được thay bằng một sentinel nhận `cfg`."""
    class _Sentinel:
        def __init__(self, cfg): self.cfg = cfg
    monkeypatch.setattr(llm_mod, attr, _Sentinel)
    assert isinstance(make_client(_cfg(provider=provider)), _Sentinel)


def test_provider_fake_khong_can_cau_hinh_gi():
    assert isinstance(make_client(_cfg(provider="fake")), FakeClient)


def test_provider_la_thi_no_to_chu_khong_roi_ve_mac_dinh():
    with pytest.raises(LLMError, match="provider lạ"):
        make_client(_cfg(provider="khong-co-that"))


def test_make_client_khong_tham_so_thi_doc_load_config(monkeypatch):
    monkeypatch.setattr(llm_mod, "load_config", lambda: _cfg(provider="fake"))
    assert make_client().max_input_chars == LLMConfig().max_input_chars


def test_co_backends_thi_gop_thanh_routing_client():
    cfg = _cfg(provider="fake")
    cfg.backends = [{"name": "a", "provider": "fake", "models": {"standard": "m1"}},
                    {"name": "b", "provider": "codex", "models": {"standard": "m2"}}]
    cfg.routing = {"cooldown_s": 10, "transient_cooldown_s": 5, "prefer": {"standard": "a"}}
    client = make_client(cfg)
    assert [b.name for b in client.backends] == ["a", "b"]
    # `supports_tools` suy từ provider khi không khai: codex không có tool-use.
    assert [b.supports_tools for b in client.backends] == [True, False]
    assert client.prefer == {"standard": "a"} and client.cooldown_s == 10.0


# ---------- adapter claude-code: chế độ KHÔNG tool ----------

def _cli_out(text: str) -> str:
    return json.dumps({"subtype": "success", "result": text, "usage": {"input_tokens": 7, "output_tokens": 3}})


def test_claude_code_luon_chay_khong_tool_va_gui_schema_hai_duong():
    seen: dict[str, object] = {}

    def runner(args, stdin, cwd=None):
        seen["args"], seen["stdin"] = args, stdin
        return _cli_out('{"a": "xong"}')

    c = ClaudeCodeClient(_cfg(provider="claude-code"), runner=runner)
    out = c.complete(system="SYS", user="USER", schema=SCHEMA, model_tier="light")
    args = seen["args"]
    assert args[args.index("--tools") + 1] == ""          # không tool: hợp đồng của keeper
    assert args[args.index("--max-turns") + 1] == "6"     # KHÔNG phải 1 — xem CLI_NO_TOOL_TURNS
    assert "--restricted" in args   # ADR gốc 0027: plugin/hook từ settings user/project không chen vào lượt
    assert args[args.index("--model") + 1] == "m-light"
    assert "--json-schema" in args                        # đường 1: CLI ép và kiểm
    assert "JSON Schema bắt buộc" in seen["stdin"]        # đường 2: model thấy mô tả trường
    assert seen["stdin"].startswith("USER")               # user message qua STDIN, không qua argv
    assert out.json() == {"a": "xong"} and out.input_tokens == 7


def test_claude_code_argv_qua_dai_thi_bao_ngay_thay_vi_de_os_no():
    """Kích thước dựng TỪ `ARGV_LIMIT`, không phải một số cứng.

    Bản đầu dùng `"y" * 40_000`: vượt trần Windows (30 000) nhưng DƯỚI trần Linux (120 000), nên test đỏ trên
    ubuntu và xanh trên Windows — đúng "cổng đúng-sai theo máy chạy" mà `TRAPS.md` §2 cấm, và CI bắt được ở
    `keeper-unit (ubuntu-latest)`. `ARGV_LIMIT` là `30_000 if os.name == "nt" else 120_000`
    (`xagents_core/llm.py:392`), nên phép thử phải bám vào chính hằng số đó."""
    schema = {"type": "object", "x": "y" * (ARGV_LIMIT + 10_000)}
    c = ClaudeCodeClient(_cfg(provider="claude-code"), runner=lambda *a, **k: _cli_out("{}"))
    with pytest.raises(LLMError, match="argv vượt"):
        c.complete(system="SYS", user="USER", schema=schema, model_tier="light")


def test_fake_client_van_la_client_hop_le_cho_runner():
    out = FakeClient(responses=[{"a": "1"}]).complete(system="s", user="u", schema=SCHEMA, model_tier="light")
    assert out.json() == {"a": "1"}
