"""Đọc/ghi phần model của `llm.yaml` từng công ty — lớp lõi dùng chung cho CLI và `/api/settings`.

Nguyên tắc:
- **Mặc định là hiện trạng.** Console không có bảng giá trị mặc định riêng: cái đang nằm trong `llm.yaml`
  chính là mặc định hiển thị, người dùng sửa từ đó.
- **Tắt backend phải tắt thật.** `company.llm.load_config` bỏ qua mọi khoá lạ, nên `enabled: false` sẽ vô
  tác dụng (backend vẫn chạy). Tắt = chuyển hẳn phần tử sang khoá `disabled_backends:` mà loader không đọc;
  bật lại = chuyển ngược. Không xoá dữ liệu của ai.
- **Ghi nguyên tử + backup.** `yaml.safe_dump` làm mất chú thích trong file, nên mỗi lần ghi để lại
  `llm.yaml.bak` của bản ngay trước đó.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

import yaml

TIERS = ("strong", "standard", "light")
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LLM_YAML = {
    "software-company": REPO_ROOT / "software-company" / "llm.yaml",
    "Studio-creators": REPO_ROOT / "Studio-creators" / "llm.yaml",
}
DEFAULT_GATEWAY_URL = "http://127.0.0.1:8100"


class SettingsError(ValueError):
    """Sai tham số người dùng — server đổi thành HTTP 400, CLI in ra rồi thoát 1."""


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SettingsError(f"không có {path} — tạo llm.yaml cho công ty đó trước")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SettingsError(f"{path} không phải ánh xạ YAML")
    return data


def _backends(data: dict[str, Any], key: str = "backends") -> list[dict[str, Any]]:
    return [b for b in (data.get(key) or []) if isinstance(b, dict)]


def _name(b: dict[str, Any]) -> str:
    return str(b.get("name") or b.get("provider") or "?")


def gateway_catalog(gateway_url: str = DEFAULT_GATEWAY_URL, timeout: float = 1.5) -> list[str]:
    """Model gateway đang phục vụ, để trang gợi ý đúng tên. Gateway tắt → rỗng, không phải lỗi:
    backend claude-code/codex không đi qua gateway nên vẫn cấu hình được bình thường."""
    try:
        with urllib.request.urlopen(f"{gateway_url.rstrip('/')}/v1/models", timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    return [str(m.get("id")) for m in (payload.get("data") or []) if isinstance(m, dict) and m.get("id")]


def _backend_view(b: dict[str, Any], *, enabled: bool, catalog: list[str]) -> dict[str, Any]:
    raw = b.get("models")
    models: dict[str, Any] = raw if isinstance(raw, dict) else {}
    provider = str(b.get("provider") or "")
    via_gateway = provider == "openai" and bool(b.get("base_url"))
    return {
        "name": _name(b),
        "provider": provider,
        "enabled": enabled,
        "via_gateway": via_gateway,
        "base_url": str(b.get("base_url") or ""),
        "models": {t: str(models.get(t) or "") for t in TIERS},
        # Chỉ soi backend đi qua gateway: model của claude-code/codex do CLI đó định nghĩa, gateway không biết.
        "unknown": sorted(
            {
                str(models.get(t))
                for t in TIERS
                if via_gateway and catalog and models.get(t) and str(models.get(t)) not in catalog
            }
        ),
    }


def read_settings(paths: dict[str, Path] | None = None, gateway_url: str = DEFAULT_GATEWAY_URL) -> dict[str, Any]:
    """Ảnh chụp cấu hình model của mọi công ty. Công ty thiếu file → `ok: false` kèm lý do, không ném lỗi."""
    catalog = gateway_catalog(gateway_url)
    out: dict[str, Any] = {"catalog": catalog, "tiers": list(TIERS), "companies": {}}
    for company, path in (paths or DEFAULT_LLM_YAML).items():
        entry: dict[str, Any] = {"path": str(path), "ok": False, "error": None, "backends": [], "prefer": {}}
        try:
            data = _load(path)
        except SettingsError as e:
            entry["error"] = str(e)
            out["companies"][company] = entry
            continue
        entry["backends"] = [_backend_view(b, enabled=True, catalog=catalog) for b in _backends(data)]
        entry["backends"] += [
            _backend_view(b, enabled=False, catalog=catalog) for b in _backends(data, "disabled_backends")
        ]
        prefer = (data.get("routing") or {}).get("prefer") or {}
        entry["prefer"] = {str(t): str(n) for t, n in prefer.items() if t in TIERS}
        entry["ok"] = True
        out["companies"][company] = entry
    return out


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def update_settings(
    path: Path,
    *,
    models: dict[str, dict[str, str]] | None = None,
    prefer: dict[str, str] | None = None,
    enable: list[str] | None = None,
    disable: list[str] | None = None,
) -> dict[str, Any]:
    """Sửa `llm.yaml` của MỘT công ty. Validate hết rồi mới ghi: hoặc đổi trọn, hoặc không đổi gì."""
    data = _load(path)
    active, disabled = _backends(data), _backends(data, "disabled_backends")
    by_name = {_name(b): b for b in [*active, *disabled]}

    for name in [*(disable or []), *(enable or []), *(models or {})]:
        if name not in by_name:
            raise SettingsError(f"không có backend `{name}` trong {path.name}")
    for backend_name, tiers in (models or {}).items():
        for tier, model in tiers.items():
            if tier not in TIERS:
                raise SettingsError(f"tier `{tier}` không hợp lệ (chỉ {', '.join(TIERS)})")
            if not str(model).strip():
                raise SettingsError(f"model cho `{backend_name}.{tier}` không được để trống")

    changes: list[str] = []
    # Bật/tắt trước, để validate `prefer` trên trạng thái SAU khi đổi.
    for name in disable or []:
        b = by_name[name]
        if b in active:
            active.remove(b)
            disabled.append(b)
            changes.append(f"tắt backend {name}")
    for name in enable or []:
        b = by_name[name]
        if b in disabled:
            disabled.remove(b)
            active.append(b)
            changes.append(f"bật backend {name}")

    active_names = {_name(b) for b in active}
    for backend_name, tiers in (models or {}).items():
        b = by_name[backend_name]
        raw = b.get("models")
        current: dict[str, Any] = raw if isinstance(raw, dict) else {}
        b["models"] = {**current, **{t: str(m) for t, m in tiers.items()}}
        changes += [f"{backend_name}.{t} → {m}" for t, m in tiers.items()]

    routing = dict(data.get("routing") or {})
    prefer_map = {str(t): str(n) for t, n in (routing.get("prefer") or {}).items()}
    for tier, backend_name in (prefer or {}).items():
        if tier not in TIERS:
            raise SettingsError(f"tier `{tier}` không hợp lệ (chỉ {', '.join(TIERS)})")
        if backend_name not in active_names:
            raise SettingsError(f"`{backend_name}` không phải backend đang bật — không đặt ưu tiên cho nó được")
        prefer_map[tier] = backend_name
        changes.append(f"ưu tiên {tier} → {backend_name}")

    # prefer trỏ vào backend vừa tắt sẽ làm router chọn hụt: bỏ mục đó và nói rõ trong `changes`.
    for tier in [t for t, n in prefer_map.items() if n not in active_names]:
        del prefer_map[tier]
        changes.append(f"bỏ ưu tiên {tier} (backend đã tắt)")

    if not changes:
        return {"ok": True, "changes": [], "path": str(path), "backup": None}

    data["backends"] = active
    if disabled:
        data["disabled_backends"] = disabled
    else:
        data.pop("disabled_backends", None)
    if prefer_map:
        routing["prefer"] = prefer_map
    else:
        routing.pop("prefer", None)
    if routing:
        data["routing"] = routing
    _atomic_write(path, data)
    return {"ok": True, "changes": changes, "path": str(path), "backup": str(path) + ".bak"}
