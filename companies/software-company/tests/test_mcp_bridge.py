"""ADR-0024: cầu MCP đưa bảng tool của công ty vào CLI `claude -p` mà tool vẫn chạy trong sandbox `tools.py`.
Không cần CLI thật: test nói JSON-RPC trực tiếp với tiến trình MCP con, và thay `claude` bằng hàm giả."""
from __future__ import annotations

import contextlib
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from company.bus import InMemoryBus
from company.llm import ClaudeCodeClient, LLMConfig, LLMError, cli_lacks_mcp
from company.mcp_bridge import SERVER_NAME, ProxyServer, ToolBridge, tool_full_name
from company.runner import AgentRunner
from company.tools import ToolBox, ToolSpec, WorkspaceTools
from company.workspace import TicketWorkspace
from test_tools_and_agentic import _init_repo, _pr, _task_env

# `token_estimate` (p3.2a) là số đo CHẨN ĐOÁN, phát ở mọi bước agent: sai số giữa ước lượng của `fit` và
# token thật trong `usage`. Các khẳng định dưới đây đo TRÌNH TỰ SỰ VIỆC của luồng, nên lọc nó ra —
# chính nó được đo riêng ở `test_adr0012.py::test_runner_audits_token_estimate_sau_moi_buoc`.
DIAG = {"token_estimate"}


def _box() -> ToolBox:
    tb = ToolBox()
    seen: list[str] = []
    tb.add(ToolSpec("echo", "Trả lại chữ", {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}),
           lambda x: (seen.append(x), f"đã nhận {x}")[1])
    tb.seen = seen  # type: ignore[attr-defined]
    return tb


# ---------- socket phía cha ----------

def test_bridge_serves_tool_list_and_calls_and_rejects_wrong_token():
    tb = _box()
    with ToolBridge(tb) as br:
        px = ProxyServer(br.port, br.token)
        assert [t["name"] for t in px.ask({"op": "list"})["tools"]] == ["echo"]
        assert px.ask({"op": "call", "name": "echo", "args": {"x": "A"}}) == {"ok": True, "result": "đã nhận A"}
        # tool chạy ở tiến trình cha → vết gọi vào đúng ToolBox của runner (audit + metrics)
        assert tb.summary() == {"echo": 1} and tb.seen == ["A"]  # type: ignore[attr-defined]
        assert not px.ask({"op": "call", "name": "khong-co", "args": {}})["ok"]   # tool lạ: lỗi, không sập cầu
        assert px.ask({"op": "lung-tung"})["error"].startswith("op lạ")
        assert ProxyServer(br.port, "token-sai").ask({"op": "list"}) == {"ok": False, "error": "token sai"}
        port, token = br.port, br.token
    # đóng rồi thì không ai gọi được nữa (socket chỉ sống trong lúc CLI chạy)
    assert not ProxyServer(port, token).ask({"op": "list"}).get("ok")


def test_bridge_port_truoc_khi_mo_bao_loi_va_exit_hai_lan_khong_sap():
    br = ToolBridge(_box())
    with pytest.raises(RuntimeError, match="chưa mở"):
        _ = br.port
    br.__exit__()   # chưa từng __enter__: server/thread vẫn None, không được sập
    with br:
        pass
    br.__exit__()   # exit lần hai sau khi đã đóng: cũng không được sập


def test_bridge_config_names_tools_and_removes_secret_file_after_use():
    with ToolBridge(_box()) as br:
        assert br.allowed_tools() == tool_full_name("echo")
        with br.config_file() as p:
            cfg = json.loads(p.read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]
            assert cfg["args"][:2] == ["-m", "company.mcp_bridge"] and br.token in cfg["args"]
            assert Path(cfg["env"]["PYTHONPATH"], "company", "mcp_bridge.py").exists()
        assert not p.exists(), "file cấu hình mang token phải bị xoá ngay sau lượt gọi"


# ---------- tiến trình MCP con thật, nói JSON-RPC qua stdio ----------

