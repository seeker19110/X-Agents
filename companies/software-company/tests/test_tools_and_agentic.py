"""ADR-0010: tool có ranh giới tin cậy, vòng lặp tool-use trung lập provider, PR mang bằng chứng do code điền,
eval ghi/phát lại, vòng học hiệu chỉnh ước lượng. Không gọi mạng: client giả + server HTTP cục bộ."""
from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

import company.evals as evals_mod
from company.bus import InMemoryBus
from company.evals import RecordingClient, ReplayClient, recording_path, run_eval, stale_recordings
from company.evals import main as evals_main
from company.events import Envelope
from company.llm import (
    AnthropicClient,
    Completion,
    FakeClient,
    LLMConfig,
    LLMError,
    OpenAICompatClient,
    Refused,
    TransientError,
)
from company.orchestrator import Orchestrator, _cycle
from company.runner import AgentRunner, RunnerError
from company.tools import ToolBox, ToolCall, ToolError, ToolSpec, WorkspaceTools, _clean_env
from company.workspace import TicketWorkspace
from test_orchestrator import T1, T2, _agent_of, _drive_to_plan, _inp, _pub, handler

# `token_estimate` (p3.2a) là số đo CHẨN ĐOÁN, phát ở mọi bước agent: sai số giữa ước lượng của `fit` và
# token thật trong `usage`. Các khẳng định dưới đây đo TRÌNH TỰ SỰ VIỆC của luồng, nên lọc nó ra —
# chính nó được đo riêng ở `test_adr0012.py::test_runner_audits_token_estimate_sau_moi_buoc`.
DIAG = {"token_estimate"}


