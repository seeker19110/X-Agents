"""ADR-0055: lệnh `image_digest` cho builder — lấy digest manifest của image trong Dockerfile/compose từ Docker Hub qua
egress, chỉ IN ra, builder tự ghim `@sha256:` vào file.

Đo hub thật 2026-10-12 (QLKH-DD-CSV/DDCSV-20, ticket compose): job CI `image-pin` của repo khách đòi mọi `FROM` có
`@sha256:`; builder không có docker, không có mạng tới registry → security rồi qa chặn hai lượt liên tiếp cùng một lý do,
builder đúng luật không đoán digest. Cùng họ với `lock` (ADR-0054): việc cần mạng thì code mở đúng domain, model chỉ
chọn tên lệnh.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from company.image_digest import DOMAINS, SCRIPT, argv, references
from company.tools import ToolError, WorkspaceTools
from test_sandbox_noi_vao_cong_ty import SpySandbox

DOCKERFILE = """# syntax=docker/dockerfile:1
ARG BASE=python:3.12-slim
FROM --platform=$BUILDPLATFORM python:3.12.11-slim-bookworm AS build
RUN echo
FROM build AS test
FROM ${BASE}
FROM scratch
FROM ghcr.io/org/tool:1.2 AS tool
FROM postgres:16.10-bookworm@sha256:38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74
from alpine:3.20
FROM --platform=linux/amd64
"""
COMPOSE = """services:
  db:
    image: postgres:16.10-bookworm
  migrate:
    image: "postgres:16.10-bookworm"
  app:
    build: .
    image: ${APP_IMAGE:-qlkh:dev}
  cache:
    image: 'redis:7.4-alpine' # cục bộ