def test_real_subprocess_speaks_mcp_and_reaches_the_parent_toolbox(tmp_path):
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    with ToolBridge(tb) as br, br.config_file() as cfg_path:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]
        # env=cfg["env"] NGUYÊN VĂN, không thêm gì: đúng thứ `--mcp-config` hứa với CLI. Trước đây
        # test thêm `PATH: ""` để chứng minh không cần PATH, nhưng như thế lại giấu mất một yêu cầu
        # thật — trên Windows thiếu `SystemRoot` thì Winsock không nạp được provider và socket về
        # tiến trình cha ném WinError 10106. Chạy đúng env đã khai mới bắt được thiếu sót đó.
        proc = subprocess.Popen([cfg["command"], *cfg["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, encoding="utf-8", env=cfg["env"])
        def rpc(method, params=None, mid=1):
            assert proc.stdin and proc.stdout
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())["result"]
        try:
            assert rpc("initialize")["serverInfo"]["name"] == SERVER_NAME
            names = [t["name"] for t in rpc("tools/list", mid=2)["tools"]]
            assert names == ["read_file", "write_file", "delete_file", "list_files", "search", "run"]
            r = rpc("tools/call", {"name": "read_file", "arguments": {"path": "mod.py"}}, mid=3)
            assert "def add" in r["content"][0]["text"] and not r["isError"]
            # sandbox không đổi: file bí mật vẫn bị chặn, và chặn ở TIẾN TRÌNH CHA
            r = rpc("tools/call", {"name": "read_file", "arguments": {"path": ".env"}}, mid=4)
            assert "file bí mật" in r["content"][0]["text"] and "sk_live_secret" not in r["content"][0]["text"]
            # ghi qua MCP là ghi thật vào worktree
            rpc("tools/call", {"name": "write_file", "arguments": {"path": "f.py", "content": "F = 1\n"}}, mid=5)
            assert (ws.path / "f.py").read_text(encoding="utf-8") == "F = 1\n"
        finally:
            assert proc.stdin
            proc.stdin.close(); proc.wait(timeout=10)
            if proc.stdout: proc.stdout.close()   # ống stdout cũng phải đóng, nếu không rò file descriptor
    assert tb.summary() == {"read_file": 2, "write_file": 1}


def test_proxy_answers_notifications_and_unknown_methods():
    px = ProxyServer(1, "t")
    assert px.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert px.handle({"jsonrpc": "2.0", "id": 9, "method": "ping"})["result"] == {}
    assert px.handle({"jsonrpc": "2.0", "id": 9, "method": "la/hoac"})["error"]["code"] == -32601
    # cha đã đóng: lỗi quay về model như dữ liệu, không làm sập server
    r = px.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "echo", "arguments": {}}})
    assert r["result"]["isError"] and "không nối được" in r["result"]["content"][0]["text"]


# ---------- adapter: một tiến trình CLI cho cả vòng tool ----------

def _cc(runner, **kw):
    kw.setdefault("mcp_tools", True)
    return ClaudeCodeClient(LLMConfig(provider="claude-code", models={"strong": "m", "standard": "m"}, **kw), runner=runner)


