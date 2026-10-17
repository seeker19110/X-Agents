"""ADR-0061: biến bí mật cho `docker compose` của khách đi qua một file env NGOÀI repo, không qua env tiến trình.

`clean_env` (xagents_core.sandbox `SECRET_ENV`) bỏ mọi tên chứa `PASSWORD`/`TOKEN`/`_DSN`… khỏi env của lệnh con —
đúng cho agent, nhưng làm compose của khách không bao giờ nhận được mật khẩu DB staging. Hub thật 2026-10-16
(QLKH-DD-CSV, REL-099): `required variable QLKH_COMPOSE_DB_PASSWORD is missing a value`, compose của khách cố ý
không có giá trị mặc định (`${QLKH_COMPOSE_DB_PASSWORD:?…}`) sau finding gitleaks.

Hai chiều (luật bắt buộc 4): bỏ `--env-file` khỏi argv → ca 1 đỏ; bỏ kiểm quyền file → ca 4 đỏ; bỏ kiểm "file nằm
trong repo khách" → ca 5 đỏ.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from company.deploy import CMD_SUB, ENV_SECRETS_DIR, DeployError, deploy
from company.smoke import Runtime
from test_deploy_compose import PS_OK

RT = Runtime(("python", "-m", "http.server", "{port}"), path="/health", timeout_s=2, deploy="compose.yaml")
GIA_TRI_GIA = "gia-tri-gia-cua-test"


class Fake:
    """Runner giả: ghi argv + env, trả kết quả theo lệnh con (lệnh con = token đầu thuộc CMD_SUB sau `-f <file>`)."""

    def __init__(self, **rc: tuple[int, str, str]):
        self.calls: list[list[str]] = []
        self.envs: list[dict] = []
        self._rc = {"up": (0, "", ""), "ps": (0, PS_OK, ""), "logs": (0, "", ""), "down": (0, "", "")} | rc

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        self.envs.append(kw["env"])
        sub = next(t for t in argv[argv.index("--project-name") + 2:] if t in CMD_SUB)   # sau mọi `-f <file>`
        assert sub in CMD_SUB
        code, out, err = self._rc[sub]
        return subprocess.CompletedProcess(argv, code, out, err)


def _secrets(tmp_path: Path, name: str = "company-qlkh-dd-csv-staging.env", mode: int = 0o600) -> Path:
    d = tmp_path / "hub-secrets"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text(f"QLKH_COMPOSE_DB_PASSWORD={GIA_TRI_GIA}\n", encoding="utf-8")
    f.chmod(mode)
    return d


def _run(tmp_path: Path, monkeypatch, env: str = "staging", **rc):
    import company.deploy as D

    monkeypatch.setattr(D, "http_probe", lambda url: 200)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    fake = Fake(**rc)
    rec = deploy(repo, "QLKH-DD-CSV", env, RT, mode="compose", run=fake, which=lambda b: f"/usr/bin/{b}")
    return rec, fake


def test_file_env_cua_dung_project_va_env_di_vao_moi_lenh_compose(tmp_path, monkeypatch):
    d = _secrets(tmp_path)
    monkeypatch.setenv(ENV_SECRETS_DIR, str(d))
    rec, fake = _run(tmp_path, monkeypatch, ps=(0, "[]", ""))  # ps rỗng → nhánh hỏng: up, ps, logs, down
    want = str((d / "company-qlkh-dd-csv-staging.env").resolve())
    assert [c[c.index("-f") + 2] for c in fake.calls] == ["up", "ps", "logs", "down"]
    assert all(c[2:4] == ["--env-file", want] for c in fake.calls), "mọi lệnh con (kể cả down) cùng nội suy biến"
    assert rec.record()["env_file"] == want, "bằng chứng ghi file nào đã dùng — đường dẫn, không phải giá trị"
    assert GIA_TRI_GIA not in repr(rec.record()) and not any(GIA_TRI_GIA in " ".join(c) for c in fake.calls)
    assert not any(GIA_TRI_GIA in v for e in fake.envs for v in e.values()), "giá trị không vào env tiến trình"


def test_khong_dat_thu_muc_thi_argv_nhu_cu(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_SECRETS_DIR, raising=False)
    rec, fake = _run(tmp_path, monkeypatch)
    assert rec.ok and all("--env-file" not in c for c in fake.calls) and "env_file" not in rec.record()


def test_file_staging_khong_dung_cho_production(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_secrets(tmp_path)))
    rec, fake = _run(tmp_path, monkeypatch, env="production")
    assert rec.ok and all("--env-file" not in c for c in fake.calls), "tên file do code ghép theo project + env"


def test_file_ai_cung_doc_duoc_thi_tu_choi_truoc_khi_chay_compose(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_secrets(tmp_path, mode=0o644)))
    with pytest.raises(DeployError, match="chmod 600"):
        _run(tmp_path, monkeypatch)


def test_thu_muc_nam_trong_repo_khach_thi_tu_choi(tmp_path, monkeypatch):
    """Repo khách là thứ builder ghi được: file env trong đó là secret agent đọc/commit được."""
    repo = tmp_path / "repo"
    repo.mkdir()
    inside = repo / ".secrets"
    inside.mkdir()
    f = inside / "company-qlkh-dd-csv-staging.env"
    f.write_text(f"QLKH_COMPOSE_DB_PASSWORD={GIA_TRI_GIA}\n", encoding="utf-8")
    os.chmod(f, 0o600)
    monkeypatch.setenv(ENV_SECRETS_DIR, str(inside))
    with pytest.raises(DeployError, match="ngoài repo"):
        _run(tmp_path, monkeypatch)


# ---------- bổ sung 2026-10-16: che giá trị bí mật trong bằng chứng, có số đo ----------
# Hub thật (QLKH-DD-CSV REL-109, TM-SEC10-05 High): security chặn RC vì "mật khẩu DB có thể lộ vào log", không có
# bằng chứng giảm nhẹ. `DeployRecord` ghi `logs_tail` (log container) và `error` (stderr compose) lên bus — app in
# chuỗi kết nối DB là mật khẩu vào `release-events`. Phiên chính đo tay: 0 lần trong bus/artifact/journal — nhưng đó
# là lời khai; bằng chứng phải do máy ghi ngay trong RC.


def test_gia_tri_bi_mat_trong_log_va_loi_bi_che_va_co_so_do(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_secrets(tmp_path)))
    rec, _ = _run(
        tmp_path, monkeypatch, ps=(0, "[]", ""), logs=(0, f"app | postgresql://qlkh:{GIA_TRI_GIA}@db/qlkh\n", "")
    )
    r = rec.record()
    assert GIA_TRI_GIA not in repr(r), "giá trị trong file env không bao giờ vào bằng chứng"
    assert "postgresql://qlkh:***@db/qlkh" in r["logs_tail"]
    assert r["secret_redaction"] == {"values": 1, "hits": 1, "verified_by": "orchestrator"}


def test_loi_compose_chua_gia_tri_bi_mat_cung_bi_che(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_secrets(tmp_path)))
    rec, _ = _run(tmp_path, monkeypatch, up=(1, "", f"interpolation: {GIA_TRI_GIA} {GIA_TRI_GIA}"))
    r = rec.record()
    assert GIA_TRI_GIA not in repr(r) and r["secret_redaction"]["hits"] == 2


def test_doc_gia_tri_bi_mat_bo_chu_thich_dong_rong_va_gia_tri_ngan(tmp_path):
    from company.deploy import _secret_values

    f = tmp_path / "x.env"
    f.write_text(f"# A={GIA_TRI_GIA}\n\nPORT=8080\nB='{GIA_TRI_GIA}-2'\nKHONG_BANG\n", encoding="utf-8")
    assert _secret_values(str(f)) == [f"{GIA_TRI_GIA}-2"], "chú thích, rỗng, giá trị ngắn (cổng): không che"


def test_chay_sach_van_ghi_so_do_hits_bang_0_khong_file_thi_khong_ghi(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_secrets(tmp_path)))
    rec, _ = _run(tmp_path, monkeypatch)
    assert rec.ok and rec.record()["secret_redaction"] == {"values": 1, "hits": 0, "verified_by": "orchestrator"}
    monkeypatch.delenv(ENV_SECRETS_DIR)
    rec, _ = _run(tmp_path, monkeypatch)
    assert "secret_redaction" not in rec.record(), "không có file env bí mật thì không có gì để canh"


# ---------- bổ sung 2026-10-17: override compose theo env, ngoài repo ----------
# Hub thật (QLKH-DD-CSV REL-126): staging và production là hai compose project trên CÙNG một máy, compose của khách
# ghim `127.0.0.1:8080:8080` (ADR-DD-21) ⇒ production `up` hỏng "Bind for 127.0.0.1:8080 failed: port is already
# allocated". Sửa compose của khách là đổi ADR của khách; hub cấp `<project>.override.yml` cạnh file env bí mật.

OVERRIDE = "services:\n  app:\n    ports: !override\n      - \"127.0.0.1:8081:8080\"\n"


def _override(d: Path, name: str = "company-qlkh-dd-csv-production.override.yml", mode: int = 0o600) -> Path:
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text(OVERRIDE, encoding="utf-8")
    f.chmod(mode)
    return f


def test_override_cua_dung_project_va_env_xep_sau_compose_cua_khach(tmp_path, monkeypatch):
    f = _override(tmp_path / "hub-secrets")
    monkeypatch.setenv(ENV_SECRETS_DIR, str(f.parent))
    rec, fake = _run(tmp_path, monkeypatch, env="production", ps=(0, "[]", ""))  # nhánh hỏng: cả bốn lệnh con
    want = str(f.resolve())
    assert all(c[c.index("-f"):c.index("-f") + 4] == ["-f", "compose.yaml", "-f", want] for c in fake.calls), \
        "override xếp SAU file của khách (compose gộp theo thứ tự), ở MỌI lệnh con kể cả down"
    assert rec.record()["compose_override"] == want, "bằng chứng ghi override nào đã dùng"


def test_override_production_khong_dung_cho_staging(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_override(tmp_path / "hub-secrets").parent))
    rec, fake = _run(tmp_path, monkeypatch, env="staging")
    assert rec.ok and all(c.count("-f") == 1 for c in fake.calls) and "compose_override" not in rec.record()


def test_override_nguoi_khac_ghi_duoc_thi_tu_choi(tmp_path, monkeypatch):
    """Override đổi cổng, volume, image — ai ghi được nó là dựng được production."""
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_override(tmp_path / "hub-secrets", mode=0o664).parent))
    with pytest.raises(DeployError, match="ghi được"):
        _run(tmp_path, monkeypatch, env="production")


def test_override_nam_trong_repo_khach_thi_tu_choi(tmp_path, monkeypatch):
    inside = tmp_path / "repo" / ".hub"
    (tmp_path / "repo").mkdir()
    monkeypatch.setenv(ENV_SECRETS_DIR, str(_override(inside).parent))
    with pytest.raises(DeployError, match="ngoài repo"):
        _run(tmp_path, monkeypatch, env="production")