"""


def _repo(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "khach"
    root.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


# ---------- tham chiếu image do code đọc từ repo khách ----------


def test_references_doc_from_va_image_bo_alias_arg_scratch_da_ghim(tmp_path):
    root = _repo(
        tmp_path, Dockerfile=DOCKERFILE, **{"docker-compose.yml": COMPOSE, "api/Dockerfile": "FROM node:22-alpine\n"}
    )
    assert references(root) == [
        "python:3.12.11-slim-bookworm",
        "ghcr.io/org/tool:1.2",
        "alpine:3.20",
        "node:22-alpine",
        "postgres:16.10-bookworm",
        "redis:7.4-alpine",
    ], "alias stage, ${ARG}, scratch, đã có @sha256, image build tại chỗ: không phải thứ cần digest; trùng thì một"


def test_references_pinned_giu_ca_image_da_ghim_cho_quet_lo_hong(tmp_path):
    """ADR-0056: trivy image quét MỌI image của RC, kể cả đã ghim — `pinned=True`; mặc định vẫn chỉ image cần ghim."""
    root = _repo(tmp_path, Dockerfile=DOCKERFILE, **{"docker-compose.yml": COMPOSE})
    pinned = references(root, pinned=True)
    assert "postgres:16.10-bookworm@sha256:38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74" in pinned
    assert pinned[:2] == ["python:3.12.11-slim-bookworm", "ghcr.io/org/tool:1.2"] and "scratch" not in pinned
    assert "${BASE}" not in pinned and "build" not in pinned and len(pinned) == len(references(root)) + 1


def test_references_khong_co_dockerfile_hay_compose_thi_rong(tmp_path):
    root = _repo(tmp_path, **{"pyproject.toml": "[project]\nname='x'\nversion='0'\n"})
    assert references(root) == [] and argv(root) is None
    (root / "Dockerfile").write_bytes(b"FROM \xff\xfe\n")
    assert references(root) == [], "file không đọc được là không có tham chiếu, không ném"


def test_argv_la_python_cua_sandbox_chay_script_stdlib_voi_tung_ref(tmp_path):
    root = _repo(tmp_path, Dockerfile="FROM python:3.12-slim\n")
    got = argv(root)
    assert (
        got is not None and got[:2] == [sys.executable, "-c"] and got[2] == SCRIPT and got[3:] == ["python:3.12-slim"]
    )
    assert "import" in SCRIPT and "urllib" in SCRIPT and "subprocess" not in SCRIPT, "chỉ stdlib, không gọi docker"


# ---------- tool `run image_digest`: qua sandbox, mạng Docker Hub chỉ ở chế độ container, không nhận paths ----------


def test_run_image_digest_di_qua_sandbox_voi_domain_docker_hub_o_che_do_container(tmp_path):
    root = _repo(tmp_path, Dockerfile="FROM python:3.12-slim\n")
    spy = SpySandbox(name="container:xagents-qlkh:py3.12", stdout="python:3.12-slim@sha256:ab\n")
    out = WorkspaceTools(root, sandbox=spy).run("image_digest")
    assert out.startswith("exit=0") and "@sha256:ab" in out
    spec = spy.specs[-1]
    assert spec.argv == [sys.executable, "-c", SCRIPT, "python:3.12-slim"] and spec.cwd == root.resolve()
    assert spec.allowed_domains == DOMAINS == ("auth.docker.io", "registry-1.docker.io")
    assert "ANTHROPIC_API_KEY" not in spec.env


def test_run_image_digest_che_do_subprocess_khong_khai_domain(tmp_path):
    root = _repo(tmp_path, Dockerfile="FROM python:3.12-slim\n")
    spy = SpySandbox(name="subprocess")
    WorkspaceTools(root, sandbox=spy).run("image_digest")
    assert spy.specs[-1].allowed_domains == ()


def test_run_image_digest_khong_nhan_paths(tmp_path):
    root = _repo(tmp_path, Dockerfile="FROM python:3.12-slim\n")
    with pytest.raises(ToolError, match="paths"):
        WorkspaceTools(root, sandbox=SpySandbox()).run("image_digest", paths=["Dockerfile"])


def test_bang_tool_chi_co_image_digest_khi_repo_co_image_can_ghim(tmp_path):
    root = _repo(tmp_path, Dockerfile="FROM python:3.12-slim\n")
    spec = next(t for t in WorkspaceTools(root, sandbox=SpySandbox()).toolbox().specs() if t.name == "run")
    assert "image_digest" in spec.parameters["properties"]["command"]["enum"] and "image_digest" in spec.description
    root2 = _repo(tmp_path / "b", Dockerfile="FROM python:3.12-slim@sha256:aa\n")
    spec2 = next(t for t in WorkspaceTools(root2, sandbox=SpySandbox()).toolbox().specs() if t.name == "run")
    assert "image_digest" not in spec2.parameters["properties"]["command"]["enum"], "đã ghim hết thì không có lệnh"
    assert "image_digest" not in WorkspaceTools(root, sandbox=SpySandbox(), allow_run=False).COMMANDS


# ---------- script chạy trong sandbox: Docker Hub token + HEAD manifest; registry khác và lỗi mạng nói rõ ----------


class _Resp:
    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None):
        self._body, self.headers = body, headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run_script(monkeypatch, refs: list[str], urlopen) -> tuple[int, str]:
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sys, "argv", ["-c", *refs])
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    try:
        exec(compile(SCRIPT, "<image_digest>", "exec"), {"__name__": "__main__"})
    except SystemExit as e:
        return int(e.code or 0), out.getvalue()
    return 0, out.getvalue()


def test_script_lay_token_roi_head_manifest_in_ref_at_digest(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    def urlopen(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        method = "GET" if isinstance(req, str) else req.get_method()
        calls.append((method, url, "" if isinstance(req, str) else req.get_header("Accept", "")))
        if "auth.docker.io/token" in url:
            return _Resp(b'{"token": "t0k"}')
        assert req.get_header("Authorization") == "Bearer t0k"
        return _Resp(headers={"Docker-Content-Digest": "sha256:" + "a" * 64})

    code, out = _run_script(monkeypatch, ["python:3.12.11-slim-bookworm", "org/app"], urlopen)
    assert code == 0 and out.splitlines() == [
        "python:3.12.11-slim-bookworm@sha256:" + "a" * 64,
        "org/app@sha256:" + "a" * 64,
    ]
    assert calls[0] == (
        "GET",
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/python:pull",
        "",
    )
    assert (
        calls[1][0] == "HEAD"
        and calls[1][1] == "https://registry-1.docker.io/v2/library/python/manifests/3.12.11-slim-bookworm"
    )
    assert "manifest.list.v2+json" in calls[1][2] and "oci.image.index.v1+json" in calls[1][2], (
        "digest của manifest LIST (đa kiến trúc), đúng thứ docker pull ghi vào RepoDigests"
    )
    assert calls[3][1].endswith("/v2/org/app/manifests/latest"), "không có tag = latest; tên có '/' không thêm library/"


def test_script_registry_ngoai_docker_hub_va_loi_mang_thi_noi_ro_va_exit_1(monkeypatch):
    def urlopen(req, timeout=0):
        raise OSError("timed out")

    code, out = _run_script(monkeypatch, ["ghcr.io/org/tool:1.2", "localhost:5000/x:1", "python:3.12-slim"], urlopen)
    lines = out.splitlines()
    assert code == 1 and len(lines) == 3
    assert lines[0].startswith("ghcr.io/org/tool:1.2 LOI:") and "docker.io" in lines[0]
    assert lines[1].startswith("localhost:5000/x:1 LOI:")
    assert lines[2] == "python:3.12-slim LOI: timed out"
