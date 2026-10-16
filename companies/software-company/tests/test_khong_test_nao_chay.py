"""Cổng không được xanh (hay "đỏ đúng TDD") khi lệnh test không chạy test nào — bài học REL-025 QLKH (389 test xanh
mà sản phẩm không chạy) và ADR-0011 của X-Templates. Exit code một mình không phải bằng chứng: `"test": "true"` xanh,
pytest không thu được test nào thoát 5 nên trông như đỏ đúng TDD, `go test` không có file test vẫn thoát 0."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.runner import AgentRunner
from company.stacks import detect, no_tests_ran
from company.workspace import NO_TESTS_MARK, TicketWorkspace
from test_orchestrator import _inp
from test_test_author import DIAG, TEST_FILE, _task, _ts
from test_tools_and_agentic import _first_turn, _tc


@pytest.mark.parametrize(("output", "expected"), [
    ("\nno tests ran in 0.01s\n", True),  # pytest, exit 5
    ("..\n2 passed in 0.10s\n", False),
    ("?   \tkhach/a\t[no test files]\n?   \tkhach/b\t[no test files]\n", True),  # go test, exit 0
    ("?   \tkhach/a\t[no test files]\nok  \tkhach/b\t0.01s\n", False),
    ("running 0 tests\n\ntest result: ok. 0 passed\n", True),  # cargo test, exit 0
    ("running 0 tests\nrunning 3 tests\ntest result: ok. 3 passed\n", False),
    ("No tests found, exiting with code 1\n", True),  # jest
    ("No test files found, exiting with code 1\n", True),  # vitest
    ("\n  0 passing (1ms)\n", True),  # mocha
    ("Tests:       4 passed, 4 total\n", False),
    ("", False),  # không có output thì không đoán — exit code quyết như cũ
])
def test_nhan_ra_lenh_test_khong_chay_test_nao(output: str, expected: bool) -> None:
    assert no_tests_ran(output) is expected


@pytest.mark.parametrize("script", ["true", ":", "exit 0", "echo ok", "  echo \"chưa có test\"  "])
def test_script_npm_khong_kiem_gi_thi_coi_nhu_khong_co_lenh(tmp_path: Path, script: str) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": script, "lint": script}}), encoding="utf-8")
    st = detect(tmp_path)
    assert (st.name, st.test, st.lint) == ("node", None, None)


@pytest.mark.parametrize("script", ["vitest run", "jest --ci", "echo \"Error: no test specified\" && exit 1"])
def test_script_npm_that_van_chay(tmp_path: Path, script: str) -> None:
    """Mặc định của `npm init` đỏ thật (exit 1) — chạy để lộ ra, không giấu thành "không có lệnh"."""
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": script}}), encoding="utf-8")
    assert detect(tmp_path).test == ["npm", "test", "--", "--watch=false"]


def _repo_khong_test(path: Path) -> Path:
    path.mkdir()
    def git(*a: str) -> None: subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (path / "pyproject.toml").write_text('[project]\nname = "khach"\nversion = "0.1.0"\n', encoding="utf-8")
    (path / "mod.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "init")
    return path


def test_workspace_khong_thu_duoc_test_nao_thi_do_va_noi_thang(tmp_path: Path) -> None:
    ws = TicketWorkspace(_repo_khong_test(tmp_path / "repo"), "T1", base="main")
    ws.create()
    r = ws.test()
    assert r.ok is False and r.ran is False
    assert r.output.startswith(NO_TESTS_MARK)
    checks = ws.run_checks()
    assert checks["tests"] is False and checks["test_output"].startswith(NO_TESTS_MARK)


def test_test_author_khong_thu_duoc_test_nao_khong_phai_do_dung_tdd(tmp_path: Path) -> None:
    """File test không có hàm test nào → pytest thoát 5. Trước đây đi thành `red` + `tests_red_as_expected`."""
    ws = TicketWorkspace(_repo_khong_test(tmp_path / "repo"), "T1", base="main")
    th = lambda m, t: [_tc("write_file", path=TEST_FILE, content="# sẽ viết sau\n")] if _first_turn(m) else []  # noqa: E731
    bus = InMemoryBus()
    _, status = AgentRunner(bus, FakeClient(handler=lambda s, u: _ts(_inp(u)), tool_handler=th)).author_tests(
        "qa", _task(), ws)
    assert status == "unknown"
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log") if e.payload["action"] not in DIAG]
    assert acts[-1] == "tests_not_collected"


def test_output_dai_van_giu_dau_o_dau_va_trong_tran(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from company.workspace import CheckResult
    ws = TicketWorkspace(_repo_khong_test(tmp_path / "repo"), "T1", base="main")
    ws.create()
    monkeypatch.setattr(ws, "_run", lambda *a, **k: CheckResult(ok=False, output="x" * 3990 + "\nno tests ran in 0s"))
    r = ws.test()
    assert r.output.startswith(NO_TESTS_MARK) and len(r.output) <= 4000 and r.output.endswith("no tests ran in 0s")