def test_runner_binds_toolbox_and_cli_runs_the_whole_tool_loop_once(tmp_path):
    """Cả vòng tool nằm trong MỘT lời gọi CLI (nên có prompt cache), tool vẫn chạy trong sandbox của công ty."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    seen: list[list[str]] = []

    def runner(args, stdin, cwd=None):
        seen.append(args)
        assert cwd == str(ws.path), "CLI chạy trong worktree của ticket"
        i = args.index("--mcp-config")
        cfg = json.loads(Path(args[i + 1]).read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]
        px = ProxyServer(int(cfg["args"][cfg["args"].index("--port") + 1]), cfg["args"][cfg["args"].index("--token") + 1])
        # đóng vai CLI: gọi tool qua cầu rồi mới chốt JSON
        px.ask({"op": "call", "name": "read_file", "args": {"path": "mod.py"}})
        px.ask({"op": "call", "name": "write_file", "args": {"path": "feature.py", "content": "F = 1\n"}})
        return json.dumps({"result": json.dumps(_pr({"ticket_id": "T1"})), "stop_reason": "end_turn",
                           "usage": {"input_tokens": 20, "cache_read_input_tokens": 15, "output_tokens": 5}})

    bus = InMemoryBus()
    g = AgentRunner(bus, _cc(runner)).generate("builder", _task_env(), "pull-requests", tools=tb)
    assert (ws.path / "feature.py").read_text(encoding="utf-8") == "F = 1\n"
    assert len(seen) == 1 and g.turns == 1, "cả vòng tool chỉ tốn một tiến trình CLI"
    assert g.tool_calls == {"read_file": 1, "write_file": 1}   # đếm từ ToolBox thật, không từ lời khai của model
    args = seen[0]
    assert "--strict-mcp-config" in args, "không mở tool riêng của CLI"
    assert "--restricted" in args, "bỏ qua settings user/project: plugin/hook của máy không chen vào lượt agent"
    assert args[args.index("--tools") + 1] == "", "tắt hẳn tool gốc của CLI: chỉ còn tool MCP của công ty"
    assert "Read(**/.env)" in args[args.index("--settings") + 1], "deny file bí mật là lớp chặn thứ hai"
    assert args[args.index("--allowedTools") + 1] == ",".join(tool_full_name(n) for n in
                                                              ["read_file", "write_file", "delete_file", "list_files", "search", "run"])
    assert [e.payload["action"] for e in bus.replay(topic="audit-log") if e.payload["action"] not in DIAG] == ["tools_used", "tools_trace"]
    ev = json.loads(next(iter(bus.replay(topic="audit-log"))).payload["evidence"])
    assert ev["calls"] == {"read_file": 1, "write_file": 1}
    tr = json.loads(next(e.payload["evidence"] for e in bus.replay(topic="audit-log") if e.payload["action"] == "tools_trace"))
    assert tr["mode"] == "mcp" and [c["name"] for c in tr["calls"]] == ["read_file", "write_file"]


def test_old_cli_falls_back_to_cli_tools_or_says_why(tmp_path):
    """CLI cũ không biết `--mcp-config`: lùi sang chế độ tool CLI (ADR-0023) nếu backend có bật, không thì báo rõ."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    modes: list[str] = []

    def runner(args, stdin, cwd=None):
        if "--mcp-config" in args:
            modes.append("mcp")
            raise LLMError("claude -p thoát mã 1: error: unknown option '--mcp-config'")
        modes.append("cli")
        return json.dumps({"result": json.dumps(_pr({"ticket_id": "T1"})), "stop_reason": "end_turn", "usage": {}})

    tb = WorkspaceTools(ws).toolbox()
    client = _cc(runner, cli_tools=True)
    client.bind_toolbox(tb)
    c = client.complete(system="s", user="u", schema={}, model_tier="strong", tools=tb.specs(), workdir=tb.root)
    assert modes == ["mcp", "cli"] and client.cfg.mcp_tools is False and c.json()["ticket_id"] == "T1"


