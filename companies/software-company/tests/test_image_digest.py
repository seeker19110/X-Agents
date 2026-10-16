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


PIN = "@sha256:" + "a" * 64


def test_bang_tool_co_image_digest_khi_repo_co_image_ke_ca_da_ghim(tmp_path):
    """ADR-0055 bổ sung (hub 2026-10-13, CR-DDCSV-SEC-001 / DDCSV-22): nâng image ĐÃ ghim lên bản vá mới cần digest
    mới — trước đây repo ghim hết thì không có lệnh, builder chỉ còn đường sửa digest bằng tay (cấm) hay dừng."""
    root = _repo(tmp_path, Dockerfile="FROM python:3.12-slim\n")
    spec = next(t for t in WorkspaceTools(root, sandbox=SpySandbox()).toolbox().specs() if t.name == "run")
    assert "image_digest" in spec.parameters["properties"]["command"]["enum"] and "image_digest" in spec.description
    root2 = _repo(tmp_path / "b", Dockerfile=f"FROM python:3.12-slim{PIN}\n")
    spec2 = next(t for t in WorkspaceTools(root2, sandbox=SpySandbox()).toolbox().specs() if t.name == "run")
    assert "image_digest" in spec2.parameters["properties"]["command"]["enum"], "đã ghim vẫn có lệnh để nâng bản"
    root3 = _repo(tmp_path / "c", **{"pyproject.toml": "[project]\nname='x'\nversion='0'\n"})
    assert "image_digest" not in WorkspaceTools(root3, sandbox=SpySandbox()).COMMANDS, (
        "không có image thì không có lệnh"
    )
    assert "image_digest" not in WorkspaceTools(root, sandbox=SpySandbox(), allow_run=False).COMMANDS


def test_argv_hoi_digest_hien_tai_cua_tag_ke_ca_ref_da_ghim(tmp_path):
    root = _repo(
        tmp_path,
        Dockerfile=f"FROM python:3.12.11-slim{PIN}\nFROM postgres:16\n",
        **{"docker-compose.yml": f"services:\n  db:\n    image: postgres:16{PIN}\n  x:\n    image: redis{PIN}\n"},
    )
    got = argv(root)
    assert got is not None and got[3:] == ["python:3.12.11-slim", "postgres:16", "redis"], (
        "bỏ @sha256 để hỏi digest HIỆN TẠI của tag; trùng thì một; không có tag thì hỏi `latest` như docker pull"
    )


def test_run_image_digest_doc_lai_repo_luc_chay_khong_dung_bang_luc_dung_toolbox(tmp_path):
    """Builder sửa tag trong Dockerfile giữa lượt rồi gọi `image_digest`: argv phải theo file HIỆN TẠI."""
    root = _repo(tmp_path, Dockerfile=f"FROM python:3.12.11-slim{PIN}\n")
    spy = SpySandbox(name="container:x", stdout="python:3.12.12-slim@sha256:bb\n")
    tools = WorkspaceTools(root, sandbox=spy)
    (root / "Dockerfile").write_text("FROM python:3.12.12-slim\n", encoding="utf-8")
    tools.run("image_digest")
    assert spy.specs[-1].argv[3:] == ["python:3.12.12-slim"]
    (root / "Dockerfile").unlink()
    with pytest.raises(ToolError, match="không còn image"):
        tools.run("image_digest")


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


# ---------- bổ sung 2026-10-16: Dockerfile do compose trỏ tới (`build.dockerfile`) ----------
# Hub thật (QLKH-DD-CSV, REL-105, TM-REL105-03): service `db` build từ `infra/db/Dockerfile` — hai tầng thư mục, ngoài
# `DOCKERFILES` ("Dockerfile", "*/Dockerfile"). Image nền postgres không bao giờ vào `evidence.vuln.images`, security
# chặn RC vì "image db không được quét". Tập quét phải gồm cả Dockerfile mà compose thật sự build.

COMPOSE_BUILD = """services:
  db:
    build:
      context: .
      dockerfile: infra/db/Dockerfile
  api:
    build:
      context: ./svc
      dockerfile: "docker/Dockerfile.api"  # ghi chú
  ngoai:
    build:
      context: ..
      dockerfile: ../thoat/Dockerfile
"""
PG = "postgres:16.10-bookworm@sha256:38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74"


def test_references_doc_ca_dockerfile_do_compose_build_tro_toi(tmp_path):
    root = _repo(
        tmp_path,
        **{
            "docker-compose.yml": COMPOSE_BUILD,
            "infra/db/Dockerfile": f"FROM {PG}\n",
            "svc/docker/Dockerfile.api": "FROM node:22-alpine\n",
        },
    )
    (tmp_path / "thoat").mkdir()
    (tmp_path / "thoat" / "Dockerfile").write_text("FROM evil:1\n", encoding="utf-8")
    assert references(root, pinned=True) == [PG, "node:22-alpine"], "Dockerfile compose build, context tương đối"
    assert references(root) == ["node:22-alpine"], "đã ghim thì không cần digest; đường thoát ra ngoài repo bị bỏ"


# ---------- bổ sung 2026-10-16 (2): image nền của image ĐÃ DỰNG đang chạy không phải bằng chứng về nó ----------
# Hub thật (QLKH-DD-CSV REL-107): sau #537 bằng chứng có thêm base `postgres:16.15-trixie@ca0bd484` của
# `infra/db/Dockerfile` (25 CRITICAL/HIGH có bản sửa). Dockerfile cố ý ghim base đó rồi `apt-get upgrade` và gỡ `gosu`
# (ADR-DD-15); image db ĐANG CHẠY có 0 CVE có bản sửa. `reviewer:tu-dong` từ chối vì "base còn CVE có bản sửa", hub
# lập kế hoạch đổi base, đi ngược quyết định kiến trúc của chủ dự án. Đúng như ADR-0056 bổ sung 2026-10-14: image dẫn
# xuất không có image nền nào nói đúng về nó; image đã dựng đang chạy mới là bằng chứng.

COMPOSE_HAI = """services:
  db:
    build:
      context: .
      dockerfile: infra/db/Dockerfile
  migrate:
    build:
      context: .
      dockerfile: infra/db/Dockerfile
  app:
    build: .
  cache:
    image: redis:7.4-alpine
volumes:
  pgdata: {}
"""


def test_scan_refs_bo_image_nen_cua_dockerfile_ma_image_da_dung_dang_chay(tmp_path):
    from company.image_digest import scan_refs

    root = _repo(
        tmp_path,
        **{
            "docker-compose.yml": COMPOSE_HAI,
            "infra/db/Dockerfile": f"FROM {PG}\n",
            "Dockerfile": "FROM python:3.12-slim\n",
        },
    )
    assert scan_refs(root, set()) == references(root, pinned=True), "chưa deploy: image nền là bằng chứng duy nhất"
    assert scan_refs(root, {"db"}) == ["python:3.12-slim", "redis:7.4-alpine"], "migrate cùng Dockerfile với db"
    assert scan_refs(root, {"db", "app"}) == ["redis:7.4-alpine"], "`build: .` = Dockerfile ở context"
    (root / "api").mkdir()
    (root / "api" / "Dockerfile").write_text(f"FROM {PG}\n", encoding="utf-8")
    assert PG in scan_refs(root, {"db", "app"}), "base còn được Dockerfile khác (chưa chạy) dùng thì vẫn quét"
