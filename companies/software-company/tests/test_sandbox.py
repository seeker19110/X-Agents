"""Hợp đồng `Sandbox` (ADR-0035): cùng bộ khẳng định chạy cho CẢ HAI backend.

Backend container dùng `runner=`/`popen=` giả nên test không cần docker và không chạm mạng.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from company.llm import LLMConfig, load_config
from company.sandbox import (
    ContainerSandbox,
    Result,
    RunSpec,
    SandboxError,
    SubprocessSandbox,
    sandbox_from_config,
    sanitize_env,
)


class FakeRunner:
    """Thay `subprocess.run`: ghi lại lời gọi, trả `CompletedProcess` (hoặc ném TimeoutExpired)."""

    def __init__(self, returncode: int = 0, stdout: str = "out", stderr: str = "err", timeout: bool = False):
        self.rc, self.stdout, self.stderr, self.timeout = returncode, stdout, stderr, timeout
        self.calls: list[dict] = []

    def __call__(self, argv, **kw):
        self.calls.append({"argv": list(argv), **kw})
        if self.timeout:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout", 1))
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, self.stderr)


class FakeStdin:
    def __init__(self): self.text, self.closed = "", False
    def write(self, s): self.text += s
    def close(self): self.closed = True


class FakeProc:
    def __init__(self, codes=(None, 0), err="boom stderr"):
        self._codes, self._i, self.err = list(codes), 0, err
        self.killed = False
        self.stdin = FakeStdin()

    def poll(self):
        rc = self._codes[min(self._i, len(self._codes) - 1)]
        self._i += 1
        return rc

    def kill(self): self.killed = True
    def communicate(self, timeout=None): return ("", self.err)


class FakePopen:
    def __init__(self, proc: FakeProc):
        self.proc, self.calls = proc, []

    def __call__(self, argv, **kw):
        self.calls.append({"argv": list(argv), **kw})
        return self.proc


def spec(tmp_path: Path, **kw) -> RunSpec:
    return RunSpec(argv=["pytest", "-q"], cwd=tmp_path, env={"PATH": "/usr/bin"}, timeout=5.0, **kw)


def both(tmp_path: Path):
    return [SubprocessSandbox(runner=FakeRunner()), ContainerSandbox("docker", "img", runner=FakeRunner())]


# ---------- bộ hợp đồng: chạy cho cả hai backend ----------

@pytest.mark.parametrize("idx", [0, 1])
def test_hop_dong_run_tra_result_day_du(tmp_path, idx):
    sb = both(tmp_path)[idx]
    r = sb.run(spec(tmp_path))
    assert isinstance(r, Result)
    assert (r.exit_code, r.timed_out) == (0, False)
    assert r.stdout == "out" and r.stderr == "err"
    assert r.sandbox == sb.name and sb.name


@pytest.mark.parametrize("idx", [0, 1])
def test_hop_dong_timeout(tmp_path, idx):
    sb = [SubprocessSandbox(runner=FakeRunner(timeout=True)),
          ContainerSandbox("docker", "img", runner=FakeRunner(timeout=True))][idx]
    r = sb.run(spec(tmp_path))
    assert r.timed_out is True and r.exit_code is None and "quá 5.0s" in r.stderr


@pytest.mark.parametrize("idx", [0, 1])
def test_hop_dong_cat_max_output(tmp_path, idx):
    long = "x" * 9000
    sb = [SubprocessSandbox(runner=FakeRunner(stdout=long, stderr=long)),
          ContainerSandbox("docker", "img", runner=FakeRunner(stdout=long, stderr=long))][idx]
    r = sb.run(RunSpec(argv=["a"], cwd=tmp_path, max_output=6000))
    assert len(r.stdout) == 6000 and len(r.stderr) == 6000


@pytest.mark.parametrize("idx", [0, 1])
def test_hop_dong_env_da_qua_clean_env(tmp_path, idx, monkeypatch):
    runner = FakeRunner()
    sb = [SubprocessSandbox(runner=runner), ContainerSandbox("docker", "img", runner=runner, env_via_stdin=True)][idx]
    dirty = {"PATH": "/usr/bin", "ANTHROPIC_API_KEY": "sk-secret", "DATABASE_URL": "postgres://u:p@h/db",
             "GITHUB_TOKEN": "ghp_x", "SSH_AUTH_SOCK": "/tmp/s"}
    sb.run(RunSpec(argv=["a"], cwd=tmp_path, env=dirty))
    call = runner.calls[0]
    seen = call["env"] if "env" in call else dict(x.split("=", 1) for x in call["input"].splitlines())
    assert "PATH" in seen and seen["PYTHONDONTWRITEBYTECODE"] == "1"
    for k in ("ANTHROPIC_API_KEY", "DATABASE_URL", "GITHUB_TOKEN", "SSH_AUTH_SOCK"):
        assert k not in seen
    assert "sk-secret" not in repr(seen)


@pytest.mark.parametrize("idx", [0, 1])
def test_hop_dong_spawn_handle(tmp_path, idx, monkeypatch):
    monkeypatch.setattr("xagents_core.sandbox._kill_tree", lambda p: p.kill())
    proc = FakeProc(codes=(None, 3))
    popen = FakePopen(proc)
    # runner giả: kill() của container còn gọi `docker rm -f <tên>` — test không được chạm docker thật.
    sb = [SubprocessSandbox(popen=popen), ContainerSandbox("docker", "img", runner=FakeRunner(), popen=popen)][idx]
    h = sb.spawn(spec(tmp_path, network=True, port=8123))
    assert h.poll() is None
    assert h.poll() == 3
    h.kill()
    assert proc.killed is True
    assert h.stderr_tail(6) == "stderr"
    assert h.stderr_tail(6) == "stderr"   # lần hai dùng lại đuôi đã đọc, không communicate lần nữa


# ---------- riêng SubprocessSandbox ----------

def test_subprocess_chay_that(tmp_path):
    sb = SubprocessSandbox()
    r = sb.run(RunSpec(argv=[sys.executable, "-c", "print('hi')"], cwd=tmp_path, timeout=60))
    assert r.exit_code == 0 and "hi" in r.stdout and r.sandbox == "subprocess"


def test_subprocess_env_none_lay_clean_env(tmp_path):
    runner = FakeRunner()
    SubprocessSandbox(runner=runner).run(RunSpec(argv=["a"], cwd=tmp_path, env=None))  # type: ignore[arg-type]
    assert "PATH" in {k.upper(): 1 for k in runner.calls[0]["env"]} or runner.calls[0]["env"]


def test_handle_communicate_loi_thi_duoi_rong(tmp_path):
    class Bad(FakeProc):
        def communicate(self, timeout=None): raise subprocess.TimeoutExpired("x", 5)
    sb = SubprocessSandbox(popen=FakePopen(Bad()))
    assert sb.spawn(spec(tmp_path)).stderr_tail(10) == ""


# ---------- riêng ContainerSandbox: argv chính xác từng cờ ----------

def test_container_argv_mac_dinh_khong_mang(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: 1000, raising=False)
    runner = FakeRunner()
    sb = ContainerSandbox("docker", "python:3.12-slim", runner=runner, env_via_stdin=True)
    sb.run(spec(tmp_path))
    argv = runner.calls[0]["argv"]
    name = argv[argv.index("--name") + 1]   # tên sinh mỗi lần chạy để dọn được container khi timeout/kill
    assert name.startswith("xagents-") and argv == [
        "docker", "run", "--rm", "--name", name, "--pids-limit", "256", "--cpus", "2", "--memory", "2g",
        "-u", "1000:1000", "-v", f"{tmp_path}:/w:rw", "-w", "/w", "--env-file", "/dev/stdin",
        "--network", "none", "python:3.12-slim", "pytest", "-q"]
    assert sb.name == "container:python:3.12-slim"


def test_container_argv_co_mang_thi_publish_cong(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: 20, raising=False)
    runner = FakeRunner()
    ContainerSandbox("podman", "img", cpus="4", memory="8g", runner=runner).run(
        spec(tmp_path, network=True, port=8123))
    argv = runner.calls[0]["argv"]
    assert argv[:3] == ["podman", "run", "--rm"]
    assert argv[argv.index("--cpus") + 1] == "4" and argv[argv.index("--memory") + 1] == "8g"
    assert "--network" in argv and argv[argv.index("--network") + 1] == "bridge"
    assert argv[argv.index("-p") + 1] == "127.0.0.1:8123:8123"
    assert "none" not in argv


def test_container_windows_khong_co_getuid_van_chay(tmp_path, monkeypatch):
    """Repo này chạy chính trên Windows: `os.getuid` không tồn tại → bỏ `-u`, tên nói rõ `no-uid`."""
    monkeypatch.delattr(os, "getuid", raising=False)
    monkeypatch.delattr(os, "getgid", raising=False)
    runner = FakeRunner()
    sb = ContainerSandbox("docker", "img", runner=runner, env_via_stdin=True)
    sb.run(spec(tmp_path))
    assert "-u" not in runner.calls[0]["argv"]
    assert sb.name == "container:img:no-uid"


def test_container_thieu_getgid_cung_coi_la_no_uid(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    monkeypatch.delattr(os, "getgid", raising=False)
    assert ContainerSandbox("docker", "img", runner=FakeRunner(), env_via_stdin=True).name == "container:img:no-uid"


def test_container_env_file_bo_gia_tri_nhieu_dong(tmp_path):
    runner = FakeRunner()
    ContainerSandbox("docker", "img", runner=runner, env_via_stdin=True).run(
        RunSpec(argv=["a"], cwd=tmp_path, env={"OK": "1", "MULTI": "a\nb"}))
    assert "OK=1" in runner.calls[0]["input"] and "MULTI" not in runner.calls[0]["input"]


def test_container_spawn_ghi_env_vao_stdin(tmp_path):
    proc = FakeProc()
    popen = FakePopen(proc)
    ContainerSandbox("docker", "img", popen=popen, env_via_stdin=True).spawn(RunSpec(argv=["a"], cwd=tmp_path, env={"OK": "1"}))
    assert "OK=1" in proc.stdin.text and proc.stdin.closed is True


def test_container_spawn_khong_co_stdin_van_chay(tmp_path):
    proc = FakeProc()
    proc.stdin = None  # type: ignore[assignment]
    ContainerSandbox("docker", "img", popen=FakePopen(proc)).spawn(RunSpec(argv=["a"], cwd=tmp_path))


# ---------- sandbox_from_config: thứ tự ưu tiên + fail-closed ----------

@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    for k in ("COMPANY_SANDBOX", "COMPANY_SANDBOX_IMAGE", "COMPANY_SANDBOX_RUNTIME"):
        monkeypatch.delenv(k, raising=False)


def test_from_config_container_thieu_binary_thi_loi_khong_tut_hang(monkeypatch):
    """Fail-closed: khai đích danh `container` mà không có docker → SandboxError, KHÔNG âm thầm về subprocess."""
    cfg = LLMConfig(sandbox="container")
    with pytest.raises(SandboxError) as e:
        sandbox_from_config(cfg, which=lambda _: None)
    assert "container" in str(e.value) and "docker" in str(e.value)


def test_from_config_container_co_binary(monkeypatch):
    sb = sandbox_from_config(LLMConfig(sandbox="container", sandbox_image="node:22"), which=lambda _: "/usr/bin/docker")
    assert isinstance(sb, ContainerSandbox) and sb.image == "node:22"


def test_from_config_auto_chon_container_khi_co_binary():
    assert isinstance(sandbox_from_config(LLMConfig(), which=lambda _: "/usr/bin/docker"), ContainerSandbox)


def test_from_config_auto_thieu_runtime_phai_dung():
    with pytest.raises(SandboxError, match="COMPANY_SANDBOX=subprocess"):
        sandbox_from_config(LLMConfig(), which=lambda _: None)


def test_from_config_subprocess_khai_dich_danh():
    assert isinstance(sandbox_from_config(LLMConfig(sandbox="subprocess"), which=lambda _: "/d"), SubprocessSandbox)


def test_from_config_env_thang_cau_hinh(monkeypatch):
    monkeypatch.setenv("COMPANY_SANDBOX", "subprocess")
    assert isinstance(sandbox_from_config(LLMConfig(sandbox="container"), which=lambda _: None), SubprocessSandbox)


def test_from_config_env_runtime_va_image(monkeypatch):
    monkeypatch.setenv("COMPANY_SANDBOX_RUNTIME", "podman")
    monkeypatch.setenv("COMPANY_SANDBOX_IMAGE", "golang:1.24")
    seen: list[str] = []
    sb = sandbox_from_config(LLMConfig(sandbox="container"), which=lambda r: seen.append(r) or "/usr/bin/podman")
    assert seen == ["podman"] and isinstance(sb, ContainerSandbox) and sb.image == "golang:1.24"


def test_from_config_che_do_la_thi_loi():
    with pytest.raises(SandboxError, match="không hợp lệ"):
        sandbox_from_config(LLMConfig(sandbox="vm"), which=lambda _: None)


def test_from_config_cfg_rong_thi_ve_auto():
    with pytest.raises(SandboxError, match="COMPANY_SANDBOX=subprocess"):
        sandbox_from_config(LLMConfig(sandbox="", sandbox_runtime="", sandbox_image=""), which=lambda _: None)


# ---------- cấu hình đọc từ yaml + env ----------

def test_llm_config_doc_sandbox_tu_yaml(tmp_path, monkeypatch):
    p = tmp_path / "llm.yaml"
    p.write_text("provider: fake\nsandbox: container\nsandbox_image: node:22\nsandbox_runtime: podman\n",
                 encoding="utf-8")
    cfg = load_config(p)
    assert (cfg.sandbox, cfg.sandbox_image, cfg.sandbox_runtime) == ("container", "node:22", "podman")


def test_llm_config_env_thang_yaml(tmp_path, monkeypatch):
    p = tmp_path / "llm.yaml"
    p.write_text("provider: fake\nsandbox: container\n", encoding="utf-8")
    monkeypatch.setenv("COMPANY_SANDBOX", "subprocess")
    monkeypatch.setenv("COMPANY_SANDBOX_IMAGE", "img:1")
    monkeypatch.setenv("COMPANY_SANDBOX_RUNTIME", "podman")
    cfg = load_config(p)
    assert (cfg.sandbox, cfg.sandbox_image, cfg.sandbox_runtime) == ("subprocess", "img:1", "podman")


def test_llm_config_mac_dinh_la_auto(tmp_path):
    assert load_config(tmp_path / "khong-co.yaml").sandbox == "auto"


def test_sanitize_env_none_lay_moi_truong_that(monkeypatch):
    monkeypatch.setenv("COMPANY_TEST_MARKER", "1")
    monkeypatch.setenv("COMPANY_LLM_API_KEY", "sk-x")
    out = sanitize_env(None)
    assert out["COMPANY_TEST_MARKER"] == "1" and "COMPANY_LLM_API_KEY" not in out