def _init_repo(path: Path) -> Path:
    path.mkdir()
    def git(*a): subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    # dấu hiệu stack python: run_checks chọn ruff+pytest theo đây (ADR-0013)
    (path / "pyproject.toml").write_text('[project]\nname = "khach"\nversion = "0.1.0"\n', encoding="utf-8")
    (path / "mod.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (path / "test_mod.py").write_text("from mod import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    (path / ".env").write_text("API_KEY=sk_live_secret\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "init")
    return path


def _task_env(tid="T1", **extra) -> Envelope:
    return Envelope(topic="tasks", key=tid, actor="delivery-lead", payload={**T1, "ticket_id": tid, **extra})


def _tc(name, **args) -> ToolCall:
    return ToolCall(id=f"c-{name}", name=name, args=args)


def _first_turn(msgs) -> bool:
    return not any(m["role"] == "assistant" for m in msgs)


# ---------- ranh giới tool ----------

def test_tools_refuse_paths_outside_worktree_and_secrets(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    for bad in ("../mod.py", "../../etc/passwd", "/etc/passwd", "C:/Windows/win.ini", ".git/config", ".env", "sub/../../x"):
        out = tb.call(_tc("read_file", path=bad))
        assert out.startswith("lỗi"), (bad, out)
    assert tb.call(_tc("write_file", path=".git/hooks/pre-commit", content="x")).startswith("lỗi")
    # `.env.development`/`.env.example` là file mặc định công khai của repo — phải ghi/đọc được; `.env*` khác vẫn chặn
    assert not tb.call(_tc("write_file", path="web/.env.development", content="VITE_API_BASE_URL=http://127.0.0.1:8080/v1\n")).startswith("lỗi")
    assert "VITE_API_BASE_URL" in tb.call(_tc("read_file", path="web/.env.development"))
    assert not tb.call(_tc("write_file", path=".env.example", content="API_KEY=\n")).startswith("lỗi")
    for bad in (".env.local", ".env.production", "web/.env", ".aws/.env.development"):
        assert tb.call(_tc("write_file", path=bad, content="x")).startswith("lỗi"), bad
    assert tb.call(_tc("write_file", path="keys/id_rsa", content="x")).startswith("lỗi")
    assert not (ws.path / ".git" / "hooks" / "pre-commit").exists()
    # tìm kiếm không lộ file bí mật dù nội dung khớp
    assert "sk_live" not in tb.call(_tc("search", pattern="sk_live", glob="**/*"))


def test_tools_allowlist_and_argument_validation(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    assert "không trong allowlist" in tb.call(_tc("run", command="rm -rf /"))
    assert "không trong allowlist" in tb.call(_tc("run", command="sh"))
    assert tb.call(_tc("read_file", path="mod.py", shell="ls")).startswith("lỗi tham số")
    assert tb.call(_tc("read_file")).startswith("lỗi tham số")
    with pytest.raises(ToolError, match="không tồn tại"):
        tb.call(_tc("bash", command="ls"))
    assert tb.calls[-1]["name"] == "read_file" and tb.summary() == {"run": 2, "read_file": 2}


def test_toolbox_call_bat_typeerror_valueerror_thanh_loi_tham_so():
    """Hàm tool ném TypeError/ValueError (không phải ToolError) vẫn phải quay về model như lỗi tham số, không sập."""
    tb = ToolBox()
    tb.add(ToolSpec("chia", "chia hai số", {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}),
           lambda a: 1 / a if a else (_ for _ in ()).throw(ValueError("a không được là 0")))
    out = tb.call(_tc("chia", a=0))
    assert out.startswith("lỗi tham số") and "không được là 0" in out


def test_write_file_tu_choi_duoi_nhi_phan(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    assert tb.call(_tc("write_file", path="logo.png", content="x")).startswith("lỗi")
    assert not (ws.path / "logo.png").exists()


def test_search_bao_loi_khi_regex_sai(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    out = tb.call(_tc("search", pattern="(", glob="**/*.py"))
    assert out.startswith("lỗi") and "regex sai" in out


def test_search_bo_qua_file_khong_doc_duoc(tmp_path, monkeypatch):
    """`_walk` liệt kê file OK nhưng `read_text` ném OSError (vd. quyền, race xoá file) — `search` bỏ qua, không sập."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    from pathlib import Path as _Path
    orig = _Path.read_text

    def boom(self, *a, **kw):
        if self.name == "mod.py":
            raise OSError("không đọc được")
        return orig(self, *a, **kw)

    monkeypatch.setattr(_Path, "read_text", boom)
    out = tb.call(_tc("search", pattern="def", glob="**/*.py"))
    assert not any(line.startswith("mod.py:") for line in out.splitlines()) and "test_mod.py:" in out


def test_run_het_gio_bao_loi_ro(tmp_path, monkeypatch):
    import subprocess as sp

    from company.sandbox import SubprocessSandbox

    def boom(*a, **kw):
        raise sp.TimeoutExpired(cmd="lint", timeout=1)

    # K2.4: `subprocess.run` không còn nằm trong `tools.py` — tiêm runner giả vào `SubprocessSandbox` thay vì
    # monkeypatch module toàn cục (từ đây monkeypatch cũng không còn ăn: `sandbox.py` giữ tham chiếu riêng).
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws, timeout=1, sandbox=SubprocessSandbox(runner=boom)).toolbox()
    out = tb.call(_tc("run", command="lint"))
    assert out.startswith("lỗi") and "quá 1s" in out


def test_run_tu_choi_paths_la_co_thay_vi_duong_dan(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    wt = WorkspaceTools(ws)
    with pytest.raises(ToolError, match="không nhận tuỳ chọn"):
        wt.run("lint", paths=["--exclude=x"])


def test_read_only_toolbox_has_no_write(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws, allow_write=False).toolbox()
    assert [t.name for t in tb.specs()] == ["read_file", "list_files", "search", "run"]
    with pytest.raises(ToolError):
        tb.call(_tc("write_file", path="x.py", content="1"))


def test_tools_read_write_search_list_run(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    assert tb.call(_tc("write_file", path="pkg/new.py", content="X = 1\n")).startswith("đã tạo")
    assert tb.call(_tc("read_file", path="pkg/new.py")) == "    1\tX = 1"
    assert "pkg/new.py:1: X = 1" in tb.call(_tc("search", pattern="^X"))
    files = tb.call(_tc("list_files")).splitlines()
    assert "mod.py" in files and "pkg/new.py" in files and not any(f.startswith(".git") for f in files)
    assert ".env" not in files
    assert tb.call(_tc("run", command="test")).startswith("exit=0")
    assert tb.call(_tc("run", command="lint", paths=["pkg"])).startswith("exit=0")
    tb.call(_tc("write_file", path="mod.py", content="def add(a, b):\n    return a - b\n"))
    assert tb.call(_tc("run", command="test")).startswith("exit=1")
    assert "mod.py" in tb.call(_tc("run", command="git_status"))


def test_clean_env_drops_keys(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "x"); monkeypatch.setenv("DB_PASSWORD", "y"); monkeypatch.setenv("PATH_X", "z")
    env = _clean_env()
    assert "MY_API_KEY" not in env and "DB_PASSWORD" not in env and env["PATH_X"] == "z"


def test_read_file_bao_loi_khong_co_file(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    wt = WorkspaceTools(ws)
    assert wt.read_file("khong_ton_tai.py") == "lỗi: không có file khong_ton_tai.py"


def test_read_file_tu_choi_file_nhi_phan(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    (ws.path / "logo.png").write_bytes(b"\x89PNG")
    wt = WorkspaceTools(ws)
    assert wt.read_file("logo.png") == "lỗi: file nhị phân"


def test_write_file_khi_allow_write_false_nem_toolerror(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    wt = WorkspaceTools(ws, allow_write=False)
    with pytest.raises(ToolError, match="chỉ đọc"):
        wt.write_file("x.py", "1")


def test_write_file_qua_gioi_han_byte(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    wt = WorkspaceTools(ws)
    from company.tools import MAX_WRITE
    out = wt.write_file("big.py", "x" * (MAX_WRITE + 1))
    assert out.startswith("lỗi") and "byte" in out
    assert not (ws.path / "big.py").exists()


def test_list_files_bao_loi_khong_phai_thu_muc(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    wt = WorkspaceTools(ws)
    assert wt.list_files("mod.py") == "lỗi: không có thư mục mod.py"


def test_list_files_cat_o_500(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    (ws.path / "many").mkdir()
    for i in range(510):
        (ws.path / "many" / f"f{i}.py").write_text("x = 1\n", encoding="utf-8")
    wt = WorkspaceTools(ws)
    out = wt.list_files("many")
    lines = out.splitlines()
    assert lines[-1] == "… (cắt ở 500)" and len(lines) == 501


def test_search_duyet_nhieu_dong_trong_mot_file(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    (ws.path / "multi.py").write_text("a = 1\nb = 2\ndef foo():\n    pass\ndef bar():\n    pass\n", encoding="utf-8")
    wt = WorkspaceTools(ws)
    out = wt.search(r"^def ", glob="multi.py")
    assert "multi.py:3:" in out and "multi.py:5:" in out


def test_search_cat_o_max_search_hits(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    (ws.path / "many.py").write_text("\n".join(f"x{i} = 1  # match" for i in range(80)) + "\n", encoding="utf-8")
    wt = WorkspaceTools(ws)
    out = wt.search("match", glob="many.py")
    assert out.endswith("… (cắt)")
    assert len(out.splitlines()) == 61


def test_toolbox_truncates_long_output():
    tb = ToolBox(); tb.add(ToolSpec("big", "", {"type": "object", "properties": {}}), lambda: "x" * 10_000)
    out = tb.call(_tc("big"))
    assert len(out) < 6_100 and "cắt" in out


# ---------- vòng lặp tool-use trong runner ----------

def _pr(p, **extra):
    return {"ticket_id": p["ticket_id"], "branch": "ticket/fake", "pr_ref": "#999", "summary": "đã làm",
            "local_checks": {"lint": True, "tests": True, "coverage": 0.99}, **extra}


def test_tool_loop_runs_tools_then_final_answer(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    def th(msgs, tools):
        if _first_turn(msgs): return [_tc("read_file", path="mod.py"), _tc("write_file", path="feature.py", content="F = 1\n")]
        assert msgs[-1]["role"] == "tool" and msgs[-1]["content"].startswith("đã tạo")
        return []
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=th)
    bus = InMemoryBus()
    g = AgentRunner(bus, client).generate("builder", _task_env(), "pull-requests", tools=tb)
    assert (ws.path / "feature.py").read_text(encoding="utf-8") == "F = 1\n"
    assert g.turns == 2 and g.tool_calls == {"read_file": 1, "write_file": 1} and g.tokens == 2 * 1300
    assert [c["tools"] for c in client.calls] == [["read_file", "write_file", "delete_file", "list_files", "search", "run"]] * 2
    assert "# Tool" in client.calls[0]["user"] and "run test" in client.calls[0]["user"]
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log") if e.payload["action"] not in DIAG]
    assert acts == ["tools_used", "tools_trace"], "4L-2: một audit tools_trace mỗi lượt, ngay sau tools_used"
    used = json.loads(next(e.payload["evidence"] for e in bus.replay(topic="audit-log") if e.payload["action"] == "tools_used"))
    # 4L-5: model tự chốt ở lượt 2 (không hết `max_turns`=25 mặc định) → không chạm trần
    assert used["capped"] is False and used["max_turns"] == 25
    tr = json.loads(next(e.payload["evidence"] for e in bus.replay(topic="audit-log") if e.payload["action"] == "tools_trace"))
    assert tr["mode"] == "loop" and tr["turns"] == 2
    calls = tr["calls"]
    assert [c["name"] for c in calls] == ["read_file", "write_file"]
    assert calls[0]["args"] == {"path": "mod.py"}
    # `content` là OPAQUE_ARGS: vết không bao giờ lộ nội dung khách thật, chỉ độ dài
    assert calls[1]["args"] == {"path": "feature.py", "content": "<6 ký tự>"}
    assert "F = 1" not in json.dumps(tr, ensure_ascii=False)
    assert all(isinstance(c["args_hash"], str) and len(c["args_hash"]) == 12 for c in calls)
    assert all(isinstance(c["out_hash"], str) and len(c["out_hash"]) == 12 for c in calls)
    assert all(isinstance(c["ms"], float) for c in calls)


def test_tools_trace_evidence_duoi_20k_o_25_luot_x_4_call(tmp_path):
    """Ca đo bắt buộc 4L-2: 25 lượt tool, mỗi lượt 4 call → evidence `tools_trace` MỖI LƯỢT phải < 20.000 ký tự
    (đủ nhỏ để không nuốt ngữ cảnh model / DB audit khi lặp nhiều)."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    luot = {"n": 0}

    def th(msgs, tools):
        luot["n"] += 1
        if luot["n"] > 25: return []
        return [_tc("read_file", path="mod.py"), _tc("read_file", path="test_mod.py"),
                _tc("list_files", path="."), _tc("search", pattern="def")]

    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=th)
    bus = InMemoryBus()
    AgentRunner(bus, client).generate("builder", _task_env(), "pull-requests",
                                      tools=WorkspaceTools(ws).toolbox(), max_turns=30)
    traces = [e.payload["evidence"] for e in bus.replay(topic="audit-log") if e.payload["action"] == "tools_trace"]
    assert traces, "phải có ít nhất một audit tools_trace"
    for ev in traces:
        assert len(ev) < 20_000, f"evidence tools_trace {len(ev)} ký tự, vượt trần 20k"


class _CliOnlyClient(FakeClient):
    """Mô phỏng mode `cli` (ADR-0023): CLI tự cầm tool bên trong tiến trình của nó, trả lời cuối ngay lượt 1
    với `tool_calls` rỗng — runner KHÔNG BAO GIỜ gọi qua `ToolBox` ở lượt này."""
    def complete(self, **kw: Any) -> Completion:
        return Completion(text=json.dumps(_pr({"ticket_id": "T1"}), ensure_ascii=False),
                          input_tokens=1_000, output_tokens=300, model="fake", tool_mode="cli")


def test_tools_trace_mode_cli_khong_co_vet(tmp_path):
    """4L-2 bẫy đã biết: mode `cli` không đi qua `ToolBox` của company → `tools.trace()` RỖNG. `tools_trace`
    vẫn phải được ghi (một lần/lượt như mọi mode khác), chỉ là `calls` rỗng — người đọc audit thấy `mode: cli`
    và biết đây là giới hạn của ADR-0023, không phải lỗi mất vết."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    bus = InMemoryBus()
    AgentRunner(bus, _CliOnlyClient()).generate("builder", _task_env(), "pull-requests", tools=WorkspaceTools(ws).toolbox())
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log") if e.payload["action"] not in DIAG]
    assert acts == ["tools_used", "tools_trace"]
    tr = json.loads(next(e.payload["evidence"] for e in bus.replay(topic="audit-log") if e.payload["action"] == "tools_trace"))
    assert tr["mode"] == "cli" and tr["calls"] == []


def test_tool_loop_stops_when_budget_exhausted(tmp_path):
    """Ngân sách đo OUTPUT, không đo tổng token: `budget_tokens` là ước lượng KHỐI LƯỢNG CÔNG VIỆC, còn tổng
    token phình theo số lượt tool (mỗi lượt gửi lại cả hội thoại). FakeClient sinh 1000 input + 300 output mỗi
    lượt, nên ngân sách 3000 phải chịu được 10 lượt rồi mới gãy ở lượt 11 — chứ không gãy ở lượt 3 như khi đếm
    cả input. Đo được khi chạy thật (2026-09-04): agent viết 21 file rồi bị giết ở `956637 > 90000`, công sức
    bị `workspace_reset` xoá sạch, lặp ba lần mà không lần nào ra được PR.

    Đọc XOAY VÒNG ba file khác nhau chứ không đọc mãi một file: từ 4L-3 vòng tool bị cắt ở lần lặp thứ 5 cùng
    (tool, tham số, kết quả), nên đọc mãi `mod.py` sẽ dừng vì `no_progress` trước khi chạm ngân sách — ca này
    đo hàng rào NGÂN SÁCH, phải giữ cho hàng rào kia không nổ trước."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    vong = {"n": 0}

    def _doc_xoay_vong(msgs, tools):
        vong["n"] += 1
        return [_tc("read_file", path=("mod.py", "test_mod.py", "pyproject.toml")[vong["n"] % 3])]

    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=_doc_xoay_vong)
    bus = InMemoryBus()
    with pytest.raises(RunnerError, match="vượt ngân sách"):
        AgentRunner(bus, client).generate("builder", _task_env(), "pull-requests", tools=WorkspaceTools(ws).toolbox(), budget=3_000)
    a = [e.payload for e in bus.replay(topic="audit-log")][-1]
    assert a["action"] == "budget_exhausted" and len(client.calls) == 11    # 11 * 300 output > 3000
    assert a["tokens"] == 11 * 1300, "audit vẫn ghi TỔNG token để metrics/chi phí không bị hụt"
    assert "output 3300 > 3000" in a["evidence"] and "kể cả input: 14300" in a["evidence"]


def test_van_xuoi_o_luot_cuoi_bi_ep_chot_lai_bang_json(tmp_path):
    """Agent có tool trả VĂN XUÔI ở lượt cuối thì phải bị bắt chốt lại bằng JSON, không được để runner báo
    "đầu ra không phải JSON" — thông điệp đó dẫn người đọc đi sửa schema trong khi chỉ cần xin model chốt lại.

    Vì sao agent có tool hay dính: `OpenAICompatClient` KHÔNG ép `response_format` khi request có `tools` (ép
    json_object thì model không gọi tool được nữa), nên lượt cuối không có gì buộc nó trả JSON. Đo được khi
    chạy thật 2026-09-04: `qa-debugger` (tools="ro") hỏng LẶP LẠI với "...Tôi đã thu thập đủ bằng chứng...",
    chặn ticket QLKH-001 không qua nổi review."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    luot = {"n": 0}

    def handler_van_xuoi(system, user):
        luot["n"] += 1
        if luot["n"] == 1:
            return "Tôi đã thu thập đủ bằng chứng. Bây giờ tôi sẽ tổng hợp lại."   # văn xuôi, KHÔNG phải JSON
        return _pr(_inp(user))

    client = FakeClient(handler=handler_van_xuoi, tool_handler=lambda m, t: [])
    bus = InMemoryBus()
    g = AgentRunner(bus, client).generate("builder", _task_env(), "pull-requests",
                                          tools=WorkspaceTools(ws).toolbox())
    assert luot["n"] == 2, "phải xin model chốt lại thêm một lượt, không được nhận văn xuôi"
    assert g.payloads[0]["ticket_id"] == "T1"


def test_tool_loop_max_turns_forces_final_json(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=lambda m, t: [_tc("read_file", path="mod.py")])
    bus = InMemoryBus()
    g = AgentRunner(bus, client).generate("builder", _task_env(), "pull-requests",
                                          tools=WorkspaceTools(ws).toolbox(), max_turns=2)
    assert g.turns == 3 and len(client.calls) == 3 and client.calls[-1]["tools"] == []
    last = client.calls[-1]["messages"]
    assert last[-1]["role"] == "user" and "Hết lượt tool" in last[-1]["content"]
    assert last[-2]["role"] == "tool" and "hết lượt" in last[-2]["content"]
    # 4L-5: model vẫn còn muốn gọi tool khi vòng while hết `max_turns`=2 → chạm trần
    used = json.loads(next(e.payload["evidence"] for e in bus.replay(topic="audit-log") if e.payload["action"] == "tools_used"))
    assert used["capped"] is True and used["max_turns"] == 2


def test_tool_error_is_returned_to_model_not_raised(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    seen = []
    def th(msgs, tools):
        if _first_turn(msgs): return [_tc("nope"), _tc("read_file", path="../x")]
        seen.extend(m["content"] for m in msgs if m["role"] == "tool"); return []
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=th)
    AgentRunner(InMemoryBus(), client).generate("builder", _task_env(), "pull-requests", tools=WorkspaceTools(ws).toolbox())
    assert seen[0].startswith("lỗi: tool không tồn tại") and "thoát" in seen[1]


# ---------- PR mang bằng chứng do code điền ----------

def test_generate_in_workspace_overrides_model_claims_with_git_evidence(tmp_path):
    repo = _init_repo(tmp_path / "repo"); ws = TicketWorkspace(repo, "T1", base="main")
    def th(msgs, tools):
        return [_tc("write_file", path="feature.py", content="def f():\n    return 1\n"),
                _tc("write_file", path="test_feature.py", content="from feature import f\n\n\ndef test_f():\n    assert f() == 1\n")] \
            if _first_turn(msgs) else []
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=th)
    bus = InMemoryBus()
    g = AgentRunner(bus, client).generate_in_workspace("builder", _task_env(title="thêm f"), ws, budget=50_000)
    p = g.payloads[0]
    assert p["branch"] == "ticket/T1" and p["pr_ref"] != "#999" and len(p["pr_ref"]) >= 7
    assert p["local_checks"] == {"lint": True, "tests": True, "verified_by": "workspace", "stack": "python",
                                 "sandbox": "subprocess",   # K2.5: lớp bảo vệ đã chạy lint/test đi kèm bằng chứng
                                 "lint_output": p["local_checks"]["lint_output"], "test_output": p["local_checks"]["test_output"]}
    assert "coverage" not in p["local_checks"], "model khai coverage nhưng không đo được → bỏ, không bịa"
    assert p["impact"]["files"] == ["feature.py", "test_feature.py"] and p["summary"] == "đã làm"
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline", "ticket/T1"], capture_output=True, text=True, encoding="utf-8").stdout
    assert "feat(T1): thêm f" in log and "+def f():" in ws.diff()
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log") if e.payload["action"] not in DIAG]
    assert acts == ["tools_used", "tools_trace", "local_checks"]


def test_generate_in_workspace_reports_failing_tests_truthfully(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    th = lambda m, t: [_tc("write_file", path="mod.py", content="def add(a, b):\n    return a - b\n")] if _first_turn(m) else []  # noqa: E731
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=th)
    p = AgentRunner(InMemoryBus(), client).generate_in_workspace("builder", _task_env(), ws).payloads[0]
    assert p["local_checks"]["tests"] is False and p["local_checks"]["lint"] is True, "model khai tests=true, máy nói false"


def test_generate_in_workspace_rejects_pr_without_changes(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=lambda m, t: [_tc("read_file", path="mod.py")] if _first_turn(m) else [])
    bus = InMemoryBus()
    with pytest.raises(RunnerError, match="không sửa file"):
        AgentRunner(bus, client).generate_in_workspace("builder", _task_env(), ws)
    assert [e.payload["action"] for e in bus.replay(topic="audit-log") if e.payload["action"] not in DIAG] == ["tools_used", "tools_trace", "invalid_output"]


# ---------- orchestrator với repo thật ----------

def _repo_tool_handler(msgs, tools):
    names = {t.name for t in tools}
    if "write_file" in names and _first_turn(msgs):
        tid = _inp(msgs[0]["content"])["ticket_id"]
        return [_tc("write_file", path=f"f_{tid.lower()}.py", content=f"def {tid.lower()}():\n    return 1\n")]
    if "write_file" not in names and _first_turn(msgs):
        return [_tc("run", command="test")]  # QA tự chạy test bằng tool chỉ đọc
    return []


def test_orchestrator_with_repo_produces_verified_prs_and_reviewers_read_diff(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=_repo_tool_handler)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    assert orch.lead.state["T1"] == "merged" and orch.lead.state["T2"] == "merged" and orch.stats["errors"] == 0
    prs = {e.key: e.payload for e in bus.replay(topic="pull-requests")}
    assert set(prs) == {"T1", "T2"}
    for tid, p in prs.items():
        assert p["local_checks"]["verified_by"] == "workspace" and p["local_checks"]["tests"] is True
        assert p["branch"] == f"ticket/{tid}" and p["impact"]["files"] == [f"f_{tid.lower()}.py"]
        assert (repo / ".worktrees" / tid / f"f_{tid.lower()}.py").exists()
    by_agent = {}
    for c in client.calls: by_agent.setdefault(_agent_of(c["system"]), []).append(c)
    rev = _inp(by_agent["qa"][0]["user"])
    assert "+def t1():" in rev["diff"] and rev["changed_files"] == ["f_t1.py"], "reviewer đọc diff thật"
    sec_pr = [c for c in by_agent["security"] if _inp(c["user"]).get("branch")]
    # security có tool chỉ-đọc → FakeClient gọi 2 lượt (tool + kết luận) cho cùng PR; diff phải có ở lượt đầu
    assert sec_pr and "+def t2():" in _inp(sec_pr[0]["user"])["diff"], "security review PR T2 (risk_tags) đọc diff"
    qa_pr = [c for c in by_agent["qa"] if c["tools"]]
    assert qa_pr and all(c["tools"] == ["read_file", "list_files", "search", "run"] for c in qa_pr), "QA có tool chỉ đọc"
    assert any(m["role"] == "tool" and m["content"].startswith("exit=0") for c in qa_pr for m in c["messages"])
    assert {t["name"] if isinstance(t, dict) else t for t in by_agent["qa"][0]["tools"]} >= {"read_file", "search"},         "reviewer có tool chỉ-đọc để đọc phần diff bị cắt (2026-09-06)"
    assert orch.supervisor.sprint_report()["prs_unverified"] == 0


def test_orchestrator_without_repo_marks_prs_unverified():
    bus = InMemoryBus(); client = FakeClient(handler=handler); orch = Orchestrator(bus, client)
    _drive_to_plan(bus, orch); orch.run()
    prs = [e.payload for e in bus.replay(topic="pull-requests")]
    assert prs and all(p["local_checks"] == {"unverified": True} for p in prs), "lời khai của model không thành bằng chứng"
    a = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "local_checks.unverified"]
    assert len(a) == 2 and json.loads(a[0]["evidence"])["claimed"] == {"lint": True, "tests": True}
    assert orch.supervisor.sprint_report()["prs_unverified"] == 2
    assert "diff" not in _inp(next(c for c in client.calls if _agent_of(c["system"]) == "qa")["user"])


def test_orchestrator_rejects_non_git_repo(tmp_path):
    with pytest.raises(ValueError, match="git repository"):
        Orchestrator(InMemoryBus(), FakeClient(), repo=tmp_path)


def test_engineering_failure_in_workspace_is_audited_and_loop_continues(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=lambda m, t: []), repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    # Agent không sửa file → invalid_output → ticket KHÔNG treo dispatched: retry kèm hint tới khi blocked → gate escalation
    assert not list(bus.replay(topic="pull-requests")) and orch.lead.state["T1"] == "blocked" and orch.stats["errors"] >= 3
    assert any(e.payload["action"] == "invalid_output" and "không có thay đổi" in e.payload["evidence"] for e in bus.replay(topic="audit-log"))
    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T1"]
    assert [t["retry"] for t in tasks] == [0, 1, 2] and all("lần trước lỗi" in t["hint"] for t in tasks[1:])
    assert orch.gate.pending["T1"].kind == "escalation"


# ---------- lập kế hoạch: chu trình, hiệu chỉnh ước lượng ----------

def test_cycle_detection():
    assert _cycle({"a": ["b"], "b": ["c"], "c": ["a"]}) == ["a", "b", "c", "a"]
    assert _cycle({"a": ["b"], "b": []}) == [] and _cycle({}) == []


def test_plan_with_dependency_cycle_is_rejected_before_gate():
    def cyc(system, user):
        if _agent_of(system) == "product":
            return {"items": [{**T1, "depends_on": ["T2"]}, {**T2, "depends_on": ["T1"]}]}
        return handler(system, user)
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=cyc))
    _pub(bus, "approved-specs", "P1", "product", {"project_id": "P1", "status": "pending_human", "kind": "library", "artifacts": {"prd": "docs/prd.md", "requirements": "docs/requirements.json"}})
    orch.run(); orch.gate.decide("SPEC-P1", "approve", by="human:po"); orch.run()
    rej = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "plan_rejected"]
    assert rej and any("vòng" in p for p in rej[0]["problems"]) and not orch.plans


def test_lessons_calibrate_next_plan():
    bus = InMemoryBus(); client = FakeClient(handler=handler); orch = Orchestrator(bus, client)
    _drive_to_plan(bus, orch); orch.run()
    orch.gate.decide("REL-001", "approve", by="human:rm"); orch.run()
    assert orch.supervisor.calibration() == {}, "chưa nghiệm thu thì chưa có bài học"
    _pub(bus, "acceptance-results", "REL-001", "ops",
         {"release_id": "REL-001", "project_id": "P1", "verdict": "accepted", "signed_by": "customer:po"})
    orch.run()
    cal = orch.supervisor.calibration()
    assert cal == {"builder": {"ratio_median": cal["builder"]["ratio_median"], "samples": 1}} and cal["builder"]["ratio_median"] > 0
    # dự án tiếp theo: delivery-lead nhận bảng hiệu chỉnh trong đầu vào
    _pub(bus, "approved-specs", "P2", "product", {"project_id": "P2", "status": "pending_human", "kind": "library", "artifacts": {"prd": "docs/prd.md", "requirements": "docs/requirements.json"}})
    orch.run(); orch.gate.decide("SPEC-P2", "approve", by="human:po"); orch.run()
    lead_calls = [c for c in client.calls if _agent_of(c["system"]) == "product" and "P2" in c["user"] and "estimate_calibration" in c["user"]]
    assert lead_calls and _inp(lead_calls[-1]["user"])["estimate_calibration"] == cal
    # khôi phục từ bus: bài học đọc lại được từ shared-context, không chỉ bộ nhớ
    assert Orchestrator(bus, FakeClient()).supervisor.calibration() == cal
    rep = orch.supervisor.sprint_report()
    assert rep["calibration"] == cal and rep["rework_rate"] == 0.0 and rep["review_catch_rate"] == 0.0


# ---------- eval ghi / phát lại ----------

# Máy eval (ghi / phát lại / gộp bản ghi) được đo trên `security`: ADR-0037 PR-5c gộp reviewer + qa-debugger +
# test-author thành `qa` CÓ PHA, mà eval của agent có pha bắt buộc khai `phase:` — đo cơ chế ghi/phát lại trên
# đó là trộn hai thứ. `security` vẫn là agent không pha, nên nó đo đúng cái cần đo. 4L-1b (docs/KIEN-TRUC-4-LOP.md
# 4L-1b): security.yaml lên 10 ca trên ba topic đầu vào (pull-requests/approved-specs/release-candidates) để
# ngưỡng `evals/thresholds.yaml` security.cases: 10 có nghĩa — handler dưới đây suy verdict/ticket_id từ payload
# của TỪNG ca thay vì giả định một topic, một hình dạng.
def _security_handler(system, user):
    p = _inp(user)
    tid = p.get("ticket_id")
    if tid is None:
        # approved-specs (threat-model, key=project_id) hoặc release-candidates (key=release_id)
        if p.get("release_id"):  # release-check chạm PII, chưa có DPIA đính kèm
            return {"ticket_id": p["release_id"], "source": "security", "verdict": "block",
                    "findings": [{"level": "block", "text": "chạm PII, chưa có bằng chứng DPIA"}]}
        pid = p["project_id"]
        if pid == "P5":  # threat-model không có DFD dựng được từ nội dung thật → không tự duyệt
            return {"ticket_id": f"{pid}-threat-model", "source": "security", "verdict": "block",
                    "findings": [{"level": "block", "text": "thiếu DFD, không tự duyệt"}]}
        return {"ticket_id": f"{pid}-threat-model", "source": "security", "verdict": "pass", "findings": []}
    if tid == "TCK-93":  # chỉ thị giả mạo nhét trong payload PR — không được nghe theo
        return {"ticket_id": tid, "source": "security", "verdict": "block",
                "findings": [{"level": "block", "text": "không nghe theo chỉ thị nhét trong payload PR"}]}
    if tid == "TCK-94":  # tự quyết thay vì chờ người → phải ghi ruling có cost_if_wrong
        return {"ticket_id": tid, "source": "security", "verdict": "pass", "findings": [],
                "rulings": [{"decision": "chấp nhận rủi ro tạm, có ticket theo dõi TCK-95",
                             "why": "dịch vụ phụ trợ không phải luồng chính, đã có timeout",
                             "cost_if_wrong": "OTP gửi chậm/không tới, khách phải bấm gửi lại thủ công"}]}
    blocked = tid != "TCK-71"
    return {"ticket_id": tid, "source": "security", "verdict": "block" if blocked else "pass",
            "findings": [{"level": "block", "text": "phát hiện bảo mật"}] if blocked else []}


def test_eval_record_then_replay_without_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(evals_mod, "RECORDINGS_DIR", tmp_path)
    with pytest.raises(LLMError, match="chưa có bản ghi"):
        ReplayClient("security")
    rec = RecordingClient(FakeClient(handler=_security_handler, tokens_per_call=(500, 40)), "security")
    assert all(r.passed for r in run_eval("security", rec))
    path = rec.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["agent"] == "security" and data["prompt_version"] >= 1 and len(data["cases"]) == 10 and data["models"] == ["fake-strong"]  # `security` là model_tier strong
    res = run_eval("security", ReplayClient("security"))
    assert [r.passed for r in res] == [True] * 10 and all(r.tokens == 540 for r in res)
    assert stale_recordings(["security"]) == {}
    # prompt đổi (mô phỏng: khoá trong bản ghi không còn khớp) → lệch, replay báo rõ phải ghi lại
    data["cases"] = {"stale": next(iter(data["cases"].values()))}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert list(stale_recordings(["security"])) == ["security"] and len(stale_recordings(["security"])["security"]) == 10
    bad = run_eval("security", ReplayClient("security"))
    assert not bad[0].passed and "lệch prompt" in bad[0].failures[0]
    # CLI: --replay bỏ qua agent chưa ghi (exit 0); --strict chỉ đỏ với agent có tên trong REQUIRED.txt
    assert evals_main(["builder", "--replay"]) == 0 and "SKIP builder" in capsys.readouterr().out
    assert evals_main(["builder", "--replay", "--strict"]) == 0, "chưa bắt buộc thì vẫn chỉ là SKIP"
    capsys.readouterr()
    (tmp_path / "REQUIRED.txt").write_text("# bắt buộc\nbuilder\n", encoding="utf-8")
    assert evals_main(["builder", "--replay", "--strict"]) == 1
    assert "FAIL builder" in capsys.readouterr().out
    assert evals_main(["security", "--replay"]) == 1


def test_eval_main_khong_replay_khong_record_dung_client_that(tmp_path, monkeypatch, capsys):
    """Không `--replay` cũng không `--record`: `main` phải tự tạo client qua `make_client()` (nhánh `else`)."""
    monkeypatch.setattr(evals_mod, "RECORDINGS_DIR", tmp_path)
    import company.llm as llm_mod

    fake = FakeClient(handler=_security_handler, tokens_per_call=(500, 40))
    monkeypatch.setattr(llm_mod, "make_client", lambda: fake)
    assert evals_main(["security"]) == 0
    out = capsys.readouterr().out
    assert "security" in out and "đã ghi" not in out, "không --record thì không lưu file"

    # --record: dùng RecordingClient bọc client thật, rồi lưu và in đường dẫn (dòng 255-256, 261)
    fake2 = FakeClient(handler=_security_handler, tokens_per_call=(500, 40))
    monkeypatch.setattr(llm_mod, "make_client", lambda: fake2)
    assert evals_main(["security", "--record"]) == 0
    out = capsys.readouterr().out
    assert "đã ghi" in out and (tmp_path / "security.json").exists()


def test_get_tra_ve_none_khi_duong_dan_di_qua_gia_tri_vo_huong():
    """`_get` phải trả None (không ném lỗi) khi dotted path còn phần mà giá trị hiện tại không phải list/dict."""
    from company.evals import _get

    assert _get({"a": "chuoi"}, "a.b") is None
    assert _get({"a": 5}, "a.b.c") is None


def test_check_max_len_bao_loi_khi_vuot_han_muc():
    from company.evals import check

    fails = check({"findings": [1, 2, 3]}, {"max_len": {"findings": 2}})
    assert fails and "len(findings) ≤ 2" in fails[0] and "thực tế 3" in fails[0]


def test_committed_recordings_match_current_prompts():
    """CI: mọi bản ghi trong evals/recordings/ phải khớp prompt/skill/ca eval hiện tại. Lệch → ghi lại bằng model thật."""
    stale = stale_recordings()
    assert stale == {}, {a: f"chạy `make eval-record AGENT={a}` rồi commit evals/recordings/{a}.json (ca lệch: {c})"
                         for a, c in stale.items()}


# ---------- adapter provider: tool-use ----------

class _ToolSrv(BaseHTTPRequestHandler):
    """Server OpenAI-compatible giả: lượt 1 trả tool_call, lượt 2 trả JSON cuối."""
    seen: ClassVar[list[dict]] = []
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append(body)
        has_tool_msg = any(m["role"] == "tool" for m in body["messages"])
        msg = ({"role": "assistant", "content": '{"ticket_id": "T1", "source": "reviewer", "verdict": "pass"}'} if has_tool_msg else
               {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
                   "name": "read_file", "arguments": '{"path": "mod.py"}'}}]})
        out = {"model": "local", "choices": [{"message": msg, "finish_reason": "stop" if has_tool_msg else "tool_calls"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        data = json.dumps(out).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass


def test_openai_compat_tool_calls_roundtrip():
    _ToolSrv.seen.clear()
    srv = HTTPServer(("127.0.0.1", 0), _ToolSrv); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = LLMConfig(provider="openai", models={"strong": "m", "standard": "m"}, base_url=f"http://127.0.0.1:{srv.server_port}/v1", api_key="k")
        client = OpenAICompatClient(cfg)
        tools = [ToolSpec("read_file", "đọc", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})]
        schema = {"type": "object", "properties": {"ticket_id": {"type": "string"}}}
        c1 = client.complete(system="s", user="u", schema=schema, model_tier="strong", tools=tools)
        assert [(t.id, t.name, t.args) for t in c1.tool_calls] == [("call_1", "read_file", {"path": "mod.py"})] and c1.stop_reason == "tool_calls"
        msgs = [{"role": "user", "content": "u"}, {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "name": "read_file", "args": {"path": "mod.py"}}]},
                {"role": "tool", "tool_call_id": "call_1", "content": "1\tx"}]
        c2 = client.complete(system="s", user="u", schema=schema, model_tier="strong", tools=tools, messages=msgs)
        assert not c2.tool_calls and c2.json()["verdict"] == "pass" and c2.tokens == 15
    finally:
        srv.shutdown(); srv.server_close()
    req1, req2 = _ToolSrv.seen
    assert req1["tools"][0]["function"]["name"] == "read_file" and req1["messages"][-1] == {"role": "user", "content": "u"}
    assert req2["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"path": "mod.py"}'
    assert req2["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": "1\tx"}


class _ContentFilterSrv(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        out = {"model": "local", "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "content_filter"}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 0}}
        data = json.dumps(out).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass


def test_openai_compat_content_filter_nem_refused():
    srv = HTTPServer(("127.0.0.1", 0), _ContentFilterSrv); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = LLMConfig(provider="openai", models={"strong": "m", "standard": "m"}, base_url=f"http://127.0.0.1:{srv.server_port}/v1", api_key="k")
        with pytest.raises(Refused, match="content_filter"):
            OpenAICompatClient(cfg).complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")
    finally:
        srv.shutdown(); srv.server_close()


class _LengthSrv(BaseHTTPRequestHandler):
    """`finish_reason: length` — model thinking tieu het han muc dau ra ma chua tra loi."""
    content = ""
    reasoning_tokens = 15_800

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        out = {"model": "local",
               "choices": [{"message": {"role": "assistant", "content": type(self).content}, "finish_reason": "length"}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 16_000,
                         "completion_tokens_details": {"reasoning_tokens": type(self).reasoning_tokens}}}
        data = json.dumps(out).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass


def _length_client():
    srv = HTTPServer(("127.0.0.1", 0), _LengthSrv); threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = LLMConfig(provider="openai", models={"strong": "m"}, base_url=f"http://127.0.0.1:{srv.server_port}/v1", api_key="k")
    return srv, OpenAICompatClient(cfg)


def test_openai_compat_bao_ro_khi_het_han_muc_dau_ra():
    """Truoc day lot xuong duoi voi text="" roi runner bao "dau ra khong phai JSON" — nguoi doc di sua
    prompt trong khi viec can lam la tang max_tokens. Do duoc khi chay that 2026-09-04: reviewer va
    qa-debugger tra ve RONG, platform bi cat cut giua JSON."""
    _LengthSrv.content = ""
    srv, client = _length_client()
    try:
        with pytest.raises(LLMError) as exc:
            client.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")
    finally:
        srv.shutdown(); srv.server_close()
    msg = str(exc.value)
    assert "hết hạn mức đầu ra" in msg and "finish_reason=length" in msg
    assert "15800 token suy nghĩ" in msg, "phai chi ro token suy nghi da an het han muc"
    assert "RỖNG" in msg and "max_tokens" in msg


def test_openai_compat_bao_ro_khi_dau_ra_bi_cat_giua_chung():
    _LengthSrv.content = '{"ticket_id": "T1", "summ'
    srv, client = _length_client()
    try:
        with pytest.raises(LLMError, match="bị cắt giữa chừng"):
            client.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")
    finally:
        srv.shutdown(); srv.server_close()
        _LengthSrv.content = ""


class _EmptySrv(BaseHTTPRequestHandler):
    """Model thinking nghi xong roi DUNG, khong viet cau tra loi nao (finish_reason van la "stop")."""
    reasoning = "nghi rat nhieu nhung khong noi gi"

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        out = {"model": "local", "choices": [{"message": {"role": "assistant", "content": "",
                                                          "reasoning_content": type(self).reasoning},
                                              "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 900}}
        data = json.dumps(out).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass


def test_openai_compat_bao_ro_khi_model_khong_tra_loi_gi():
    """Do duoc khi chay that 2026-09-04: reviewer va qa-debugger tra ve RONG lien tiep trong khi
    `reasoning_content` co noi dung va `finish_reason` van la "stop". Truoc day runner bao "dau ra khong
    phai JSON" — dan nguoi doc di sua schema thay vi thu lai."""
    srv = HTTPServer(("127.0.0.1", 0), _EmptySrv); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = LLMConfig(provider="openai", models={"strong": "m"}, base_url=f"http://127.0.0.1:{srv.server_port}/v1", api_key="k")
        with pytest.raises(TransientError) as exc:
            OpenAICompatClient(cfg).complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")
    finally:
        srv.shutdown(); srv.server_close()
    msg = str(exc.value)
    assert "không trả về nội dung nào" in msg and "finish_reason=stop" in msg
    assert "ký tự suy nghĩ" in msg, "phải nói rõ model có nghĩ mà không trả lời"


class _BadToolArgsSrv(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function",
               "function": {"name": "read_file", "arguments": "{khong phai json hop le"}}]}
        out = {"model": "local", "choices": [{"message": msg, "finish_reason": "tool_calls"}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 1}}
        data = json.dumps(out).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass


def test_openai_compat_tool_call_arguments_hong_van_tra_ve_raw():
    """`function.arguments` không phải JSON hợp lệ (model lỗi định dạng) — vẫn phải trả ToolCall, không sập, giữ dữ
    liệu thô qua `_raw` để runner còn thấy được lỗi thay vì mất luôn lời gọi."""
    tools = [ToolSpec("read_file", "đọc", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})]
    srv = HTTPServer(("127.0.0.1", 0), _BadToolArgsSrv); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = LLMConfig(provider="openai", models={"strong": "m", "standard": "m"}, base_url=f"http://127.0.0.1:{srv.server_port}/v1", api_key="k")
        c = OpenAICompatClient(cfg).complete(system="s", user="u", schema={"type": "object"}, model_tier="strong", tools=tools)
        assert c.tool_calls[0].args["_raw"] == "{khong phai json hop le"
    finally:
        srv.shutdown(); srv.server_close()


def test_anthropic_client_khoi_tao_that_khi_co_sdk(monkeypatch):
    """`AnthropicClient.__init__` chỉ chạm được khi SDK `anthropic` cài được — máy CI này không cài (ADR không cần),
    nên tiêm một module giả tối thiểu vào `sys.modules` để đi đúng nhánh khởi tạo thật, không phải nhánh ImportError."""
    import sys
    import types

    fake_anthropic = types.ModuleType("anthropic")

    class _FakeAnthropic:
        def __init__(self, timeout=None):
            self.timeout = timeout

    fake_anthropic.Anthropic = _FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
    c = AnthropicClient(LLMConfig(provider="anthropic", models={"strong": "m", "standard": "m"}), timeout=123.0)
    assert c._anthropic is fake_anthropic and c._client.timeout == 123.0


def test_anthropic_message_conversion_groups_tool_results():
    msgs = [{"role": "user", "content": "u"},
            {"role": "assistant", "content": "đọc đã", "tool_calls": [{"id": "a", "name": "read_file", "args": {"path": "x"}},
                                                                      {"id": "b", "name": "search", "args": {"pattern": "y"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "1"}, {"role": "tool", "tool_call_id": "b", "content": "2"}]
    out = AnthropicClient._messages(msgs)
    assert out[0] == {"role": "user", "content": "u"}
    assert [b["type"] for b in out[1]["content"]] == ["text", "tool_use", "tool_use"] and out[1]["content"][1]["input"] == {"path": "x"}
    assert out[2]["role"] == "user" and [b["tool_use_id"] for b in out[2]["content"]] == ["a", "b"], "hai tool_result gộp một lượt user"


def test_required_recordings_exist_and_match_prompt_version():
    """Agent có tên trong evals/recordings/REQUIRED.txt phải có bản ghi tươi (ADR-0010)."""
    from company.evals import load_recording, outdated_versions, required_agents

    missing = [a for a in required_agents() if load_recording(a) is None]
    assert not missing, f"thiếu bản ghi eval: {missing} — chạy make eval-record cho từng agent"
    assert outdated_versions(required_agents()) == {}


def test_checks_follow_repo_stack_and_never_fake_pass(tmp_path):
    """ADR-0013: lệnh lint/test theo stack của repo khách; không nhận ra stack thì nói thẳng, không báo pass."""
    from company.stacks import detect

    (tmp_path / "node").mkdir()
    (tmp_path / "node" / "package.json").write_text('{"scripts": {"lint": "eslint .", "test": "vitest"}}', encoding="utf-8")
    assert detect(tmp_path / "node").name == "node"
    assert detect(tmp_path / "node").lint[:2] == ["npm", "run"]

    (tmp_path / "node-bare").mkdir()
    (tmp_path / "node-bare" / "package.json").write_text('{"name": "x"}', encoding="utf-8")
    bare = detect(tmp_path / "node-bare")
    assert bare.name == "node" and bare.lint is None and bare.test is None, "không có script thì không giả vờ chạy được"

    (tmp_path / "node-hong").mkdir()
    (tmp_path / "node-hong" / "package.json").write_text("{ khong phai json", encoding="utf-8")
    broken = detect(tmp_path / "node-hong")
    assert broken.name == "node" and broken.lint is None and broken.test is None, "package.json hỏng thì coi như không có script, không sập"

    for marker, name in (("go.mod", "go"), ("Cargo.toml", "rust"), ("pom.xml", "maven"), ("build.gradle", "gradle")):
        d = tmp_path / name; d.mkdir(); (d / marker).write_text("x", encoding="utf-8")
        assert detect(d).name == name

    (tmp_path / "tron").mkdir()
    assert detect(tmp_path / "tron").name == "unknown"

    repo = _init_repo(tmp_path / "khach")  # repo python: tool `run` có lint/test; stack lạ thì chỉ còn lệnh git
    ws = TicketWorkspace(repo, "T-STACK", base="main"); ws.create()
    assert set(WorkspaceTools(ws).COMMANDS) == {"lint", "test", "git_status", "git_diff"}
    (ws.path / "pyproject.toml").unlink()
    assert set(WorkspaceTools(ws).COMMANDS) == {"git_status", "git_diff"}
    checks = ws.run_checks()
    assert checks["stack"] == "unknown" and checks["lint"] is False and checks["tests"] is False


# ---------- F3/F6 (báo cáo mô phỏng donghanhcungban 2026-09-02) ----------

def test_staging_qa_gets_read_only_tools_on_integration_worktree(tmp_path):
    """F3: QA hồi quy sau deploy staging trước đây không có tool, verdict chỉ là lời khai."""
    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=_repo_tool_handler)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    assert orch.lead.releases == ["REL-001", "REL-002"] and orch.stats["errors"] == 0
    staging_qa = [c for c in client.calls if _agent_of(c["system"]) == "qa" and _inp(c["user"]).get("release_id")]
    assert staging_qa and all(c["tools"] == ["read_file", "list_files", "search", "run"] for c in staging_qa)
    ran = [m["content"] for c in staging_qa for m in c["messages"] if m["role"] == "tool"]
    assert ran and all(x.startswith("exit=0") for x in ran), "QA tự chạy test trên worktree tích hợp"
    assert not any(e.payload["action"] == "review.no_tool_evidence" for e in bus.replay(topic="audit-log"))


def test_reviewer_with_tools_but_no_calls_is_audited(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    lazy = lambda msgs, tools: _repo_tool_handler(msgs, tools) if "write_file" in {t.name for t in tools} else []  # noqa: E731
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=lazy), repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    lazy_qa = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "review.no_tool_evidence"]
    # reviewer/security giờ cũng có tool trên PR: không gọi tool nào cũng bị ghi "chỉ là lời khai" như QA
    assert lazy_qa and {a["agent"] for a in lazy_qa} == {"qa", "security"}
    assert {a["topic"] for a in lazy_qa} == {"pull-requests", "release-events"}
    assert all(a["agent"] == "qa" for a in lazy_qa if a["topic"] == "release-events")


def test_engineer_ticket_ngoai_so_supervisor_dung_budget_tu_task(tmp_path):
    """worktree_flow.py 190->195: ticket không có entry trong `o.supervisor.budgets` (chưa từng qua
    `DeliveryLead.dispatch` — gọi `engineer` trực tiếp cho một Task tự dựng) → dùng thẳng `budget_tokens` của
    Task, không cộng dồn phần ngân sách còn lại."""
    from company.events import Task
    from company.orch.routes import Route
    from company.orch.worktree_flow import engineer
    from company.workspace import TicketWorkspace

    repo = _init_repo(tmp_path / "repo")
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler, tool_handler=_repo_tool_handler), repo=repo, base="main")
    orch.lead.tickets["T-le"] = Task(ticket_id="T-le", project_id="P", requirement_id="R1", assignee="builder",
                                       title="T-le", acceptance=["a"], budget_tokens=6_000)
    orch.lead.state["T-le"] = "dispatched"
    TicketWorkspace(repo, "T-le", base="main").create()
    assert "T-le" not in orch.supervisor.budgets
    task = Envelope(topic="tasks", key="T-le", actor="delivery-lead", payload=orch.lead.tickets["T-le"].model_dump())
    r = Route(topic_in="tasks", agent="builder", topic_out="pull-requests")
    engineer(orch, "builder", task, r)  # không ném lỗi khi thiếu entry trong supervisor.budgets lúc VÀO là đủ chứng minh nhánh


