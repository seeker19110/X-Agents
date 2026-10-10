"""ADR-0039 D1a: `company.deploy` — `deployed` là container đang chạy, không phải lời khai.

Máy chạy test (và `windows-latest` trong ma trận CI) KHÔNG có docker daemon, nên runner compose được **tiêm vào**
đúng như `which` của `sandbox_from_settings`: bốn nhánh của quyết định 3 (`up -d` đỏ / service `exited` / smoke đỏ
/ đường hạnh phúc) và fail-closed của quyết định 4 đo được mà không cần container thật.

Đo hai chiều (AGENTS.md luật 4) — bỏ từng vế của `ok` thì đúng một ca dưới đây phải đỏ:
- bỏ kiểm `ps` (chỉ tin `up -d`) → `test_service_exited_*` đỏ;
- bỏ smoke khỏi điều kiện → `test_smoke_do_*` đỏ;
- bỏ `down` ở nhánh hỏng → cả ba ca hỏng đỏ ở phần `assert "down" in ...`;
- `COMPANY_DEPLOY=compose` mà `which` trả None mà không raise → `test_compose_khai_dich_danh_*` đỏ.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from company.deploy import (
    CMD_SUB,
    ENV_MODE,
    ENV_RUNTIME,
    DeployError,
    DeployRecord,
    _argv,
    _published_port,
    _services,
    compose_file,
    deploy,
    deploy_settings,
    project_name,
)
from company.smoke import Runtime, parse_runtime

RT = Runtime(("python", "-m", "http.server", "{port}"), path="/health", timeout_s=2, deploy="compose.yaml")
PS_OK = json.dumps([{"Service": "web", "ID": "abcdef0123456789", "State": "running",
                     "Publishers": [{"PublishedPort": 8080, "TargetPort": 80}]}])
PS_EXITED = json.dumps([{"Service": "web", "ID": "abc", "State": "running",
                         "Publishers": [{"PublishedPort": 8080}]},
                        {"Service": "db", "ID": "def", "State": "exited"}])


class FakeCompose:
    """Runner giả: ghi lại từng argv, trả kết quả dựng sẵn theo LỆNH CON. Không chạy gì — đo đường đi và kết luận."""

    def __init__(self, **rc: tuple[int, str, str]):
        self.calls: list[list[str]] = []
        self.kwargs: list[dict] = []
        self._rc = {"up": (0, "", ""), "ps": (0, PS_OK, ""), "logs": (0, "log-cuoi", ""), "down": (0, "", "")} | rc

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        self.kwargs.append(kw)
        code, out, err = self._rc[argv[6]]
        return subprocess.CompletedProcess(argv, code, out, err)

    @property
    def subs(self) -> list[str]:
        return [c[6] for c in self.calls]


def _repo(tmp_path: Path, name: str = "compose.yaml") -> Path:
    (tmp_path / name).write_text("services: {}\n", encoding="utf-8")
    return tmp_path


def _deploy(tmp_path, rt=RT, *, which=lambda b: f"/usr/bin/{b}", **kw) -> tuple[DeployRecord, FakeCompose]:
    fake = FakeCompose(**kw)
    return deploy(_repo(tmp_path), "P1", "staging", rt, mode="auto", run=fake, which=which), fake


def _probe_tra(monkeypatch, status):
    """Thay probe HTTP: deploy dùng lại `smoke._probe`, test không mở socket thật."""
    import company.deploy as D
    monkeypatch.setattr(D, "http_probe", lambda url: status)


# ---------- quyết định 3: `ok` là kết luận ba phần ----------

def test_duong_hanh_phuc_ok_co_container_id_va_khong_goi_down(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, 200)
    r, fake = _deploy(tmp_path)
    assert r.ok is True and r.error == "" and r.skipped == ""
    assert r.project == "company-p1-staging" and r.env == "staging"
    assert r.services == ("web",) and r.container_ids == ("abcdef012345",), "id container là bằng chứng máy sinh"
    assert r.port == 8080 and r.smoke["http_status"] == 200 and r.started_at
    assert fake.subs == ["up", "ps"], f"deploy xong KHÔNG được `down` (sản phẩm phải còn sống): {fake.subs}"
    assert fake.calls[0][:6] == ["docker", "compose", "--project-name", "company-p1-staging", "-f", "compose.yaml"]
    assert fake.calls[0][6:] == ["up", "-d"]
    env = fake.kwargs[0]["env"]
    assert "PATH" in env and not [k for k in env if k.startswith(("GH_", "GITHUB_"))], "env phải qua clean_env"


def test_up_thoat_khac_0_thi_khong_ok_va_co_down(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, 200)
    r, fake = _deploy(tmp_path, up=(1, "", "no such image"))
    assert r.ok is False and "up -d" in r.error and "no such image" in r.error
    assert fake.subs == ["up", "logs", "down"], "hỏng thì thu log rồi dọn, không bỏ lại container nửa sống"
    assert r.logs_tail == "log-cuoi" and r.port is None


def test_service_exited_thi_khong_ok_du_up_thoat_0(tmp_path, monkeypatch):
    """Đo hai chiều: bỏ kiểm `compose ps` (chỉ tin `up -d` thoát 0) thì đúng ca này đỏ."""
    _probe_tra(monkeypatch, 200)
    r, fake = _deploy(tmp_path, ps=(0, PS_EXITED, ""))
    assert r.ok is False and "db=exited" in r.error and "running" in r.error
    assert r.services == ("web", "db") and "down" in fake.subs


def test_smoke_do_thi_khong_ok_du_container_running(tmp_path, monkeypatch):
    """Đo hai chiều: bỏ smoke khỏi điều kiện `ok` thì đúng ca này đỏ — container sống mà health 500."""
    _probe_tra(monkeypatch, 500)
    r, fake = _deploy(tmp_path)
    assert r.ok is False and r.error.startswith("smoke:")
    assert r.smoke["http_status"] == 500 and r.smoke["expect_status"] == 200 and r.smoke["ok"] is False
    assert r.smoke["url"] == "http://127.0.0.1:8080/health"
    assert "down" in fake.subs


def test_smoke_khong_tra_loi_trong_timeout_thi_ghi_ly_do(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, None)
    r, _ = _deploy(tmp_path, RT)
    assert r.ok is False and "không trả lời" in r.smoke["error"] and r.smoke["elapsed_s"] >= 0


def test_ps_hong_hoac_rong_deu_la_khong_deployed(tmp_path):
    r, fake = _deploy(tmp_path, ps=(1, "", "cannot connect to docker daemon"))
    assert r.ok is False and "ps:" in r.error and "daemon" in r.error and "down" in fake.subs
    r2, fake2 = _deploy(tmp_path, ps=(0, "[]", ""))
    assert r2.ok is False and "không có service nào" in r2.error and "down" in fake2.subs


def test_compose_khong_map_cong_thi_noi_thang_khong_co_gi_de_probe(tmp_path):
    ps = json.dumps([{"Service": "worker", "ID": "x1", "State": "running", "Publishers": []}])
    r, fake = _deploy(tmp_path, ps=(0, ps, ""))
    assert r.ok is False and "không map cổng nào" in r.error and "down" in fake.subs


def test_logs_hong_thi_bang_chung_rong_chu_khong_phai_stderr_gia_lam_log(tmp_path):
    r, _ = _deploy(tmp_path, up=(1, "", "boom"), logs=(1, "", "no such service"))
    assert r.logs_tail == "", "log hỏng thì để trống, không nhét stderr vào chỗ dành cho log sản phẩm"


# ---------- quyết định 4: fail-closed đúng khuôn `sandbox_from_settings` ----------

def test_auto_thieu_binary_tra_skipped_kem_ten_bien(tmp_path):
    r, fake = _deploy(tmp_path, which=lambda _b: None)
    assert r.ok is False and r.skipped and ENV_RUNTIME in r.skipped and ENV_MODE in r.skipped
    assert fake.calls == [], "thiếu binary thì không gọi lệnh nào"
    assert r.record()["skipped"] == r.skipped and "error" not in r.record()


def test_compose_khai_dich_danh_ma_thieu_binary_thi_raise_khong_phai_skipped(tmp_path):
    """Đo hai chiều: trả `skipped` thay vì ném ở nhánh này là âm thầm tụt hạng bảo vệ — ca này đỏ ngay."""
    with pytest.raises(DeployError, match="compose"):
        deploy(_repo(tmp_path), "P1", "staging", RT, mode="compose", run=FakeCompose(), which=lambda _b: None)


def test_mode_off_va_mode_la_deu_khong_chay_gi(tmp_path):
    fake = FakeCompose()
    r = deploy(_repo(tmp_path), "P1", "staging", RT, mode="off", run=fake, which=lambda b: b)
    assert r.skipped == f"{ENV_MODE}=off" and fake.calls == []
    with pytest.raises(DeployError, match="không hợp lệ"):
        deploy(_repo(tmp_path), "P1", "staging", RT, mode="ngau-nhien", run=fake, which=lambda b: b)


def test_env_ngoai_hai_moi_truong_la_loi(tmp_path):
    """`env` là của ROUTE (ADR-0039 §5). Nhận `env` lạ tức là để lời khai của model đặt tên project."""
    with pytest.raises(DeployError, match="env không hợp lệ"):
        deploy(_repo(tmp_path), "P1", "prod", RT, mode="auto", run=FakeCompose(), which=lambda b: b)


def test_mac_dinh_doc_tu_moi_truong(monkeypatch, tmp_path):
    assert deploy_settings() == ("auto", "docker")
    monkeypatch.setenv(ENV_MODE, "OFF")
    monkeypatch.setenv(ENV_RUNTIME, "podman")
    assert deploy_settings() == ("off", "podman")
    r = deploy(_repo(tmp_path), "P1", "staging", RT, run=FakeCompose(), which=lambda b: b)
    assert r.skipped == f"{ENV_MODE}=off", "không truyền `mode` thì đọc env, không mặc định `auto` cứng"


# ---------- compose file: của khách, không sinh, không đoán ----------

def test_khong_khai_va_khong_do_ra_compose_thi_skipped_chu_khong_phai_thanh_cong(tmp_path, monkeypatch):
    """Hai nửa của ADR-0039 §1: spec không khai nhưng repo có compose thì vẫn chạy; không có file nào thì
    `skipped` kèm lý do — và `skipped` KHÔNG phải deploy thành công."""
    # Không thay probe thì smoke gõ cổng 8080 THẬT suốt `timeout_s` mặc định (30 s) — ca chậm nhất bộ test.
    _probe_tra(monkeypatch, 200)
    _, fake = _deploy(tmp_path, Runtime(("x",)))
    assert fake.subs[:1] == ["up"], "dò ra `compose.yaml` thì vẫn chạy: deploy không đòi spec phải khai"

    trong = tmp_path / "rong"
    trong.mkdir()
    r = deploy(trong, "P1", "staging", Runtime(("x",)), mode="auto", run=FakeCompose(), which=lambda b: b)
    assert r.ok is False and "không dò ra" in r.skipped and r.error == ""


def test_khai_file_khong_ton_tai_khong_duoc_am_tham_roi_ve_file_do_duoc(tmp_path):
    repo = _repo(tmp_path)
    r = deploy(repo, "P1", "staging", Runtime(("x",), deploy="deploy/prod.yaml"), mode="auto",
               run=FakeCompose(), which=lambda b: b)
    assert r.skipped and r.ok is False, "khai sai đường dẫn mà chạy file khác là chạy thứ người ký không duyệt"


def test_compose_file_do_dung_hai_ten_mac_dinh(tmp_path):
    assert compose_file(tmp_path, Runtime(("x",))) == ""
    assert compose_file(_repo(tmp_path, "docker-compose.yml"), Runtime(("x",))) == "docker-compose.yml"
    assert compose_file(_repo(tmp_path), Runtime(("x",), deploy=" compose.yaml ")) == "compose.yaml"


def test_project_name_do_code_dat_khong_phai_payload():
    assert project_name("QLKH", "production") == "company-qlkh-production"


def test_project_name_hop_le_voi_compose():
    # audit 2026-09-23: compose chỉ nhận [a-z0-9_-] cho --project-name; mã dự án thật (QLKH, DHCB) viết hoa
    # nên `up -d` luôn thoát khác 0 → mọi deploy compose thành deploy_failed + gate leo thang.
    import re
    for pid in ("QLKH", "P1", "Dự Án.2"):
        assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project_name(pid, "staging")), pid


def test_runtime_deploy_doc_duoc_tu_spec_va_khong_co_thi_rong():
    assert parse_runtime({"runtime": {"command": ["x"], "deploy": "ops/compose.yaml"}}).deploy == "ops/compose.yaml"
    assert parse_runtime({"runtime": {"command": ["x"]}}).deploy == ""


def test_schema_approved_specs_khai_runtime_deploy():
    """Trường ghi vào payload mà schema không khai thì `guard` chặn event — hai nửa, thiếu nửa nào cũng hỏng."""
    schemas = Path(__file__).resolve().parents[1] / "topics" / "schemas" / "approved-specs.json"
    rt = json.loads(schemas.read_text(encoding="utf-8"))["properties"]["payload"]["properties"]["runtime"]
    assert rt["properties"]["deploy"]["type"] == "string" and "ADR-0039" in rt["properties"]["deploy"]["description"]


# ---------- đọc `ps`: hình dạng đầu ra không phải thứ công ty chọn được ----------

@pytest.mark.parametrize("out,n", [
    (PS_OK, 1),
    ('{"Service": "web"}', 1),                                  # một object trần
    ('{"Service": "a"}\n{"Service": "b"}', 2),                  # NDJSON của compose cũ
    ("", 0), ("khong-phai-json", 0), ('"chuoi"', 0), ("[1, 2]", 0),
])
def test_doc_ps_moi_hinh_dang(out, n):
    assert len(_services(out)) == n


def test_cong_lay_tu_ps_bo_qua_ban_ghi_vo_nghia():
    assert _published_port([{"Publishers": "khong-phai-list"}, {},
                            {"Publishers": [{"PublishedPort": None}, {"PublishedPort": 0},
                                            {"PublishedPort": "x"}, {"PublishedPort": 9000}]}]) == 9000
    assert _published_port([{"Publishers": [{"TargetPort": 80}]}]) is None


# ---------- ranh giới lệnh và bản ghi ----------

def test_chi_bon_lenh_con_duoc_ghep():
    assert set(CMD_SUB) == {"up", "ps", "logs", "down"}
    with pytest.raises(DeployError, match="không được phép"):
        _argv("docker", "company-P-staging", "compose.yaml", "exec", "sh")


def test_khong_co_binary_luc_chay_va_qua_gio_deu_thanh_ly_do_doc_duoc(tmp_path):
    def khong_co(argv, **kw):
        raise FileNotFoundError(argv[0])

    r = deploy(_repo(tmp_path), "P1", "staging", RT, mode="auto", run=khong_co, which=lambda b: b)
    assert r.ok is False and "không có trên máy" in r.error

    def qua_gio(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)

    r2 = deploy(_repo(tmp_path), "P1", "staging", RT, mode="auto", run=qua_gio, which=lambda b: b)
    assert r2.ok is False and "quá" in r2.error


def test_binary_co_that_ma_khong_chay_duoc_thi_ly_do_doc_duoc(tmp_path):
    """`_compose` hứa "không ném" nhưng chỉ bắt `FileNotFoundError`: binary CÓ trên đĩa mà không chạy được ném
    `OSError` khác, xuyên qua `deploy()` (cả `up -d` lẫn `logs`/`down` của nhánh dọn). File thật,
    `subprocess.run` thật; đuôi `.exe` để Windows không tự thêm `.exe` rồi đọc thành "không có"."""
    f = tmp_path / "khong-chay.exe"
    f.write_text("khong phai binary\n", encoding="utf-8")   # 0o644: không ai chạy được, kể cả root
    r = deploy(_repo(tmp_path), "P1", "staging", RT, mode="compose", binary=str(f),
               run=subprocess.run, which=lambda b: b)
    assert r.ok is False and "không chạy được" in r.error and r.logs_tail == ""


def test_record_la_bang_chung_ghi_duoc_vao_event(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, 200)
    r, _ = _deploy(tmp_path)
    ev = r.record()
    assert ev["verified_by"] == "orchestrator" and ev["ok"] is True
    assert ev["services"] == ["web"] and ev["container_ids"] == ["abcdef012345"] and ev["port"] == 8080
    assert ev["compose_file"] == "compose.yaml" and ev["smoke"]["ok"] is True
    assert "skipped" not in ev and "error" not in ev and "logs_tail" not in ev
