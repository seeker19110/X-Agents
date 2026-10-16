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
        sub = argv[argv.index("-f") + 2]
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