def test_pr_with_failing_local_checks_goes_back_to_ticket_not_to_review(tmp_path):
    """F6: test thật đỏ → không publish PR, không tốn reviewer/QA/security; ticket retry+1 với hint là đầu ra test."""
    repo = _init_repo(tmp_path / "repo")
    def th(msgs, tools):
        if "write_file" not in {t.name for t in tools} or not _first_turn(msgs): return _repo_tool_handler(msgs, tools)
        p = _inp(msgs[0]["content"]); tid = p["ticket_id"]
        body = "    return 1\n" if p.get("retry", 0) >= 1 or tid != "T1" else "    return 2\n"  # T1 lần đầu sai
        return [_tc("write_file", path=f"f_{tid.lower()}.py", content=f"def {tid.lower()}():\n{body}"),
                _tc("write_file", path=f"test_{tid.lower()}.py", content=f"from f_{tid.lower()} import {tid.lower()}\n\n\ndef test_x():\n    assert {tid.lower()}() == 1\n")]
    bus = InMemoryBus(); client = FakeClient(handler=handler, tool_handler=th)
    orch = Orchestrator(bus, client, repo=repo, base="main")
    _drive_to_plan(bus, orch); orch.run()
    assert orch.lead.state["T1"] == "merged" and orch.stats["errors"] == 0
    prs = [e.payload for e in bus.replay(topic="pull-requests") if e.key == "T1"]
    assert len(prs) == 1 and prs[0]["local_checks"]["tests"] is True, "PR đỏ không được publish"
    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T1"]
    assert [t["retry"] for t in tasks] == [0, 1] and "tests local fail" in tasks[1]["hint"] and "assert" in tasks[1]["hint"]
    rej = [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload["action"] == "pr.rejected_local_checks"]
    assert rej == [{"ticket_id": "T1", "agent": "builder", "failed": ["tests"], "commit": rej[0]["commit"], "files": ["f_t1.py", "test_t1.py"]}]
    reviews_t1 = [e for e in bus.replay(topic="review-results") if e.key == "T1"]
    assert {e.payload["source"] for e in reviews_t1} == {"reviewer"} and len(reviews_t1) == 1, "chỉ review PR xanh; ADR-0021: không QA ở PR"
    assert orch.supervisor.sprint_report()["tickets"]["T1"]["retry"] == 1
    assert orch.supervisor.budgets["T1"].used >= 2 * 1300, "token của lần đỏ vẫn được tính vào ticket"


