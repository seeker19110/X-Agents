"""S2 / ADR gốc 0010: workload chỉ ở bridge internal, ra HTTP(S) qua ACL Squid.

Không mount socket/config host vào workload; proxy/relay là sidecar tin cậy có route ngoài, workload chỉ ở mạng internal.
Session sở hữu network/sidecar, close idempotent để run/spawn dọn cả đường lỗi.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Protocol

from .sandbox import SandboxError

PROXY_IMAGE = 'ubuntu/squid:6.6-24.04_beta'
_RELAY = """import select, socket, socketserver, sys
class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5) as upstream:
            pair = [self.request, upstream]
            while True:
                ready = select.select(pair, [], [], 30)[0]
                if not ready: return
                for source in ready:
                    data = source.recv(65536)
                    if not data: return
                    pair[1 if source is self.request else 0].sendall(data)
socketserver.ThreadingTCPServer(('0.0.0.0', int(sys.argv[2])), Relay).serve_forever()
"""
_HOST = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$')


def squid_config(domains: tuple[str, ...]) -> str:
    """Tên chính xác, không IP/reverse DNS, wildcard hoặc chỉ thị ACL do nơi gọi chèn."""
    if any(not _HOST.fullmatch(d) for d in domains):
        raise SandboxError('allowed_domains chỉ nhận hostname chính xác')
    return '\n'.join([
        'http_port 3128', 'pid_filename /tmp/xagents-squid.pid',
        'cache_log /tmp/xagents-squid.log', 'access_log none', 'cache_store_log none',
        'cache deny all', 'visible_hostname xagents-egress',
        'acl safe port 80 443', 'acl tls port 443', 'acl CONNECT method CONNECT',
        'acl private dst 0.0.0.0/8 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 ::1/128 fc00::/7 fe80::/10',
        'http_access deny !safe', 'http_access deny CONNECT !tls', 'http_access deny private',
        'acl allowed dstdomain -n ' + ' '.join(domains),
        'http_access allow allowed', 'http_access deny all', '',
    ])


class EgressSession(Protocol):
    network: str
    env: dict[str, str]
    def close(self) -> None: ...


class EgressProxy(Protocol):
    def open(self, name: str, domains: tuple[str, ...], port: int | None = None) -> EgressSession: ...


@dataclass
class _Session:
    runtime: str
    network: str
    proxy: str
    runner: Any
    env: dict[str, str] = field(default_factory=dict)
    closed: bool = False
    relay: str = ""

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        commands = ([[self.runtime, 'rm', '-f', self.proxy]] if self.proxy else [])
        if self.relay: commands.append([self.runtime, 'rm', '-f', self.relay])
        commands.append([self.runtime, 'network', 'rm', self.network])
        for argv in commands:
            try:
                self.runner(argv, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                pass


class DockerSquidProxy:
    """Image được người vận hành cài trước; runtime không tự pull khi chạy mã khách."""

    def __init__(self, runtime: str, image: str = PROXY_IMAGE, runner: Any = subprocess.run):
        self.runtime, self.image, self.runner = runtime, image, runner

    def _command(self, *args: str, input: str | None = None) -> None:
        try:
            r = self.runner([self.runtime, *args], input=input, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            raise SandboxError(f'egress: {e}') from e
        if r.returncode:
            raise SandboxError(f'egress: {(r.stderr or r.stdout or "runtime failed")[-600:]}')

    def open(self, name: str, domains: tuple[str, ...], port: int | None = None) -> EgressSession:
        config = squid_config(domains) if domains else ''
        session = _Session(self.runtime, name + '-net', name + '-proxy' if domains else '', self.runner)
        try:
            self._command('network', 'create', '--internal', session.network)
            if port is not None:
                session.relay = name + '-relay'
                self._command('run', '-d', '--pull=never', '--name', session.relay,
                              '--network', 'bridge', '-p', f'127.0.0.1:{port}:{port}',
                              '--pids-limit', '128', '--memory', '128m', '--entrypoint', 'python',
                              'python:3.12-slim', '-c', _RELAY, name, str(port))
                self._command('network', 'connect', session.network, session.relay)
            if domains:
                self._command('run', '-d', '--pull=never', '--name', session.proxy,
                              '--network', session.network, '--pids-limit', '128', '--memory', '256m',
                              '--entrypoint', 'sh', self.image, '-c', 'sleep infinity')
                self._command('network', 'connect', 'bridge', session.proxy)
                self._command('exec', '-i', session.proxy, 'sh', '-c',
                              'cat > /tmp/xagents-squid.conf && squid -f /tmp/xagents-squid.conf -k parse '
                              '&& squid -f /tmp/xagents-squid.conf', input=config)
                url = f'http://{session.proxy}:3128'
                session.env = {k: url for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')}
                session.env.update(NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1',
                                   ALL_PROXY='', all_proxy='')
            return session
        except BaseException:
            session.close()
            raise
