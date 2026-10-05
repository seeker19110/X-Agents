"""Shim K3.2: mã ở `xagents_core.sandbox`. Giữ mọi tên cũ để `tools.py`, `workspace.py`, `smoke.py`,
`orchestrator.py`, `orch/cli.py` và test không sửa một dòng import (ADR gốc 0001, nguyên tắc 4).

`sandbox_from_config` và chính sách registry của company ở lại đây, và đó không phải sót: nó là chỗ DUY NHẤT của module này biết mình đang phục vụ
công ty nào — biến `COMPANY_SANDBOX*`, nguồn `cfg.sandbox` của `LLMConfig`, mặc định `auto`. Core nhận ba giá trị
đã đọc sẵn (`sandbox_from_settings`) nên không cần một câu `if prefix == …` nào.
"""
from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from xagents_core.sandbox import (
    SECRET_ENV,
    ContainerSandbox,
    Handle,
    Result,
    RunSpec,
    Sandbox,
    SandboxError,
    SubprocessSandbox,
    clean_env,
    sandbox_from_settings,
    sanitize_env,
)

if TYPE_CHECKING:  # pragma: no cover - chỉ để mypy, tránh import vòng lúc chạy
    from .llm import LLMConfig

__all__ = ["SECRET_ENV", "ContainerSandbox", "Handle", "Result", "RunSpec", "Sandbox", "SandboxError",
           "SubprocessSandbox", "clean_env", "sandbox_from_config", "sandbox_from_settings", "sanitize_env"]


def sandbox_from_config(cfg: LLMConfig, which: Any = shutil.which) -> Sandbox:
    """`COMPANY_SANDBOX` env → `cfg.sandbox` → `auto` (ADR-0035)."""
    mode = os.environ.get("COMPANY_SANDBOX") or getattr(cfg, "sandbox", "") or "auto"
    runtime = os.environ.get("COMPANY_SANDBOX_RUNTIME") or getattr(cfg, "sandbox_runtime", "") or "docker"
    image = os.environ.get("COMPANY_SANDBOX_IMAGE") or getattr(cfg, "sandbox_image", "") or "python:3.12-slim"
    return sandbox_from_settings(mode, runtime, image, "COMPANY_SANDBOX", which)


def registry_domains(argv: Sequence[str], mode: str) -> tuple[str, ...]:
    """S2: uv tự sync phụ thuộc khách; chỉ cho PyPI khi backend enforce được ACL."""
    return ('pypi.org', 'files.pythonhosted.org') if argv[0] == 'uv' and mode.startswith('container:') else ()