def test_loi_khac_trong_mcp_khong_phai_cli_cu_thi_nem_thang(tmp_path):
    """LLMError ở lượt MCP KHÔNG phải "CLI không biết --mcp-config" (vd. hết hạn mức) phải ném thẳng lên, không
    được hiểu nhầm là CLI cũ rồi lặng lẽ lùi sang chế độ CLI-tools."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()

    def runner(args, stdin, cwd=None):
        raise LLMError("You've hit your usage limit")

    tb = WorkspaceTools(ws).toolbox()
    client = _cc(runner, cli_tools=True)
    client.bind_toolbox(tb)
    with pytest.raises(LLMError, match="usage limit"):
        client.complete(system="s", user="u", schema={}, model_tier="strong", tools=tb.specs(), workdir=tb.root)
    assert client.cfg.mcp_tools is True, "không phải lỗi CLI cũ thì không được tắt mcp_tools"

    # không bật cli_tools thì không im lặng bỏ tool: lỗi nói đúng việc phải làm
    only_mcp = _cc(lambda a, s, cwd=None: (_ for _ in ()).throw(LLMError("unknown option '--mcp-config'")))
    only_mcp.bind_toolbox(tb)
    with pytest.raises(LLMError, match="không hỗ trợ `--mcp-config`"):
        only_mcp.complete(system="s", user="u", schema={}, model_tier="strong", tools=tb.specs(), workdir=tb.root)
    assert cli_lacks_mcp("unknown option '--mcp-config'") and not cli_lacks_mcp("You've hit your usage limit")


def test_mcp_needs_binding_and_config_flag(tmp_path):
    """Không bind ToolBox (gọi ngoài vòng tool) hoặc không bật `mcp_tools` thì không im lặng bỏ qua tool."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws).toolbox()
    ok = json.dumps({"result": "{}", "stop_reason": "end_turn", "usage": {}})
    unbound = _cc(lambda a, s, cwd=None: ok)
    with pytest.raises(LLMError, match="chưa bind ToolBox"):
        unbound.complete(system="s", user="u", schema={}, model_tier="strong", tools=tb.specs(), workdir=tb.root)
    off = _cc(lambda a, s, cwd=None: ok, mcp_tools=False)
    off.bind_toolbox(tb)
    with pytest.raises(LLMError, match="mcp_tools"):
        off.complete(system="s", user="u", schema={}, model_tier="strong", tools=tb.specs(), workdir=tb.root)
    # runner gỡ bind sau vòng tool → lượt sau không còn cầu nào mở
    bound = _cc(lambda a, s, cwd=None: ok)
    bound.bind_toolbox(tb); bound.bind_toolbox(None)
    with pytest.raises(LLMError, match="chưa bind ToolBox"):
        bound.complete(system="s", user="u", schema={}, model_tier="strong", tools=tb.specs(), workdir=tb.root)


@pytest.mark.skipif(sys.platform == "win32", reason="đường dẫn socket khác trên Windows CI")
def test_bridge_binds_loopback_only():
    with ToolBridge(_box()) as br:
        assert br._server is not None and br._server.server_address[0] == "127.0.0.1"


def test_proxy_handle_initialize_and_tools_list_in_process():
    """`test_proxy_answers_notifications_and_unknown_methods` không gọi `initialize`/`tools/list` thành công —
    bù ở đây, nói thẳng với `ProxyServer.handle` trong tiến trình test (subprocess không tính vào coverage)."""
    with ToolBridge(_box()) as br:
        px = ProxyServer(br.port, br.token)
        r = px.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert r["result"]["serverInfo"] == {"name": SERVER_NAME, "version": "1.0.0"}
        assert r["result"]["protocolVersion"]
        r = px.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert r["result"]["tools"][0]["name"] == "echo"
        assert r["result"]["tools"][0]["inputSchema"]["type"] == "object"


def test_proxy_tools_list_lien_lac_that_bai_tra_ve_loi_jsonrpc():
    """Cha đã đóng (hoặc token sai): `tools/list` phải trả lỗi JSON-RPC, không sập server con."""
    px = ProxyServer(1, "token-khong-ton-tai")
    r = px.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r["error"]["code"] == -32603
    assert "không nối được" in r["error"]["message"]


def test_socket_dong_goi_lon_hon_line_max_bi_ngat():
    """Dòng gửi lên socket vượt trần `LINE_MAX` phải bị ngắt kết nối, không được xử lý tiếp (dòng 80)."""
    from company import mcp_bridge as mb

    with ToolBridge(_box()) as br:
        with socket.create_connection((br.host, br.port), timeout=5) as s:
            huge = b"x" * (mb.LINE_MAX + 10) + b"\n"
            s.sendall(huge)
            s.shutdown(socket.SHUT_WR)
            assert s.recv(65536) == b""   # server đóng kết nối mà không trả lời