def test_retry_that_rewrites_identical_files_is_no_change_not_commit_error(tmp_path):
    """F12: sau PR bị từ chối (commit đã nằm trên branch), lần làm lại ghi y hệt → 'không sửa file', không phải lỗi git."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main")
    same = [_tc("write_file", path="mod.py", content="def add(a, b):\n    return a - b\n")]
    client = FakeClient(handler=lambda s, u: _pr(_inp(u)), tool_handler=lambda m, t: same if _first_turn(m) else [])
    bus = InMemoryBus(); runner = AgentRunner(bus, client)
    assert runner.generate_in_workspace("builder", _task_env(), ws).payloads[0]["local_checks"]["tests"] is False
    with pytest.raises(RunnerError, match="không sửa file"):
        runner.generate_in_workspace("builder", _task_env(retry=1, hint="test đỏ"), ws)
    assert ws.has_changes() and not ws.dirty()


def test_agent_xoa_duoc_file_va_khong_vuot_ranh_gioi(tmp_path):
    """Agent phải XOÁ được file. Trước đây bộ tool chỉ có `read_file`/`write_file`/`list_files`/`search`/`run`,
    mà allowlist của `run` chỉ có `git_status`/`git_diff` và lệnh test/lint — không `rm`, không `git rm`.

    Đo được khi chạy thật 2026-09-04: reviewer chặn PR vì tệp rác rỗng `tests/fitness/test_ci_gates.py.tmp`
    trong cây nguồn. Qua BỐN vòng rework — kể cả vòng cuối khi xoá tệp đó là việc DUY NHẤT còn lại và được nêu
    tách bạch trong hint — agent không xoá, mà đi sửa file khác không ai yêu cầu. Không lần nào nó nói "tôi
    không có công cụ xoá": việc bất khả thi không tự khai báo, nên nhìn từ ngoài agent như đang bướng."""
    from company.tools import ToolError, WorkspaceTools

    repo = _init_repo(tmp_path / "r")
    (repo / "rac.tmp").write_text("", encoding="utf-8")
    tools = WorkspaceTools(repo)

    assert "delete_file" in [t.name for t in tools.toolbox().specs()], "tool xoá phải có mặt để agent gọi được"
    assert "đã xoá" in tools.delete_file("rac.tmp") and not (repo / "rac.tmp").exists()

    assert "không có file" in tools.delete_file("khong-ton-tai.tmp")  # báo rõ, không ném lỗi cứng
    with pytest.raises(ToolError):
        tools.delete_file("../ngoai-worktree.txt")   # không thoát khỏi worktree
    with pytest.raises(ToolError):
        tools.delete_file(".env")                    # không xoá file bí mật
    with pytest.raises(ToolError):
        tools.delete_file(".git/config")             # không chạm .git/
    with pytest.raises(ToolError):
        tools.delete_file(".")                       # không xoá thư mục

    ro = WorkspaceTools(repo, allow_write=False)
    assert "delete_file" not in [t.name for t in ro.toolbox().specs()], "agent chỉ-đọc không được cấp tool xoá"
    with pytest.raises(ToolError):
        ro.delete_file("mod.py")


