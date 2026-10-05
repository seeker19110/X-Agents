"""Lớp gọi model TEXT của `keeper`, trung lập provider (khuôn `Studio-creators/src/studio/llm.py`).

`keeper` đến sau cả hai công ty kia, nên file này chỉ còn ba thứ core KHÔNG được biết:

1. **Tiền tố biến môi trường** (`KEEPER_*`) và **provider mặc định**. Mặc định là `fake` như studio, không phải
   `anthropic` như company: toàn bộ test và `evals --replay` của `keeper` phải chạy offline (`AGENTS.md` cấm §4).
2. **Chính sách tool của `claude-code`.** Core cố ý KHÔNG có `complete()` mặc định (docstring
   `xagents_core.llm`, K3.3c3): mỗi công ty khai chiến lược tool của mình. Chiến lược của `keeper` là
   **không có tool** — không agent nào của `keeper` khai `tools`, vì mọi thao tác đọc thật (gh, pytest, git)
   là CODE xác định (`github.py`, `evidence.py`), không phải tool-use. Nên `complete()` ở đây luôn `--tools ""`,
   kèm `--restricted` để plugin/hook từ settings user/project của máy không chạy trong lượt (ADR gốc 0027).
3. **Ghép backend** khi `llm.yaml` có `backends:` (ADR-0006). Cơ chế ở `xagents_core.routing`; `keeper` không
   dựng lại `routing.py` riêng vì nó không có nhu cầu nào khác studio.

Cấu hình (ưu tiên: biến môi trường > `llm.yaml` > mặc định): `KEEPER_LLM_PROVIDER`, `KEEPER_MODEL_STRONG` /
`_STANDARD` / `_LIGHT`, `KEEPER_LLM_BASE_URL`, `KEEPER_LLM_API_KEY`, `KEEPER_LLM_BACKENDS`,
`KEEPER_MAX_INPUT_CHARS`. `llm.yaml` là bí mật, KHÔNG commit (`.gitignore`); bản mẫu là `llm.example.yaml`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from xagents_core.llm import ARGV_LIMIT as ARGV_LIMIT
from xagents_core.llm import CLI_BASE_FLAGS, cli_effort_args, system_prompt_args
from xagents_core.llm import AnthropicClient as AnthropicClient
from xagents_core.llm import ClaudeCodeClient as CoreClaudeCodeClient
from xagents_core.llm import CodexClient as CodexClient
from xagents_core.llm import Completion as Completion
from xagents_core.llm import FakeClient as FakeClient
from xagents_core.llm import LLMConfig as CoreLLMConfig
from xagents_core.llm import LLMError as LLMError
from xagents_core.llm import ModelClient as ModelClient
from xagents_core.llm import OpenAICompatClient as OpenAICompatClient
from xagents_core.llm import TransientError as TransientError
from xagents_core.llm import load_config as core_load_config
from xagents_core.tools import ToolSpec

from .core import CORE

__all__ = ["CLI_NO_TOOL_TURNS", "ClaudeCodeClient", "Completion", "LLMConfig", "LLMError", "ModelClient",
           "TransientError", "load_config", "make_client"]

# Lượt cho đường KHÔNG tool. KHÔNG phải 1: `--json-schema` ép JSON bằng một lượt nội bộ nữa của CLI, nên
# `--max-turns 1` cắt đúng lượt ép đó → `error_max_turns`, không có `result`. Company đo và vá 2026-09-05,
# studio đo lại 2026-09-09; `keeper` lấy thẳng con số đã đo hai lần thay vì lặp lại cùng sự cố lần thứ ba.
CLI_NO_TOOL_TURNS = 6


@dataclass
class LLMConfig(CoreLLMConfig):
    """Cấu hình của `keeper` = ĐÚNG khung chung, không thêm trường nào (như studio sau K3.3b)."""

    PREFIX: ClassVar[str] = CORE.prefix

    provider: str = "fake"


def load_config(path: Path | None = None) -> LLMConfig:
    """`keeper/llm.yaml` + biến `KEEPER_*`."""
    return core_load_config(CORE, path, cls=LLMConfig)


class ClaudeCodeClient(CoreClaudeCodeClient):
    """`claude -p --output-format json` như một model backend, chế độ KHÔNG tool (xem docstring module §2).

    Dùng khi máy đã đăng nhập Claude Code mà không có `ANTHROPIC_API_KEY` — chính là cách ghi bản ghi eval của
    `keeper` bằng gói subscription (`config_dir` trỏ thư mục đăng nhập của tài khoản muốn dùng)."""

    def complete(self, *, system: str, user: str, schema: dict[str, Any], model_tier: str,
                 cache_key: str | None = None, tools: list[ToolSpec] | None = None,
                 messages: list[dict[str, Any]] | None = None, workdir: str | None = None) -> Completion:
        model = self.cfg.model_for(model_tier)
        hint = ("\n\n# JSON Schema bắt buộc cho câu trả lời\n```json\n"
                + json.dumps(schema, ensure_ascii=False) + "\n```")
        base = [self.binary, "-p", "--output-format", "json", "--model", model, *CLI_BASE_FLAGS,
                "--json-schema", json.dumps(schema, ensure_ascii=False),
                *cli_effort_args(self.cfg.effort, model_tier), "--restricted", "--tools", "",
                "--max-turns", str(CLI_NO_TOOL_TURNS)]
        with system_prompt_args(system) as sp_args:
            args = [*base, *sp_args]
            if sum(len(a) + 1 for a in args) > ARGV_LIMIT:
                raise LLMError(f"claude -p: argv vượt {ARGV_LIMIT} ký tự — rút gọn schema/prompt của agent")
            out = self._run(args, user + hint)
        return self._parse(out, model)


def _single_client(cfg: LLMConfig) -> ModelClient:
    if cfg.provider == "anthropic": return AnthropicClient(cfg)
    if cfg.provider == "openai": return OpenAICompatClient(cfg)
    if cfg.provider == "codex": return CodexClient(cfg)
    if cfg.provider == "claude-code": return ClaudeCodeClient(cfg)
    if cfg.provider == "fake": return FakeClient()
    raise LLMError(f"provider lạ: {cfg.provider} (anthropic | openai | claude-code | codex | fake)")


def make_client(cfg: LLMConfig | None = None) -> ModelClient:
    """Client theo cấu hình, gắn `max_input_chars` để runner đọc mà không cần biết cấu hình.
    Có `backends:` → `RoutingClient` của core gộp nhiều gói tài khoản (ADR-0006)."""
    cfg = cfg or load_config()
    client: Any
    if not cfg.backends:
        client = _single_client(cfg)
    else:
        from xagents_core.routing import Backend, RoutingClient
        bs = []
        for data in cfg.backends:
            bc = cfg.backend_config(data)
            bs.append(Backend(name=bc.name, client=_single_client(bc), tiers=bc.tiers_configured(),
                              supports_tools=bool(data.get("supports_tools", bc.provider != "codex"))))
        r = cfg.routing
        client = RoutingClient(bs, cooldown_s=float(r.get("cooldown_s", 3600)),
                               transient_cooldown_s=float(r.get("transient_cooldown_s", 60)),
                               prefer={str(k): str(v) for k, v in (r.get("prefer") or {}).items()})
    client.max_input_chars = cfg.max_input_chars
    return client