def _one_shot_server(respond, *, close=True):
    """Server TCP một lần, tự chọn cổng: nhận kết nối, **đọc hết request của client**, gọi `respond(conn)` rồi
    (mặc định) đóng. Trả `(port, da_doc)` — `da_doc` là list nhận đúng những byte request đã đọc.

    Đọc request trước khi đóng KHÔNG phải trang trí, nó là điều kiện để ca test đo đúng thứ nó định đo:
    đóng một socket khi buffer nhận còn dữ liệu chưa đọc thì TCP gửi **RST** thay vì FIN. Winsock khi nhận RST
    thì vứt luôn dữ liệu đã đệm, nên `recv()` của client ném `ConnectionReset/Aborted` thay vì trả 200 byte —
    ca test thấy lỗi kết nối chứ không thấy `trả lời quá dài`. Linux khoan dung hơn (vẫn trả dữ liệu đã đệm sau
    RST) nên chỉ Windows đỏ, và đỏ theo kiểu lúc được lúc không. Server thật (`ToolBridge`) luôn đọc request
    trước khi trả lời, nên đọc ở đây cũng là làm server giả giống server thật.

    `close=False`: để client tự đóng khi đọc xong."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    da_doc: list[bytes] = []
    def run():
        conn, _ = srv.accept()
        try:
            da_doc.append(conn.recv(65536))
            respond(conn)
        finally:
            if close: conn.close()
            srv.close()
    threading.Thread(target=run, daemon=True).start()
    return port, da_doc


def test_ask_tra_loi_qua_line_max_thi_bao_loi_thay_vi_doc_het(monkeypatch):
    """Phản hồi vượt `LINE_MAX` (server hỏng hoặc bị lừa) → `ask()` trả lỗi ngay khi vượt trần, không đọc tiếp
    tới khi hết bộ nhớ. Hạ `LINE_MAX` xuống nhỏ hẳn để test không phải truyền thật hàng MB qua socket (dễ bị
    RST giữa chừng trong sandbox mạng hạn chế, không liên quan tới điều đang test)."""
    from company import mcp_bridge as mb
    monkeypatch.setattr(mb, "LINE_MAX", 64)
    port, da_doc = _one_shot_server(lambda conn: conn.sendall(b"x" * 200))
    r = ProxyServer(port, "tok", timeout=10).ask({"op": "list"})
    assert r == {"ok": False, "error": "trả lời quá dài"}
    # Bất biến giữ ca test này khỏi RST trên Windows: server giả phải ĐỌC request trước khi đóng, nếu không
    # `close()` với buffer nhận còn dữ liệu sẽ gửi RST và client thấy lỗi kết nối thay vì lỗi độ dài.
    assert da_doc and da_doc[0].startswith(b'{"op": "list"'), "server giả phải đọc hết request trước khi đóng"


def test_ask_server_dong_ket_noi_giua_chung_khong_co_dong_moi():
    """Server đóng kết nối giữa chừng (chưa gửi `\\n`) → `recv()` trả rỗng, vòng đọc dừng bằng `break`; buf dở
    dang không parse được JSON → lỗi kết nối, không sập."""
    port, _ = _one_shot_server(lambda conn: conn.sendall(b'{"incomplete"'))   # không \n, rồi đóng
    r = ProxyServer(port, "tok", timeout=10).ask({"op": "list"})
    assert r["ok"] is False


def test_socket_gui_json_hong_bi_ngat_khong_sap_server():
    """Dòng không phải JSON hợp lệ (hoặc không giải mã được UTF-8) phải bị ngắt kết nối êm (dòng 83-84)."""
    with ToolBridge(_box()) as br:
        with socket.create_connection((br.host, br.port), timeout=5) as s:
            s.sendall(b"khong phai json {{{\n")
            s.shutdown(socket.SHUT_WR)
            assert s.recv(65536) == b""
        # server vẫn sống, phục vụ kết nối tiếp theo bình thường
        px = ProxyServer(br.port, br.token)
        assert px.ask({"op": "list"})["ok"]


def test_force_utf8_stdio_bo_qua_stream_khong_co_reconfigure(monkeypatch):
    """Stream bị thay bằng thứ không có `reconfigure` (vd. trong test) thì bỏ qua, không ném lỗi."""
    from company import mcp_bridge as mb

    class NoReconfigure:
        pass

    monkeypatch.setattr(mb.sys, "stdin", NoReconfigure())
    monkeypatch.setattr(mb.sys, "stdout", NoReconfigure())
    mb.force_utf8_stdio()   # không được ném AttributeError


def test_force_utf8_stdio_goi_reconfigure_khi_co():
    from company import mcp_bridge as mb

    calls: list[dict] = []

    class FakeStream:
        def reconfigure(self, **kw):
            calls.append(kw)

    fake_in, fake_out = FakeStream(), FakeStream()
    with contextlib.ExitStack() as stack:
        stack.enter_context(_patched(mb, "stdin", fake_in))
        stack.enter_context(_patched(mb, "stdout", fake_out))
        mb.force_utf8_stdio()
    assert calls == [{"encoding": "utf-8", "errors": "replace"}] * 2


@contextlib.contextmanager
def _patched(mod, attr, value):
    orig = getattr(mod.sys, attr)
    setattr(mod.sys, attr, value)
    try:
        yield
    finally:
        setattr(mod.sys, attr, orig)


def test_main_parses_argv_and_runs_proxy_until_stdin_closes(monkeypatch):
    """`main()` đọc `--port`/`--token`, ép UTF-8, và chạy `ProxyServer.run` tới khi stdin đóng."""
    import io as _io

    from company import mcp_bridge as mb

    fake_stdin = _io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n")
    fake_stdout = _io.StringIO()
    monkeypatch.setattr(mb.sys, "stdin", fake_stdin)
    monkeypatch.setattr(mb.sys, "stdout", fake_stdout)

    rc = mb.main(["--port", "1", "--token", "t"])

    assert rc == 0
    assert json.loads(fake_stdout.getvalue())["result"] == {}


def test_main_entrypoint_dung_lam_module(tmp_path):
    """Chạy `python -m company.mcp_bridge` với stdin rỗng phải thoát mã 0 ngay (đường `__main__`)."""
    import os as _os

    root = str(Path(__file__).resolve().parents[1] / "src")
    env = dict(_os.environ, PYTHONPATH=root)
    proc = subprocess.run([sys.executable, "-m", "company.mcp_bridge", "--port", "1", "--token", "t"],
                          input="", capture_output=True, text=True, timeout=10, env=env)
    assert proc.returncode == 0, proc.stderr


# ---------- bảng mã: kênh stdio phải sống được trên console không phải UTF-8 ----------

def test_ghi_duoc_thong_diep_tieng_viet_ra_stdout_cp1252():
    """Trên Windows stdio của tiến trình con mặc định là cp1252, mà mọi thông điệp của repo đều là
    tiếng Việt — nên một lượt trả về chữ có dấu từng giết tiến trình con và kéo sập cả chế độ
    `mcp_tools: true`. Test này chạy được trên mọi OS vì tự dựng stream cp1252."""
    import io as _io

    out = _io.TextIOWrapper(_io.BytesIO(), encoding="cp1252", newline="")
    src = _io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "phuong-thuc-la"}) + "\n")

    ProxyServer(1, "token").run(stdin=src, stdout=out)   # không được ném UnicodeEncodeError

    out.flush()
    raw = out.buffer.getvalue().decode("ascii")           # thuần ASCII: đó chính là điều cần chứng minh
    assert json.loads(raw)["error"]["message"] == "method lạ: phuong-thuc-la"


def test_run_bo_qua_dong_trong_va_json_hong_roi_tra_loi_dong_hop_le():
    """`ProxyServer.run` phải bỏ qua dòng trắng và dòng JSON hỏng (không phải dict), rồi vẫn trả lời dòng hợp lệ tiếp theo."""
    import io as _io

    out = _io.StringIO()
    src = _io.StringIO("\n" + "khong phai json {{{\n" + "[1, 2]\n" +
                       json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n")
    ProxyServer(1, "token").run(stdin=src, stdout=out)
    assert json.loads(out.getvalue())["result"] == {}


def test_run_bo_qua_notification_khong_id_roi_van_tra_loi_dong_sau():
    """Notification JSON-RPC (không có `id`, vd. `notifications/initialized`) không được trả lời — `handle()`
    trả None, `run()` không ghi gì và đọc tiếp dòng sau."""
    import io as _io

    out = _io.StringIO()
    src = _io.StringIO(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n" +
                       json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n")
    ProxyServer(1, "token").run(stdin=src, stdout=out)
    lines = [ln for ln in out.getvalue().splitlines() if ln]
    assert len(lines) == 1 and json.loads(lines[0])["result"] == {}


def test_khung_tra_loi_khong_co_byte_ngoai_ascii():
    """Đường dây phải thuần ASCII bất kể nội dung: đó là thứ khiến nó không phụ thuộc bảng mã console."""
    import io as _io

    out = _io.StringIO()
    src = _io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 7, "method": "khong-co-đâu"}) + "\n")
    ProxyServer(1, "token").run(stdin=src, stdout=out)
    raw = out.getvalue()
    assert raw.isascii(), raw
    assert "khong-co-đâu" in json.loads(raw)["error"]["message"]   # vẫn giải mã lại nguyên vẹn


# ---------- môi trường tiến trình con ----------

def test_mcp_config_khai_du_moi_thu_tien_trinh_con_can(tmp_path):
    """`--mcp-config` phải tự đủ: đặc tả MCP không hứa client giữ lại biến môi trường nào."""
    br = ToolBridge(ToolBox([(ToolSpec("echo", "vọng lại", {"type": "object"}), lambda **kw: "ok")]))
    with br:
        env = br.mcp_config()["mcpServers"][SERVER_NAME]["env"]
    assert env["PYTHONIOENCODING"] == "utf-8"
    if sys.platform == "win32":
        # Thiếu SystemRoot thì Winsock ném WinError 10106 và cầu không nối được về tiến trình cha.
        assert env.get("SystemRoot"), env


def test_platform_env_chi_them_bien_tren_windows(monkeypatch):
    from company import mcp_bridge as mb

    monkeypatch.setattr(mb.sys, "platform", "linux")
    assert mb.platform_env() == {}

    monkeypatch.setattr(mb.sys, "platform", "win32")
    monkeypatch.setattr(mb.os, "environ", {"SystemRoot": r"C:\Windows"})
    assert mb.platform_env() == {"SystemRoot": r"C:\Windows"}

    monkeypatch.setattr(mb.os, "environ", {})       # biến không có thì bỏ qua, không ném KeyError
    assert mb.platform_env() == {}


def test_mcp_tran_thoi_gian_cli_chua_du_cho_tool_chay_lau(tmp_path, monkeypatch):
    """Lượt MCP gói CẢ vòng tool trong một tiến trình `claude -p`, nên trần thời gian của tiến trình đó phải chứa được
    thời gian tool chạy, không chỉ thời gian model nghĩ. Trước đây trần cứng 900s trong khi một lần `run test` được
    phép 600s: builder chạy test hai lần là bị giết, mọi việc trong lượt mất trắng, rồi thử lại y hệt. Đo được
    2026-09-24 (CAMPUS-UNI/TCK-002): 4 lượt × 900s bị giết liên tiếp, bus im lặng 1 giờ, 0 event."""
    ws = TicketWorkspace(_init_repo(tmp_path / "repo"), "T1", base="main"); ws.create()
    tb = WorkspaceTools(ws, timeout=600).toolbox()
    seen: list[float] = []

    def fake_run(args, **kw):
        seen.append(kw["timeout"])
        out = json.dumps({"result": json.dumps(_pr({"ticket_id": "T1"})), "stop_reason": "end_turn", "usage": {}})
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = ClaudeCodeClient(LLMConfig(provider="claude-code", models={"strong": "m"}, mcp_tools=True))
    client.bind_toolbox(tb)
    client.complete(system="s", user="u", schema={}, model_tier="strong", tools=tb.specs(), workdir=tb.root)
    client.complete(system="s", user="u", schema={}, model_tier="strong")   # không tool: trần cũ, không rò sang
    assert seen == [900.0 + 3 * 600, 900.0]