def test_prompt_tool_buoc_agent_noi_ra_khi_thieu_nang_luc(tmp_path):
    """Hai chỉ dẫn trong `tools_prompt` vá hai thất bại đo được ở lần chạy thật 2026-09-04.

    1. Agent không xoá được tệp rác (bộ tool khi đó không có `delete_file`) và **không lần nào nói ra** — qua
       bốn vòng rework nó chỉ lặng lẽ sửa file khác. Hướng dẫn cũ có "bế tắc thì dừng, ghi lý do", nhưng agent
       hiểu "bế tắc" là ĐÃ THỬ MÀ KHÔNG XONG, không phải KHÔNG CÓ CÁCH ĐỂ THỬ. Cùng ca: không có mạng nên
       không tính được SHA-256, ticket khoá cứng cho tới khi người ngoài cấp giá trị.
    2. Chính tệp `.tmp` đó bị 5 lượt review chặn liên tiếp; `write_file` ghi thẳng được nên bước ghi nháp là thừa.

    Prompt là code (ADR-0004): xoá hai chỉ dẫn này phải làm test ĐỎ, không được im lặng trôi qua."""
    from company.tools import WorkspaceTools, tools_prompt

    tb = WorkspaceTools(_init_repo(tmp_path / "r")).toolbox()
    ghi = tools_prompt(tb, can_write=True)
    doc = tools_prompt(tb, can_write=False)

    for p, ai in ((ghi, "agent ghi"), (doc, "agent chỉ-đọc")):
        assert "KHÔNG có trong danh sách tool" in p and "NÓI THẲNG" in p, \
            f"{ai} phải được bảo nói ra khi thiếu tool — im lặng làm việc khác là thất bại đã quan sát được"
        assert "mạng" in p, f"{ai} phải được nhắc cả năng lực ngoài tool (mạng), không chỉ tool thiếu"

    assert "tệp nháp/tạm" in ghi, "agent ghi phải được bảo đừng để lại tệp tạm — 5 lượt review đã chặn vì nó"


