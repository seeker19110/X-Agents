"""Sandbox tiến trình cho lệnh con — lõi chung hai công ty (ADR-0035 của software-company, ADR gốc 0001 K3.2).

Trước ADR-0035, "sandbox" chỉ là *đường dẫn + env*: lệnh của khách (lint/test theo stack, lệnh khởi động do model
viết ra) và lệnh media (TTS, ffmpeg, ffprobe) chạy bằng quyền người vận hành và thấy cả `HOME`. Module này gói mọi
điểm gọi subprocess của cả hai công ty sau một giao diện duy nhất, để đổi sang container mà không sửa nơi gọi.

Hai backend: `SubprocessSandbox` (giữ NGUYÊN hành vi cũ — cùng cách cắt output, cùng timeout, cùng `clean_env`) và
`ContainerSandbox` (docker/podman `run --rm`, mạng tắt mặc định). **Fail-closed**: khai đích danh `container` mà
không có binary thì `SandboxError`, không bao giờ âm thầm tụt về subprocess.

Git KHÔNG đi qua đây (ADR-0035): argv hard-code, hook đã bị vô hiệu, push cần credential của người vận hành.

`RunSpec` là hợp của nhu cầu hai bên, mỗi trường có đúng một chỗ dùng thật:

- `network` + `port` — `company.smoke` probe 127.0.0.1 trong container.
- `stdin` — `studio.media.CommandTTS` đưa văn bản vào stdin lệnh TTS. Với `ContainerSandbox`, stdin đã bị
  `--env-file /dev/stdin` chiếm, nên khi có `stdin` thì env buộc quay về `-e KEY=VALUE` (giá trị **hiện trong danh sách
  tiến trình** của máy — đánh đổi ghi ở đây để không ai tưởng là kín).
- `read_only` — `studio.qc` chỉ đo file, mount `:ro`.

Studio đã rời repo: `stdin` và `read_only` nay không còn chỗ gọi nào ngoài test của core, và `sandbox_from_settings`
chỉ còn company gọi — keeper chỉ dùng `clean_env` (đo 2026-09-28). Giữ vì là API core có test; gỡ là quyết định riêng.

**Chọn backend là việc của công ty, không phải của core**: `sandbox_from_settings` dưới đây nhận mode/runtime/image
đã đọc sẵn, còn *đọc từ đâu* thì mỗi bên tự làm — nguồn cấu hình khác nhau (`cfg.sandbox` của company vs
`media.yaml render.sandbox` của studio), tên biến môi trường khác nhau, và **mặc định cũng khác**: company `auto`,
studio `subprocess`. Studio cố ý không `auto` vì ffmpeg/ffprobe nhận đường dẫn tuyệt đối trải trên nhiều thư mục
mà container chỉ thấy `cwd` được mount — muốn container thì phải khai đích danh và tự lo mount.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .egress import EgressProxy, EgressSession

# Hợp đồng của shim `company.sandbox` (keeper nhập thẳng core): `import *` chỉ mang tên trong đây.
__all__ = ["SECRET_ENV", "ContainerSandbox", "Handle", "Result", "RunSpec", "Sandbox", "SandboxError",
           "SubprocessSandbox", "clean_env", "sandbox_from_settings", "sanitize_env"]

# `<PREFIX>_LLM_*` — cấu hình model của MỌI công ty (`COMPANY_LLM_PROVIDER`, `KEEPER_LLM_BACKENDS`…). Viết theo hình,
# không liệt kê tên: core không được biết tên công ty (ADR gốc 0001 §2), và bản liệt kê cũ `COMPANY_LLM|STUDIO_LLM`
# đã sót keeper (đo 2026-09-28). `llm.cli_env` dùng lại nó để không `keep_prefixes` nào mở được không gian này.
LLM_ENV = re.compile(r"_LLM(_|$)", re.IGNORECASE)

SECRET_ENV = re.compile(
    r"(API_?KEY|TOKEN|SECRET|PASSW(OR)?D|CREDENTIAL|ACCESS_KEY|PRIVATE_KEY|SESSION_KEY|SIGNING_KEY|AUTH(?!OR)"
    r"|_URL$|_URI$|_DSN$|DATABASE|CONNECTION_STRING|SSH_AUTH_SOCK|^GITHUB_|^GH_|^NPM_|^PYPI_|^AWS_|^AZURE_|^GOOGLE_"
    r"|^OPENAI_|^ANTHROPIC_|" + LLM_ENV.pattern + r"|^CLAUDE_CONFIG_DIR$|^CODEX_HOME$"
    # ADR-0016: con trỏ tới tầng máy — không phải bí mật, mà là ĐƯỜNG ĐẾN bí mật, cùng họ CLAUDE_CONFIG_DIR.
    r"|^XAGENTS_LLM_CONFIG$)",
    re.IGNORECASE)


def clean_env() -> dict[str, str]:
    """Env cho lệnh con: bỏ mọi biến trông như khoá. Lệnh TTS cục bộ (Piper, edge-tts) và ffmpeg là mã của người
    khác chạy dưới quyền người vận hành — không có lý do gì để chúng thấy `ELEVENLABS_API_KEY`."""
    return {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)} | {"PYTHONDONTWRITEBYTECODE": "1"}


class SandboxError(Exception):
    """Không dựng được sandbox đã yêu cầu. Cố ý là lỗi, không phải cảnh báo (fail-closed)."""


@dataclass(frozen=True)
class RunSpec:
    """Một lệnh cần chạy. `network=False` là mặc định; `read_only=True` mount cwd `:ro` (qc chỉ đo, không ghi)."""
    argv: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 600.0
    network: bool = False
    port: int | None = None
    max_output: int = 6000
    stdin: str | None = None
    read_only: bool = False
    allowed_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class Result:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    sandbox: str


@runtime_checkable
class Handle(Protocol):
    """Tiến trình đang chạy: poll trong lúc chờ, giết, rồi lấy đuôi stderr."""
    def poll(self) -> int | None: ...
    def kill(self) -> None: ...
    def stderr_tail(self, n: int) -> str: ...


class Sandbox(Protocol):
    name: str
    def run(self, spec: RunSpec) -> Result: ...
    def spawn(self, spec: RunSpec) -> Handle: ...


def sanitize_env(env: dict[str, str] | None) -> dict[str, str]:
    """Env cuối cùng của lệnh con. Lọc lại lần nữa ngay tại sandbox dù nơi gọi đã `clean_env()`: sandbox là chỗ
    cuối cùng biến môi trường đi qua, không dựa vào kỷ luật của nơi gọi."""
    base = clean_env() if env is None else dict(env)
    return {k: v for k, v in base.items() if not SECRET_ENV.search(k)} | {"PYTHONDONTWRITEBYTECODE": "1"}


class _ProcHandle:
    """Bọc `Popen` đúng vòng đời: poll → kill → communicate(timeout=5) → đuôi stderr."""

    def __init__(self, proc: Any, on_kill: Any = None):
        self.proc = proc
        self._tail = ""
        self._on_kill = on_kill

    def poll(self) -> int | None:
        rc = self.proc.poll()
        return None if rc is None else int(rc)

    def kill(self) -> None:
        self.proc.kill()
        if self._on_kill is not None:
            self._on_kill()

    def stderr_tail(self, n: int) -> str:
        if not self._tail:
            try:
                _, err = self.proc.communicate(timeout=5)
            except (subprocess.TimeoutExpired, ValueError):
                err = ""
            self._tail = err or ""
        return self._tail[-n:]


def _kill_tree(proc: Any, runner: Any = subprocess.run) -> None:
    """Giết CẢ CÂY của `proc`, không chỉ con trực tiếp. Windows: `taskkill /T` đi theo quan hệ cha-con từ gốc (gốc
    còn sống lúc hết giờ nên cây còn tìm được); POSIX: cả nhóm tiến trình (`start_new_session=True` lúc dựng).
    Nỗ lực tốt nhất: cây đã tự tan hay `taskkill` treo không được che kết quả timeout — `proc.kill()` luôn chạy."""
    try:
        if sys.platform == "win32":
            runner(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    proc.kill()


def _run_tree(argv: list[str], *, cwd: str, env: dict[str, str], input: str | None, timeout: float,
              popen: Any = subprocess.Popen, kill_tree: Any = _kill_tree, **_: Any) -> subprocess.CompletedProcess[str]:
    """Như `subprocess.run(capture_output=True, text=True, encoding="utf-8", errors="replace")`, trừ hai chỗ khi hết
    giờ: giết CẢ CÂY (`_kill_tree`), và chờ ống tối đa 5s thay vì vô hạn. `subprocess.run` chỉ giết con trực tiếp,
    rồi trên Windows `communicate()` không trần — cháu (`uv run` → launcher venv → python thật) còn giữ ống stdout
    là treo tới khi cháu tự xong. Đo được 2026-09-24 (CAMPUS-UNI/TCK-002): orchestrator 0% CPU, 0 event 20+ phút
    trong khi pytest mồ côi ăn 1245s CPU."""
    extra: dict[str, Any] = {} if sys.platform == "win32" else {"start_new_session": True}
    proc = popen(argv, cwd=cwd, env=env, stdin=None if input is None else subprocess.PIPE, stdout=subprocess.PIPE,
                 stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **extra)
    try:
        out, err = proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError):
            pass
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


class _TreeHandle(_ProcHandle):
    """Tiến trình nền có cùng ranh giới dừng cả cây như đường run()."""

    def kill(self) -> None:
        _kill_tree(self.proc)


class SubprocessSandbox:
    """Hành vi hiện tại: tiến trình con của chính người vận hành, cô lập bằng cwd + env đã lọc khoá. Hết giờ thì
    giết cả cây tiến trình (`_run_tree`), không chỉ con trực tiếp."""

    def __init__(self, runner: Any = _run_tree, popen: Any = subprocess.Popen):
        self.name = "subprocess"
        self._runner, self._popen = runner, popen

    def run(self, spec: RunSpec) -> Result:
        if spec.allowed_domains:
            raise SandboxError("subprocess không enforce được allowed_domains")
        try:
            r = self._runner(spec.argv, cwd=str(spec.cwd), capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=spec.timeout, env=sanitize_env(spec.env), input=spec.stdin)
        except subprocess.TimeoutExpired:
            return Result(None, "", f"quá {spec.timeout}s", True, self.name)
        except OSError as e:   # thiếu binary / cwd: 127 như shell trong container báo, không ném xuyên nơi gọi
            return Result(127, "", f"không chạy được {spec.argv[0]!r} trong {spec.cwd}: {e.strerror or e}", False,
                          self.name)
        return Result(int(r.returncode), (r.stdout or "")[-spec.max_output:], (r.stderr or "")[-spec.max_output:],
                      False, self.name)

    def spawn(self, spec: RunSpec) -> Handle:
        if spec.allowed_domains:
            raise SandboxError("subprocess không enforce được allowed_domains")
        extra: dict[str, Any] = {} if sys.platform == "win32" else {"start_new_session": True}
        return _TreeHandle(self._popen(spec.argv, cwd=str(spec.cwd), env=sanitize_env(spec.env),
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                       encoding="utf-8", errors="replace", **extra))


def _container_name() -> str:
    """Tên riêng mỗi lần chạy: không có `--name` thì container bỏ lại sau timeout không gọi tên được để dọn."""
    return f"xagents-{uuid.uuid4().hex[:16]}"


class ContainerSandbox:
    """`docker`/`podman run --rm` với cwd mount vào `/w`, mạng tắt, hạn mức pid/cpu/ram.

    Env đi qua `--env-file /dev/stdin` (stdin) chứ không phải `-e`: giá trị không hiện trong danh sách tiến trình của máy.
    Ngoại lệ: `RunSpec.stdin` cần chính stdin đó, lúc ấy env buộc phải quay về `-e` (xem docstring module)."""

    def __init__(self, runtime: str, image: str, cpus: str = "2", memory: str = "2g",
                 runner: Any = subprocess.run, popen: Any = subprocess.Popen,
                 env_via_stdin: bool | None = None, egress: EgressProxy | None = None):
        self.runtime, self.image, self.cpus, self.memory = runtime, image, cpus, memory
        self._runner, self._popen = runner, popen
        self._egress = egress
        # Windows không có `/dev/stdin` cho Docker CLI; env ra `-e` như ca stdin (cùng đánh đổi, xem docstring
        # module); `None` = tự chọn theo hệ điều hành, đặt tường minh để test không phụ thuộc máy chạy. Tên mang
        # `:env-argv` cùng khuôn `:no-uid`: audit đọc tên là biết cách ly còn gì.
        self.env_via_stdin = (os.name != "nt") if env_via_stdin is None else env_via_stdin
        self.name = (f"container:{image}" + ("" if self._uid() else ":no-uid")
                     + ("" if self.env_via_stdin else ":env-argv"))

    @staticmethod
    def _uid() -> str | None:
        """Windows không có `os.getuid` → bỏ cờ `-u` (container chạy user mặc định của image) và nói thẳng trong
        tên sandbox để audit không tưởng là đã hạ quyền."""
        getuid, getgid = getattr(os, "getuid", None), getattr(os, "getgid", None)
        if getuid is None or getgid is None:
            return None
        return f"{getuid()}:{getgid()}"

    def _remove(self, name: str) -> None:
        """Giết client `docker run` KHÔNG dừng container — nó sống tiếp dưới daemon. Dọn theo tên, nỗ lực tốt
        nhất: binary biến mất hay `rm` treo không được che kết quả timeout/kill của lệnh chính."""
        try:
            self._runner([self.runtime, "rm", "-f", name], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass

    def _argv(self, spec: RunSpec, name: str, network: str = "none") -> list[str]:
        base = [self.runtime, "run", "--rm", "--name", name, "--pids-limit", "256", "--cpus", self.cpus, "--memory", self.memory]
        uid = self._uid()
        if uid: base += ["-u", uid]
        base += ["-v", f"{spec.cwd}:/w:{'ro' if spec.read_only else 'rw'}", "-w", "/w"]
        if spec.stdin is None and self.env_via_stdin:
            base += ["--env-file", "/dev/stdin"]
        else:
            if spec.stdin is not None: base += ["-i"]
            for k, v in sanitize_env(spec.env).items():
                base += ["-e", f"{k}={v}"]
        base += ["--network", network]
        if network != "none": base += ["--dns", "127.0.0.1"]
        return [*base, self.image, *spec.argv]

    def _input(self, spec: RunSpec) -> str:
        # `/dev/stdin` đọc từng dòng KEY=VALUE trên stdin; giá trị nhiều dòng không hợp lệ nên bỏ.
        if spec.stdin is not None:
            return spec.stdin
        if not self.env_via_stdin:
            return ""   # env đã ra `-e`; không đẩy KEY=VALUE vào stdin của một lệnh không đọc nó
        return "\n".join(f"{k}={v}" for k, v in sanitize_env(spec.env).items() if "\n" not in v)

    def _prepare(self, spec: RunSpec, name: str) -> tuple[RunSpec, EgressSession | None]:
        spec = replace(spec, env={k: v for k, v in sanitize_env(spec.env).items()
                                  if k.upper() not in {"PATH", "VIRTUAL_ENV"}})
        if not spec.network and not spec.allowed_domains:
            return spec, None
        from .egress import DockerSquidProxy
        proxy = self._egress or DockerSquidProxy(self.runtime)
        session = proxy.open(name, spec.allowed_domains, port=spec.port if spec.network else None)
        return replace(spec, env=sanitize_env(spec.env) | session.env), session

    def run(self, spec: RunSpec) -> Result:
        name = _container_name()
        spec, session = self._prepare(spec, name)
        try:
            try:
                r = self._runner(self._argv(spec, name, session.network if session else "none"),
                                 input=self._input(spec), capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=spec.timeout)
            except subprocess.TimeoutExpired:
                self._remove(name)
                return Result(None, "", f"quá {spec.timeout}s", True, self.name)
            return Result(int(r.returncode), (r.stdout or "")[-spec.max_output:], (r.stderr or "")[-spec.max_output:],
                          False, self.name)
        finally:
            if session: session.close()

    def spawn(self, spec: RunSpec) -> Handle:
        name = _container_name()
        spec, session = self._prepare(spec, name)
        try:
            proc = self._popen(self._argv(spec, name, session.network if session else "none"), stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace")
            if proc.stdin is not None:
                proc.stdin.write(self._input(spec))
                proc.stdin.close()
        except BaseException:
            self._remove(name)
            if session: session.close()
            raise
        handle = _ProcHandle(proc, on_kill=lambda: self._remove(name))
        return _NetworkHandle(handle, session) if session else handle


class _NetworkHandle:
    """Giữ network đến khi workload thoát/kill, rồi dọn đúng một lần."""

    def __init__(self, handle: Handle, session: EgressSession):
        self.handle, self.session = handle, session
        self.closed = False

    def _close(self) -> None:
        if not self.closed:
            self.closed = True
            self.session.close()

    def poll(self) -> int | None:
        rc = self.handle.poll()
        if rc is not None: self._close()
        return rc

    def kill(self) -> None:
        try:
            self.handle.kill()
        finally:
            self._close()

    def stderr_tail(self, n: int) -> str:
        return self.handle.stderr_tail(n)


def sandbox_from_settings(mode: str, runtime: str, image: str, env_var: str,
                          which: Any = shutil.which) -> Sandbox:
    """Dựng backend từ ba giá trị đã đọc sẵn. Core cố ý KHÔNG tự đọc `os.environ` hay file cấu hình: nguồn và tên
    biến khác nhau giữa hai công ty (xem docstring module), nên nơi gọi đọc rồi truyền vào.

    `env_var` chỉ để dựng câu lỗi đúng tên biến người vận hành phải đặt — người đọc lỗi cần biết gõ gì, và tên đó
    là của công ty gọi (`COMPANY_SANDBOX`), core không tự đoán.

    `auto` và `container` đều cần runtime; thiếu binary → `SandboxError`.
    Chỉ `subprocess` khai tường minh mới chạy không cô lập file."""
    if mode == "subprocess":
        return SubprocessSandbox()
    if mode == "container":
        if not which(runtime):
            raise SandboxError(f"{env_var}=container nhưng không tìm thấy `{runtime}` trên PATH; "
                               f"cài runtime hoặc đặt {env_var}=subprocess (không tự tụt hạng bảo vệ)")
        return ContainerSandbox(runtime, image)
    if mode != "auto":
        raise SandboxError(f"chế độ sandbox không hợp lệ: {mode!r} (auto | container | subprocess)")
    if not which(runtime):
        raise SandboxError(f"{env_var}=auto nhưng không tìm thấy `{runtime}` trên PATH; "
                           f"cài runtime hoặc đặt {env_var}=subprocess (gate không chống được mã khách)")
    return ContainerSandbox(runtime, image)
