"""S2: ACL có hiệu lực và tài nguyên mạng luôn được dọn (ADR gốc 0010)."""
import subprocess

import pytest

from xagents_core.egress import DockerSquidProxy, squid_config
from xagents_core.sandbox import SandboxError


def test_s2_acl_chi_hostname_chinh_xac_va_chan_dich_noi_bo():
    config = squid_config(('pypi.org', 'files.pythonhosted.org'))
    assert 'dstdomain -n pypi.org files.pythonhosted.org' in config
    assert 'http_access deny private' in config
    assert config.index('http_access deny private') < config.index('http_access allow allowed')
    assert 'http_access deny all' in config and 'port 80 443' in config


@pytest.mark.parametrize('domain', ['*.pypi.org', '.pypi.org', 'https://pypi.org', '127.0.0.1',
                                    'pypi.org\nhttp_access allow all', '', '-x', 'localhost'])
def test_s2_acl_tu_choi_ip_url_wildcard_va_config_injection(domain):
    with pytest.raises(SandboxError, match='hostname'):
        squid_config((domain,))


class Runner:
    def __init__(self, fail=''):
        self.calls = []
        self.fail = fail

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 1 if self.fail and self.fail in argv else 0, '', 'bad')


def test_s2_proxy_session_tao_mang_internal_acl_va_don_idempotent():
    run = Runner()
    session = DockerSquidProxy('docker', runner=run).open('check', ('pypi.org',))
    assert session.network == 'check-net'
    assert '--internal' in run.calls[0][0]
    assert any(c[0][:3] == ['docker', 'network', 'connect'] and 'bridge' in c[0] for c in run.calls)
    exec_call = next(c for c in run.calls if c[0][1] == 'exec')
    assert 'dstdomain -n pypi.org' in exec_call[1]['input']
    assert session.env['HTTPS_PROXY'] == 'http://check-proxy:3128'
    session.close(); n = len(run.calls); session.close()
    assert len(run.calls) == n
    assert run.calls[-2][0] == ['docker', 'rm', '-f', 'check-proxy']
    assert run.calls[-1][0] == ['docker', 'network', 'rm', 'check-net']


def test_s2_mang_loopback_khong_domains_khong_tao_proxy():
    run = Runner()
    session = DockerSquidProxy('docker', runner=run).open('check', ())
    assert session.env == {} and len(run.calls) == 1
    session.close()
    assert run.calls[-1][0] == ['docker', 'network', 'rm', 'check-net']


@pytest.mark.parametrize('fail', ['create', 'run', 'connect', 'exec'])
def test_s2_proxy_khoi_dong_loi_fail_closed_va_don(fail):
    run = Runner(fail)
    with pytest.raises(SandboxError, match='egress'):
        DockerSquidProxy('docker', runner=run).open('check', ('pypi.org',))
    assert run.calls[-1][0] == ['docker', 'network', 'rm', 'check-net']


def _require_docker():
    import shutil
    reason = None
    if not shutil.which('docker'):
        reason = 'S2 cần Docker Engine và hai image cài trước'
    else:
        for args in [['info'], ['image', 'inspect', 'python:3.12-slim'],
                     ['image', 'inspect', 'ubuntu/squid:6.6-24.04_beta']]:
            r = subprocess.run(['docker', *args], capture_output=True, timeout=30)
            if r.returncode:
                reason = 'S2 cần Engine/python/Squid image cài trước, test không tự pull'
                break
    if reason:
        pytest.skip(reason)

def test_s2_container_that_allowlist_chan_proxy_bypass_dns_va_don(tmp_path):
    import json

    from xagents_core.sandbox import ContainerSandbox, RunSpec
    _require_docker()
    before = subprocess.check_output(['docker','network','ls','--format','{{.Name}}'], text=True)
    code = '''
import json, socket, urllib.request, urllib.error
out = {}
for name, url in [('allowed', 'https://pypi.org/simple/'), ('denied', 'https://example.com/'),
                  ('private', 'http://127.0.0.1/')]:
    try:
        out[name] = urllib.request.urlopen(url, timeout=15).status
    except urllib.error.HTTPError as e:
        out[name] = e.code
    except urllib.error.URLError as e:
        out[name] = 403 if '403 Forbidden' in str(e) else 'blocked'
for name, operation in [('direct', lambda: socket.create_connection(('1.1.1.1',443),2)),
                        ('dns', lambda: socket.getaddrinfo('example.com',443))]:
    try:
        operation(); out[name] = 'escaped'
    except OSError:
        out[name] = 'blocked'
print(json.dumps(out))
'''
    r = ContainerSandbox('docker', 'python:3.12-slim').run(
        RunSpec(argv=['python', '-c', code], cwd=tmp_path, allowed_domains=('pypi.org',), timeout=60))
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {'allowed': 200, 'denied': 403, 'private': 'blocked',
                                   'direct': 'blocked', 'dns': 'blocked'}
    names = subprocess.check_output(['docker','network','ls','--format','{{.Name}}'],text=True)
    assert set(names.splitlines()) == set(before.splitlines())


def test_s2_smoke_port_publish_van_hoat_dong_khi_khong_cho_egress(tmp_path):
    import socket
    import time
    import urllib.error
    import urllib.request

    from xagents_core.sandbox import ContainerSandbox, RunSpec
    _require_docker()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    handle = ContainerSandbox('docker', 'python:3.12-slim').spawn(
        RunSpec(argv=['python', '-m', 'http.server', str(port), '--bind', '0.0.0.0'],
                cwd=tmp_path, network=True, port=port))
    status = None
    try:
        for _ in range(50):
            try:
                status = urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1).status
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        assert status == 200, handle.stderr_tail(1000)
    finally:
        handle.kill()


def test_s2_port_publish_o_relay_tin_cay_workload_van_internal():
    run = Runner()
    session = DockerSquidProxy('docker', runner=run).open('check', (), port=8200)
    relay = next(c[0] for c in run.calls if c[0][1] == 'run')
    assert 'check-relay' in relay and '127.0.0.1:8200:8200' in relay
    assert relay[relay.index('--network')+1] == 'bridge'
    assert any(c[0] == ['docker','network','connect','check-net','check-relay'] for c in run.calls)
    session.close()
    assert run.calls[-2][0] == ['docker','rm','-f','check-relay']
    assert run.calls[-1][0] == ['docker','network','rm','check-net']


@pytest.mark.parametrize('failure', [OSError('runtime missing'), subprocess.TimeoutExpired('docker',30)])
def test_s2_runtime_exception_fail_closed_cleanup_khong_che_loi(failure):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        raise failure
    with pytest.raises(SandboxError, match='egress'):
        DockerSquidProxy('docker', runner=run).open('check', ('pypi.org',))
    assert calls[-1] == ['docker','network','rm','check-net']
