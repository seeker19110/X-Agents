"""Cổng cứng cho bộ file container hoá hub (ADR gốc 0013): `Dockerfile`, `docker-compose.yml`, `.dockerignore`.

Vì sao cần — bốn chỗ hở đo được trong audit 2026-09-13 (`docs/reports/2026-09-13-audit.md` mục "deploy"),
tất cả đều **im lặng**: không cổng nào đỏ, `docker compose up -d` vẫn chạy, chỉ có bí mật nằm sai chỗ và
gateway không với tới được.

1. `.dockerignore` không loại `llm.yaml`/`.env` mà `Dockerfile` lại `COPY . .` ⇒ máy nào đã cấu hình xong rồi
   build là **bake khoá vào layer image** — trái ADR-0013 quyết định 4+7 và `AGENTS.md` luật cấm 3. Đây là
   lớp lỗi mà gitleaks KHÔNG bắt: file vẫn không vào git, nó vào image.
2. Thiếu volume `llm.yaml` ⇒ container hoặc chạy bằng bí mật đã bake (mục 1), hoặc không có cấu hình model.
3. `base_url` của gateway là `127.0.0.1:1123` — trong container đó là chính container, không phải daemon trên
   host. Phải có đường tới host (`extra_hosts: host.docker.internal` hoặc `network_mode: host`).
4. Bus chạy `PRAGMA journal_mode=WAL` (`xagents_core/sqlite_bus.py`), WAL sinh hai file anh em `-wal`/`-shm`
   cạnh file DB. Bind-mount một FILE `.sqlite` để hai file đó rơi vào layer container: mất khi `down`, và lệch
   trạng thái nếu host cũng mở cùng DB. Mount THƯ MỤC chứa nó.

Đặt ở `platform/console/tests/` theo đúng lối `test_cong_repo.py` — console là nơi repo để các phép canh cấp
gốc (job `console-unit`, chạy trên cả ba nền).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
DOCKERIGNORE = ROOT / ".dockerignore"
COMPOSE = ROOT / "docker-compose.yml"
DOCKERFILE = ROOT / "Dockerfile"

#: File bí mật của `AGENTS.md` luật cấm 3. Cùng danh sách ấy phải bị loại khỏi ngữ cảnh build, vì `COPY . .`
#: không biết `.gitignore` — hai cơ chế khác nhau, cùng một danh sách.
#: `llm.yaml.*`: bản `.bak`/`.tmp` console ghi cạnh `llm.yaml` (`console/settings.py:_atomic_write`) mang cùng khoá.
BI_MAT = ("llm.yaml", "llm.yaml.*", "media.yaml", ".env")


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _hub() -> dict[str, Any]:
    hub = _compose()["services"]["hub"]
    assert isinstance(hub, dict)
    return hub


def _volumes() -> list[str]:
    return [v for v in _hub().get("volumes", []) if isinstance(v, str)]


def _nguon(v: str) -> str:
    """Vế trái của một dòng `volumes:` dạng ngắn (`nguon:dich[:ro]`), giữ nguyên `${BIEN:-mặc định}`."""
    than = v.split(":${", 1)[0] if v.startswith("$") else v
    return than.rsplit(":", 2)[0] if v.startswith("$") else v.split(":")[0]


@pytest.mark.parametrize("ten", BI_MAT)
def test_dockerignore_loai_moi_file_bi_mat(ten: str) -> None:
    """`COPY . .` + `.dockerignore` thiếu một dòng = bí mật nằm trong image. gitleaks không thấy lớp này."""
    assert "COPY . ." in DOCKERFILE.read_text(encoding="utf-8"), (
        "Dockerfile không còn `COPY . .` — đọc lại test này: nó canh đúng cặp `COPY . .` + `.dockerignore`.")
    dong = {d.strip() for d in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()}
    assert f"**/{ten}" in dong or ten in dong, (
        f".dockerignore không loại `{ten}`, mà Dockerfile `COPY . .` — máy đã cấu hình xong rồi `--build` là "
        f"bake bí mật vào layer image (ADR-0013 quyết định 4+7, AGENTS.md luật cấm 3).")


def test_compose_mount_llm_yaml_thay_vi_bake() -> None:
    """Cấu hình model phải vào container qua volume; đó là mặt kia của cổng `.dockerignore` ở trên."""
    assert any("llm.yaml" in v for v in _volumes()), (
        "docker-compose.yml không mount `llm.yaml` nào. Không mount mà cũng không bake thì container không có "
        "cấu hình model; bake thì vi phạm luật cấm 3 — phải là mount.")


def test_compose_mount_thu_muc_chua_sqlite_khong_mount_file_le() -> None:
    """WAL sinh `-wal`/`-shm` CẠNH file DB. Mount file lẻ ⇒ hai file ấy nằm trong layer container."""
    le = [v for v in _volumes() if _nguon(v).endswith(".sqlite")]
    assert not le, (
        f"mount file `.sqlite` lẻ: {le}. Bus chạy `journal_mode=WAL` (xagents_core/sqlite_bus.py), hai file "
        f"anh em `-wal`/`-shm` sẽ rơi vào layer container — mất khi `down`, lệch nếu host cũng mở cùng DB. "
        f"Mount THƯ MỤC chứa file DB.")


def test_compose_co_duong_toi_gateway_tren_host() -> None:
    """`base_url: http://127.0.0.1:1123/v1` trong container trỏ về chính container, không phải host."""
    hub = _hub()
    co_host_gateway = (
        hub.get("network_mode") == "host"
        or any("host.docker.internal" in str(h) for h in hub.get("extra_hosts", []))
    )
    assert co_host_gateway, (
        "service `hub` không có đường tới host: thiếu cả `network_mode: host` lẫn `extra_hosts` với "
        "`host.docker.internal`. Gateway (`127.0.0.1:1123`) là tiến trình trên HOST — trong container địa chỉ "
        "đó là chính container, nên hub không dùng được pool tài khoản của chính dự án.")