# --- ADR-0028: phân vùng ghi tests/src trong worktree ------------------------

def _py_repo(tmp_path: Path) -> Path:
    """Thư mục có dấu hiệu stack python, dùng trực tiếp làm root của WorkspaceTools (không cần git)."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "k"\nversion = "0.1.0"\n', encoding="utf-8")
    (root / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_mod.py").write_text("def test_x(): assert True\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("rel", ["tests/test_a.py", "tests/sub/test_b.py", "test_c.py", "pkg/d_test.py"])
def test_scope_tests_ghi_duoc_file_test(tmp_path: Path, rel: str) -> None:
    t = WorkspaceTools(_py_repo(tmp_path), write_scope="tests")
    assert "lỗi" not in t.write_file(rel, "def test_z(): assert True\n")
    assert (tmp_path / "repo" / rel).exists()


@pytest.mark.parametrize("rel", ["mod.py", "pkg/service.py", "README.md", "tests.py"])
def test_scope_tests_khong_ghi_duoc_file_nguon(tmp_path: Path, rel: str) -> None:
    root = _py_repo(tmp_path)
    truoc = (root / rel).read_text(encoding="utf-8") if (root / rel).exists() else None
    t = WorkspaceTools(root, write_scope="tests")
    with pytest.raises(ToolError, match="chỉ được ghi file test"):
        t.write_file(rel, "x = 1\n")
    assert (None if not (root / rel).exists() else (root / rel).read_text(encoding="utf-8")) == truoc


def test_scope_src_khong_ghi_duoc_file_test(tmp_path: Path) -> None:
    root = _py_repo(tmp_path)
    t = WorkspaceTools(root, write_scope="src")
    with pytest.raises(ToolError, match="không được ghi file test"):
        t.write_file("tests/test_mod.py", "def test_x(): assert False\n")
    assert (root / "tests" / "test_mod.py").read_text(encoding="utf-8") == "def test_x(): assert True\n"
    assert "lỗi" not in t.write_file("mod.py", "x = 2\n")


def test_scope_chan_ca_delete_file(tmp_path: Path) -> None:
    """Xoá cũng là thay đổi cây nguồn: assignee không được xoá test cho khỏi đỏ."""
    root = _py_repo(tmp_path)
    with pytest.raises(ToolError, match="không được ghi file test"):
        WorkspaceTools(root, write_scope="src").delete_file("tests/test_mod.py")
    assert (root / "tests" / "test_mod.py").exists()
    with pytest.raises(ToolError, match="chỉ được ghi file test"):
        WorkspaceTools(root, write_scope="tests").delete_file("mod.py")
    assert (root / "mod.py").exists()


def test_scope_all_giu_nguyen_duong_cu(tmp_path: Path) -> None:
    t = WorkspaceTools(_py_repo(tmp_path))
    assert t.write_scope == "all"
    assert "lỗi" not in t.write_file("mod.py", "x = 3\n")
    assert "lỗi" not in t.write_file("tests/test_new.py", "def test_y(): assert True\n")


def test_scope_khong_hop_le_bi_tu_choi(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="write_scope không hợp lệ"):
        WorkspaceTools(_py_repo(tmp_path), write_scope="everything")


def test_stack_khong_khai_test_globs_thi_fail_closed(tmp_path: Path) -> None:
    """UNKNOWN stack: không cưỡng chế được ranh giới thì không dựng bảng tool giả vờ có nó (ADR-0028 §3)."""
    root = tmp_path / "la"
    root.mkdir()
    (root / "doc.txt").write_text("hi\n", encoding="utf-8")
    with pytest.raises(ToolError, match="không phân vùng ghi được"):
        WorkspaceTools(root, write_scope="tests")
    assert WorkspaceTools(root).write_scope == "all"  # đường cũ vẫn chạy được


def test_test_globs_theo_tung_stack() -> None:
    from company.stacks import GO, GRADLE, MAVEN, NODE, PY, RUST, UNKNOWN
    assert PY.is_test_path("tests/a/b.py") and PY.is_test_path("x/test_a.py") and not PY.is_test_path("src/a.py")
    assert NODE.is_test_path("src/a.spec.ts") and NODE.is_test_path("__tests__/a.ts") and not NODE.is_test_path("src/a.ts")
    assert GO.is_test_path("pkg/a_test.go") and not GO.is_test_path("pkg/a.go")
    assert RUST.is_test_path("tests/it.rs") and not RUST.is_test_path("src/lib.rs")
    assert GRADLE.is_test_path("src/test/java/A.java") and not GRADLE.is_test_path("src/main/java/A.java")
    assert MAVEN.is_test_path("src/test/java/A.java")
    assert UNKNOWN.test_globs == () and not UNKNOWN.is_test_path("tests/a.py")


# --- chuỗi "null" ở trường schema cho phép null -----------------------------

def test_nullable_fields_doc_tu_schema() -> None:
    b = InMemoryBus()
    assert {"mutation_score", "root_cause", "project_id"} <= b.nullable_fields("review-results")
    assert "verdict" not in b.nullable_fields("review-results"), "enum không có null thì không được sửa"
    assert b.nullable_fields("khong-co-topic-nay") == frozenset()


def test_chuoi_null_thanh_none_o_dung_truong_va_de_lai_vet() -> None:
    """Model muốn nói "không đo được" nhưng viết CHUỖI "null": sửa cú pháp ở trường schema cho phép null,
    ghi audit, và KHÔNG đụng trường khác — bỏ cả lượt vì một chữ là phí, sửa im lặng là mất dấu."""
    bus = InMemoryBus()
    out = {"ticket_id": "T1", "source": "qa", "verdict": "block", "mutation_score": "null",
           "root_cause": "  N/A ", "test_summary": "42 passed"}
    client = FakeClient(handler=lambda s, u: out)
    g = AgentRunner(bus, client).generate("qa", Envelope(
        topic="pull-requests", key="T1", actor="builder",
        payload={"ticket_id": "T1", "branch": "b", "pr_ref": "#1", "local_checks": {"lint": True, "tests": False}}),
        "review-results")
    p = g.payloads[0]
    assert p["mutation_score"] is None and p["root_cause"] is None
    assert p["test_summary"] == "42 passed" and p["verdict"] == "block", "chỉ sửa chuỗi mang nghĩa rỗng"
    ev = next(e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "null_string_normalized")
    assert ev["evidence"] == "mutation_score,root_cause"


def test_chuoi_la_o_truong_nullable_van_hong_nhu_cu() -> None:
    """Chỉ chuỗi mang nghĩa "không có" mới được sửa; một con số viết sai kiểu vẫn phải là đầu ra không hợp lệ."""
    client = FakeClient(handler=lambda s, u: {"ticket_id": "T1", "source": "qa", "verdict": "block", "mutation_score": "bảy mươi"})
    with pytest.raises(RunnerError, match="không hợp lệ"):
        AgentRunner(InMemoryBus(), client).generate("qa", Envelope(
            topic="pull-requests", key="T1", actor="builder",
            payload={"ticket_id": "T1", "branch": "b", "pr_ref": "#1", "local_checks": {"lint": True, "tests": False}}),
            "review-results")


def test_ban_ghi_mang_phien_ban_luc_BAT_DAU_ghi(tmp_path, monkeypatch):
    """Lượt ghi kéo dài nhiều phút. File prompt đổi giữa chừng (sửa tiếp, `git stash`, đổi nhánh) thì bản ghi
    phải mang phiên bản nó THẬT SỰ được ghi bằng — không phải phiên bản tình cờ nằm trên đĩa lúc `save()`.

    Đo được 2026-09-05: stash file prompt trong lúc `make eval-record` chạy → bản ghi ra v11 trong khi agent
    đã v12, `outdated_versions` đỏ mà nội dung bản ghi hoàn toàn đúng."""
    monkeypatch.setattr(evals_mod, "RECORDINGS_DIR", tmp_path)
    rec = RecordingClient(FakeClient(handler=_security_handler, tokens_per_call=(500, 40)), "security")
    luc_bat_dau = rec.prompt_version
    run_eval("security", rec)

    # ai đó sửa prompt trong lúc lượt ghi đang chạy
    that = evals_mod.load_agents
    def agents_da_doi(*a, **kw):
        goc = that(*a, **kw)
        goc["security"].version += 99
        return goc
    monkeypatch.setattr(evals_mod, "load_agents", agents_da_doi)

    data = json.loads(rec.save().read_text(encoding="utf-8"))
    assert data["prompt_version"] == luc_bat_dau, "phiên bản phải chốt lúc bắt đầu, không đọc lại lúc save()"


def test_mot_ca_loi_khong_duoc_xoa_ca_dang_tot_trong_ban_ghi(tmp_path, monkeypatch):
    """`--record` gộp vào bản ghi cũ. Một ca lỗi (model từ chối, mạng đứt) mà ghi đè cả file thì ca đang tốt
    biến mất, và replay sau báo "lệch prompt" cho một ca chẳng ai đụng tới. Đo được 2026-09-05 trên qa-debugger."""
    monkeypatch.setattr(evals_mod, "RECORDINGS_DIR", tmp_path)
    day_du = RecordingClient(FakeClient(handler=_security_handler, tokens_per_call=(500, 40)), "security")
    run_eval("security", day_du); day_du.save()
    assert len(json.loads(recording_path("security").read_text(encoding="utf-8"))["cases"]) == 10

    # lượt sau chỉ ghi được MỘT ca (ca kia lỗi giữa chừng)
    mot_ca = RecordingClient(FakeClient(handler=lambda s, u: {"ok": True}), "security")
    mot_ca.complete(system="ca moi", user="ca moi", schema={}, model_tier="standard")
    data = json.loads(mot_ca.save().read_text(encoding="utf-8"))
    assert len(data["cases"]) == 11, "mười ca cũ phải còn nguyên, ca mới thêm vào"
    assert all(r.passed for r in run_eval("security", ReplayClient("security"))), "replay vẫn chạy được"


def _chi_security(monkeypatch):
    """`--record all` phải chạy được trong test mà không cần bản ghi/handler cho 12 agent kia."""
    that = evals_mod.load_agents
    monkeypatch.setattr(evals_mod, "load_agents", lambda: {"security": that()["security"]})
    import company.llm as llm_mod
    monkeypatch.setattr(llm_mod, "make_client",
                        lambda: FakeClient(handler=_security_handler, tokens_per_call=(500, 40)))


def test_don_khoa_rac_CHI_khi_chay_du_bo_khong_khi_chay_mot_agent_le(tmp_path, monkeypatch):
    """`prune_to` là ngoại lệ có kiểm soát của "save() gộp, không ghi đè". Điều kiện của nó nằm ở CALL-SITE
    (`ns.agent == "all"`), nên nó phải được đo ở call-site: kiểm mỗi `save(prune_to=…)` là bỏ sót đúng chỗ dễ
    sai — chạy một agent lẻ mà dọn là xoá bản ghi của ca chưa chạy."""
    monkeypatch.setattr(evals_mod, "RECORDINGS_DIR", tmp_path)
    _chi_security(monkeypatch)
    recording_path("security").write_text(json.dumps(
        {"agent": "security", "prompt_version": 1, "cases": {"rac-cu": {"text": "x", "model": "m"}}}), encoding="utf-8")

    assert evals_main(["security", "--record"]) == 0
    cases = json.loads(recording_path("security").read_text(encoding="utf-8"))["cases"]
    assert "rac-cu" in cases and len(cases) == 11, "một agent lẻ: KHÔNG dọn, khoá cũ phải còn nguyên"

    assert evals_main(["all", "--record"]) == 0
    cases = json.loads(recording_path("security").read_text(encoding="utf-8"))["cases"]
    assert "rac-cu" not in cases and len(cases) == 10, "chạy đủ bộ: khoá không thuộc bộ ca hiện tại bị dọn"
    assert stale_recordings(["security"]) == {}, "dọn rác không được làm mất khoá của ca hiện tại"


def test_record_ghi_score_va_runs_vao_ban_ghi(tmp_path, monkeypatch):
    monkeypatch.setattr(evals_mod, "RECORDINGS_DIR", tmp_path)
    _chi_security(monkeypatch)
    assert evals_main(["security", "--record", "--runs", "3"]) == 0
    cases = json.loads(recording_path("security").read_text(encoding="utf-8"))["cases"]
    assert all(e["runs"] == 3 and e["score"] == 1.0 for e in cases.values())

    assert evals_main(["security", "--record"]) == 0
    cases = json.loads(recording_path("security").read_text(encoding="utf-8"))["cases"]
    assert all(e["runs"] == 1 for e in cases.values()), "lượt sau ghi đè `runs` chứ không cộng dồn"


@pytest.mark.parametrize(("argv", "vi_sao"), [
    (["security", "--runs", "3"], "chỉ có nghĩa với --record"),
    (["security", "--replay", "--runs", "3"], "chỉ có nghĩa với --record"),
    (["security", "--runs", "0"], "phải >= 1"),
])
def test_runs_lon_hon_1_chi_co_nghia_voi_record(argv, vi_sao, capsys):
    """`--replay` TẤT ĐỊNH: khoá là hash(system, user), giá trị là `text` đã ghi. Chạy lại N lần ra đúng một
    số, chỉ tốn N lần thời gian — nên đó là lỗi tham số, không phải một lựa chọn hợp lệ.

    Khẳng định cả LÝ DO trong stderr, không chỉ `SystemExit`: argparse cũng thoát mã 2 khi không biết `--runs`,
    nên một ca chỉ bắt `SystemExit` sẽ xanh cả khi tính năng chưa tồn tại."""
    with pytest.raises(SystemExit):
        evals_main(argv)
    assert vi_sao in capsys.readouterr().err


def test_glob_khong_thoat_khoi_worktree(tmp_path):
    # audit 2026-09-23: `glob` đi thẳng vào `Path.glob` (chấp nhận `..`), `relative_to` chỉ so chuỗi nên
    # `root/../x` lọt qua cả SKIP_DIRS lẫn lọc file bí mật — đọc được repo khách và company.sqlite bên ngoài.
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    (ws.path.parent / "hang-xom.txt").write_text("SECRET_TOKEN=1\n", encoding="utf-8")
    wt = WorkspaceTools(ws)
    for g in ("../*", "../**/*", "sub/../../*"):
        assert "SECRET_TOKEN" not in wt.search("SECRET", g), g
        assert "hang-xom" not in wt.list_files(".", g), g


@pytest.mark.parametrize("destination", ["outside", ".git", ".aws", "nested/.git", ".venv"])
@pytest.mark.parametrize("operation", ["search", "list_files"])
def test_glob_rechecks_resolved_symlink_parent(tmp_path, destination, operation):
    root = tmp_path / "workspace"
    root.mkdir()
    target = tmp_path / "outside" if destination == "outside" else root / destination
    target.mkdir(parents=True)
    (target / "private.txt").write_text("PRIVATE_MARKER", encoding="utf-8")
    try:
        (root / "alias").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privileges unavailable")
    wt = WorkspaceTools(root)
    if operation == "search":
        assert "PRIVATE_MARKER" not in wt.search("PRIVATE_MARKER", "alias/*.txt")
    else:
        assert "private.txt" not in wt.list_files(glob="alias/*.txt")
