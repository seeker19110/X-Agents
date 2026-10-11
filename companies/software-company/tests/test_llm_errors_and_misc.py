"""Bổ sung sau rà soát: đường lỗi của adapter (429/5xx/timeout), bus SQLite hai tiến trình, graph, demo."""
import json
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from company import demo
from company.events import Envelope
from company.graph import RESEARCH_ORDER, research_order
from company.llm import (
    ClaudeCodeClient,
    Completion,
    LLMConfig,
    LLMError,
    OpenAICompatClient,
    Refused,
    RetryingClient,
    TransientError,
)
from company.registry import load_agents
from company.sqlite_bus import SQLiteBus


@contextmanager
def _server(handler_cls):
    """Server giả cho một test. `server_close()` bắt buộc: `shutdown()` chỉ dừng vòng lặp,
    socket lắng nghe vẫn mở và rò qua các test sau."""
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}"
    finally:
        srv.shutdown(); t.join(timeout=5); srv.server_close()


def _client(url, retries=3):
    from company.llm import LLMConfig
    cfg = LLMConfig(provider="openai", models={"strong": "m", "standard": "m"}, base_url=url)
    return RetryingClient(OpenAICompatClient(cfg), retries=retries, sleep=lambda _s: None)


def _complete(c):
    return c.complete(system="s", user="u", schema={"type": "object"}, model_tier="standard")


class _Handler(BaseHTTPRequestHandler):
    def _reply(self, code, body: bytes):
        """Đọc hết request body TRƯỚC khi trả lời, và luôn gửi Content-Length. Bỏ bước đọc thì
        lúc đóng socket còn dữ liệu chưa nhận, Windows gửi RST thay vì FIN và client đang đọc
        response bị ConnectionAbortedError — đỏ ngẫu nhiên khi máy đang tải."""
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


class _Flaky(_Handler):
    hits = 0
    def do_POST(self):
        type(self).hits += 1
        if type(self).hits < 3:
            return self._reply(429, b'{"error":"rate"}')
        self._reply(200, json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 5, "completion_tokens": 1}}).encode())


class _AlwaysDown(_Handler):
    def do_POST(self): self._reply(503, b'{"error":"down"}')


class _BadRequest(_Handler):
    def do_POST(self): self._reply(400, b'{"error":"schema"}')


def test_rate_limit_is_retried_then_succeeds():
    _Flaky.hits = 0
    with _server(_Flaky) as url:
        assert _complete(_client(url)).input_tokens == 5
        assert _Flaky.hits == 3, "429 phải được thử lại chứ không hỏng ngay"


def test_server_error_gives_up_after_attempts_as_transient():
    with _server(_AlwaysDown) as url, pytest.raises(TransientError):
        _complete(_client(url, retries=1))


def test_client_error_is_not_retried():
    """400 là lỗi của request, gọi lại cũng vậy — chỉ tốn token."""
    with _server(_BadRequest) as url:
        with pytest.raises(LLMError) as e:
            _complete(_client(url))
        assert not isinstance(e.value, TransientError)


class _Raising:
    """ModelClient giả chỉ để đo hành vi retry của RetryingClient."""
    def __init__(self, exc):
        self.exc, self.calls = exc, 0
    def complete(self, **kw):
        self.calls += 1
        raise self.exc


def test_retrying_client_does_not_retry_refusal():
    inner = _Raising(Refused("từ chối"))
    with pytest.raises(Refused):
        RetryingClient(inner, retries=3, sleep=lambda _s: None).complete(
            system="s", user="u", schema={}, model_tier="standard")
    assert inner.calls == 1, "model từ chối thì gọi lại cũng vậy, chỉ tốn token"


def test_retrying_client_backs_off_between_attempts():
    waits: list[float] = []
    inner = _Raising(TransientError("429"))
    with pytest.raises(TransientError):
        RetryingClient(inner, retries=2, sleep=waits.append).complete(
            system="s", user="u", schema={}, model_tier="standard")
    assert inner.calls == 3 and len(waits) == 2 and waits[1] > waits[0], "backoff phải tăng dần"


def test_retrying_client_retries_am_thi_vong_lap_rong_va_assert_no():
    """`retries=-1` (cấu hình lỗi, không nên xảy ra bình thường) → `range(self.retries+1)` rỗng, vòng lặp không
    chạy lần nào, rơi thẳng vào `assert last is not None` — bất biến nội bộ giữ nguyên: không âm thầm trả về
    kết quả rỗng, phải sập rõ ràng ngay tại nơi giả định bị vi phạm."""
    inner = _Raising(TransientError("429"))
    with pytest.raises(AssertionError):
        RetryingClient(inner, retries=-1, sleep=lambda _s: None).complete(
            system="s", user="u", schema={}, model_tier="standard")
    assert inner.calls == 0, "vòng lặp rỗng thì inner không được gọi lần nào"


def test_completion_json_rejects_garbage():
    with pytest.raises(LLMError):
        Completion(text="không phải json", input_tokens=1, output_tokens=1, model="m").json()


def test_find_codex_binary_fallback_ve_ten_tho_khi_khong_thay(monkeypatch):
    """Không có trên PATH thì trả về nguyên tên nhị phân — CLI sẽ tự báo lỗi rõ khi thật sự chạy, không phải lúc
    tìm đường dẫn."""
    import shutil as _shutil

    from company.llm import find_codex_binary
    monkeypatch.setattr(_shutil, "which", lambda b: None)
    assert find_codex_binary("codex-khong-ton-tai-xyz") == "codex-khong-ton-tai-xyz"


def test_codex_client_subprocess_that_tra_ve_stdout(tmp_path):
    """`_subprocess` mặc định của CodexClient chạy tiến trình con thật (dòng 807-818, thành công)."""
    from company.llm import CodexClient
    c = CodexClient(LLMConfig(provider="codex", models={"strong": "m", "standard": "m"}))
    out = c._subprocess([sys.executable, "-c", "print('hello')"], stdin="")
    assert out.strip() == "hello"
    with pytest.raises(LLMError, match="không tìm thấy"):
        c._subprocess(["khong-ton-tai-binary-xyz"], stdin="")
    with pytest.raises(LLMError, match="thoát mã"):
        c._subprocess([sys.executable, "-c", "import sys; sys.exit(1)"], stdin="")


def test_codex_client_bo_qua_dong_jsonl_hong_va_bao_chua_dang_nhap(tmp_path):
    """Dòng JSONL không phải JSON hợp lệ bị bỏ qua (dòng 845); lỗi có 'not logged in' báo rõ CODEX_HOME (dòng 861)."""
    from company.llm import CodexClient
    cfg = LLMConfig(provider="codex", models={"strong": "m", "standard": "m"})
    bad_line = '{khong phai json hop le\n{"type":"error","message":"not logged in, run codex login"}\n{"type":"turn.failed","error":{"message":"x"}}\n'
    c = CodexClient(cfg, runner=lambda a, s: bad_line)
    with pytest.raises(LLMError, match="chưa đăng nhập"):
        c.complete(system="s", user="u", schema={}, model_tier="strong")


def test_claude_code_client_subprocess_that_tra_ve_stdout(tmp_path):
    """`_subprocess` mặc định (không có `runner` giả) phải chạy tiến trình con thật và trả về stdout (dòng 672)."""
    from company.llm import ClaudeCodeClient
    c = ClaudeCodeClient(LLMConfig(provider="claude-code", models={"strong": "m", "standard": "m"}))
    out = c._subprocess([sys.executable, "-c", "print('{\"ok\": true}')"], stdin="")
    assert out.strip() == '{"ok": true}'


def test_claude_code_thoat_ma_1_phan_loai_theo_thong_diep_khong_theo_duoi_telemetry():
    """`claude -p` in JSON kết quả rồi thoát mã 1; đuôi JSON là telemetry chứa `depth_limit`/`concurrency_limit`.
    Soi đuôi tìm "limit" thì MỌI lỗi thành TransientError "hết quota" và routing lặp mãi (đo được 2026-09-05:
    20 phút retry mỗi 44s trong khi CLI gọi tay chạy bình thường). Phải đọc `result`/`api_error_status`."""
    from company.llm import ClaudeCodeClient, TransientError
    c = ClaudeCodeClient(LLMConfig(provider="claude-code", models={"strong": "m", "standard": "m"}))
    tail = '"refused":{"depth_limit":0,"concurrency_limit":0,"budget":0},"started_in_background":0,"max_depth":0'
    hard = ('{"type":"result","subtype":"error_during_execution","is_error":true,"api_error_status":null,'
            '"result":"Authentication failed. Please run /login",' + tail + "}")
    with pytest.raises(LLMError, match="Authentication failed") as ei:
        c._subprocess([sys.executable, "-c", f"import sys; print({hard!r}); sys.exit(1)"], stdin="")
    assert not isinstance(ei.value, TransientError), "lỗi xác thực không phải lỗi tạm thời"
    soft = ('{"type":"result","subtype":"error_during_execution","is_error":true,"api_error_status":429,'
            '"result":"Rate limited",' + tail + "}")
    with pytest.raises(TransientError, match="api_error_status=429"):
        c._subprocess([sys.executable, "-c", f"import sys; print({soft!r}); sys.exit(1)"], stdin="")
    with pytest.raises(LLMError, match="thoát mã 1: boom") as ei2:  # không có JSON: stderr như cũ
        c._subprocess([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(1)"], stdin="")
    assert not isinstance(ei2.value, TransientError)
    with pytest.raises(LLMError, match=r"thoát mã 1.*not json") as ei3:  # có `{` nhưng không phải JSON: rơi về đuôi output
        c._subprocess([sys.executable, "-c", "import sys; print('{not json'); sys.exit(1)"], stdin="")
    assert not isinstance(ei3.value, TransientError)


def test_retrying_client_bind_toolbox_chuyen_tiep_khi_inner_biet():
    class _WithBind(_Raising):
        def __init__(self):
            super().__init__(Refused("x")); self.bound = None
        def bind_toolbox(self, tb): self.bound = tb

    rc = RetryingClient(_WithBind())
    rc.bind_toolbox("hop-tool")
    assert rc.inner.bound == "hop-tool"
    rc2 = RetryingClient(_Raising(Refused("x")))   # inner không có bind_toolbox: không sập
    rc2.bind_toolbox("hop-tool")


# ---------- AnthropicClient.complete: SDK giả tối thiểu (không cần cài `anthropic`) ----------

class _FakeBlock:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items(): setattr(self, k, v)


class _FakeUsage:
    def __init__(self, input_tokens=10, output_tokens=2, cache_read_input_tokens=0, cache_creation_input_tokens=0):
        self.input_tokens = input_tokens; self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens; self.cache_creation_input_tokens = cache_creation_input_tokens


class _FakeMessage:
    def __init__(self, content, stop_reason="end_turn", model="claude-x", usage=None, stop_details=None):
        self.content, self.stop_reason, self.model = content, stop_reason, model
        self.usage = usage or _FakeUsage()
        self.stop_details = stop_details


class _FakeStream:
    def __init__(self, msg): self._msg = msg
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get_final_message(self): return self._msg


def _fake_anthropic_module(monkeypatch, msg=None, raise_=None):
    """Tiêm một module `anthropic` giả tối thiểu — đủ để `AnthropicClient.complete` đi trọn đường thật."""
    import sys
    import types
    fake = types.ModuleType("anthropic")

    class APIConnectionError(Exception): pass
    class APIStatusError(Exception):
        def __init__(self, message, status_code): super().__init__(message); self.message, self.status_code = message, status_code

    class _Messages:
        def stream(self, **kw):
            if raise_ is not None: raise raise_
            return _FakeStream(msg)

    class _Anthropic:
        def __init__(self, timeout=None): self.messages = _Messages()

    fake.Anthropic = _Anthropic; fake.APIConnectionError = APIConnectionError; fake.APIStatusError = APIStatusError
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return fake


def _anthropic_client(monkeypatch, **kw):
    from company.llm import AnthropicClient
    _fake_anthropic_module(monkeypatch, **kw)
    return AnthropicClient(LLMConfig(provider="anthropic", models={"strong": "m", "standard": "m"}))


def test_anthropic_complete_duong_thanh_cong_va_tool_call(monkeypatch):
    msg = _FakeMessage(content=[_FakeBlock("text", text="xin chào"),
                                _FakeBlock("tool_use", id="c1", name="read_file", input={"path": "x"})],
                       usage=_FakeUsage(input_tokens=100, output_tokens=5, cache_read_input_tokens=20))
    from company.tools import ToolSpec
    c = _anthropic_client(monkeypatch, msg=msg)
    out = c.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong",
                     tools=[ToolSpec("read_file", "d", {"type": "object"})])
    assert out.text == "xin chào" and out.tool_calls[0].name == "read_file" and out.tool_calls[0].args == {"path": "x"}
    assert out.cached_input_tokens == 20 and out.model == "claude-x"


def test_anthropic_complete_tu_choi_ném_refused(monkeypatch):
    msg = _FakeMessage(content=[], stop_reason="refusal",
                       stop_details=type("D", (), {"category": "vi_phạm"})())
    c = _anthropic_client(monkeypatch, msg=msg)
    with pytest.raises(Refused, match="từ chối"):
        c.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")


def test_anthropic_complete_loi_mang_thanh_transient(monkeypatch):
    c = _anthropic_client(monkeypatch)
    def boom(**kw): raise c._anthropic.APIConnectionError("đứt mạng")
    c._client.messages.stream = boom
    with pytest.raises(TransientError, match="lỗi mạng"):
        c.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")


def test_anthropic_complete_5xx_la_transient_4xx_la_llmerror(monkeypatch):
    c = _anthropic_client(monkeypatch)
    def boom_503(**kw): raise c._anthropic.APIStatusError("quá tải", status_code=503)
    c._client.messages.stream = boom_503
    with pytest.raises(TransientError, match="API 503"):
        c.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")

    def boom_400(**kw): raise c._anthropic.APIStatusError("schema sai", status_code=400)
    c._client.messages.stream = boom_400
    with pytest.raises(LLMError) as e:
        c.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")
    assert not isinstance(e.value, TransientError) and "API 400" in str(e.value)


# ---------- ClaudeCodeClient: đường lỗi của tiến trình con thật ----------

def _ccc(**kw):
    return ClaudeCodeClient(LLMConfig(provider="claude-code", models={"strong": "m", "standard": "m"}, **kw), timeout=5)


def test_claude_code_binary_khong_ton_tai_bao_loi_ro(monkeypatch):
    client = _ccc()
    def boom(*a, **kw):
        raise FileNotFoundError("no such file")
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(LLMError, match="không tìm thấy"):
        client._subprocess(["claude", "-p"], "stdin")


def test_claude_code_het_gio_la_transient(monkeypatch):
    client = _ccc()
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=5)
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(TransientError, match="quá 5"):
        client._subprocess(["claude", "-p"], "stdin")


def test_claude_code_qua_han_muc_la_transient_con_loi_khac_thi_khong(monkeypatch):
    client = _ccc()

    class _R:
        def __init__(self, code, err): self.returncode, self.stderr, self.stdout = code, err, ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _R(1, "Error: rate limit exceeded, retry later"))
    with pytest.raises(TransientError):
        client._subprocess(["claude", "-p"], "stdin")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _R(2, "unknown option '--foo'"))
    with pytest.raises(LLMError) as e:
        client._subprocess(["claude", "-p"], "stdin")
    assert not isinstance(e.value, TransientError)


def test_claude_code_json_hong_va_thieu_result():
    cfg = LLMConfig(provider="claude-code", models={"strong": "m", "standard": "m"})
    client = ClaudeCodeClient(cfg, runner=lambda a, s, cwd=None: "không phải JSON và cũng không có ngoặc")
    with pytest.raises(LLMError, match="không phải JSON"):
        client.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")
    client2 = ClaudeCodeClient(cfg, runner=lambda a, s, cwd=None: json.dumps({"stop_reason": "end_turn", "usage": {}}))
    with pytest.raises(LLMError, match="thiếu trường result"):
        client2.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")


def test_claude_code_subprocess_thanh_cong_tra_stdout(monkeypatch):
    """Đường thành công thật của `_subprocess` (không qua `runner` giả) — dòng `return r.stdout`."""
    client = _ccc()

    class _R:
        returncode = 0
        stdout = '{"result": "{}", "usage": {}}'
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _R())
    assert client._subprocess(["claude", "-p"], "stdin") == _R.stdout


def test_claude_code_parse_bao_loi_khi_co_ngoac_nhung_json_hong():
    """`out` có `{` nhưng nội dung sau đó không phải JSON hợp lệ — khác nhánh "không có `{` nào" ở trên."""
    cfg = LLMConfig(provider="claude-code", models={"strong": "m", "standard": "m"})
    client = ClaudeCodeClient(cfg, runner=lambda a, s, cwd=None: '{đây không phải JSON hợp lệ')
    with pytest.raises(LLMError, match="không phải JSON"):
        client.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")


# ---------- CodexClient: đường lỗi tiến trình con thật ----------

def _cxc(**kw):
    from company.llm import CodexClient
    return CodexClient(LLMConfig(provider="codex", models={"strong": "m", "standard": "m"}, **kw), binary="codex", timeout=5)


def test_codex_binary_khong_ton_tai_bao_loi_ro(monkeypatch):
    client = _cxc()
    def boom(*a, **kw):
        raise FileNotFoundError("no such file")
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(LLMError, match="không tìm thấy"):
        client._subprocess(["codex", "exec"], "stdin")


def test_codex_het_gio_la_transient(monkeypatch):
    client = _cxc()
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="codex", timeout=5)
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(TransientError, match="quá 5"):
        client._subprocess(["codex", "exec"], "stdin")


def test_codex_thoat_ma_khac_khong_bao_loi_ro(monkeypatch):
    client = _cxc()

    class _R:
        def __init__(self, code): self.returncode, self.stdout, self.stderr = code, "chi tiết stdout", "chi tiết stderr"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _R(1))
    with pytest.raises(LLMError, match="thoát mã 1"):
        client._subprocess(["codex", "exec"], "stdin")


def test_codex_parse_bo_qua_dong_khong_phai_json_va_bao_loi_dang_nhap(monkeypatch):
    """`complete` bỏ qua dòng rác không phải JSON (dòng 845) rồi báo lỗi đăng nhập rõ ràng (dòng 861)."""
    from company.llm import CodexClient
    out = ("{dòng bắt đầu bằng ngoặc nhưng không phải JSON hợp lệ\n"
           '{"type":"error","message":"not logged in, run `codex login` first"}\n'
           '{"type":"turn.failed","error":{"message":"x"}}\n')
    cfg = LLMConfig(provider="codex", models={"strong": "m", "standard": "m"})
    client = CodexClient(cfg, binary="codex", runner=lambda a, s: out)
    with pytest.raises(LLMError, match="chưa đăng nhập"):
        client.complete(system="s", user="u", schema={"type": "object"}, model_tier="strong")


def test_sqlite_bus_sees_events_written_by_another_process(tmp_path):
    db = tmp_path / "company.sqlite"
    bus = SQLiteBus(db)
    seen: list[str] = []
    bus.subscribe("audit-log", lambda e: seen.append(e.payload["action"]))
    code = (f"import sys; sys.path.insert(0, {str(tmp_path.parent)!r});"
            "from company.sqlite_bus import SQLiteBus; from company.events import Envelope;"
            f"b = SQLiteBus({str(db)!r});"
            "b.publish(Envelope(topic='audit-log', key='x', actor='x', payload={'actor': 'x', 'action': 'tien-trinh-khac'}))")
    subprocess.run([sys.executable, "-c", code], check=True, cwd="src", capture_output=True)
    assert seen == [], "chưa poll thì chưa thấy"
    new = bus.poll()
    assert [e.payload["action"] for e in new] == ["tien-trinh-khac"] and seen == ["tien-trinh-khac"]
    assert bus.poll() == [], "poll lần hai không lặp lại event cũ"


def test_sqlite_bus_survives_reopen_and_keeps_order(tmp_path):
    db = tmp_path / "b.sqlite"
    b1 = SQLiteBus(db)
    for i in range(5):
        b1.publish(Envelope(topic="audit-log", key="k", actor="a", payload={"actor": "a", "action": f"a{i}"}))
    b1.close()
    b2 = SQLiteBus(db)
    assert [e.payload["action"] for e in b2.replay(topic="audit-log")] == [f"a{i}" for i in range(5)]


def test_graph_order_references_real_agents():
    agents = load_agents()
    assert research_order(agents) == list(RESEARCH_ORDER)
    assert set(RESEARCH_ORDER) <= set(agents)


def test_graph_rejects_unknown_agent():
    with pytest.raises(ValueError, match="không tồn tại"):
        research_order({"intake": object()})


def test_demo_runs_full_lifecycle(capsys):
    demo.run()
    out = capsys.readouterr().out
    assert "TCK-1" in out and "TCK-2" in out, "demo chạy hết vòng đời hai ticket"


def test_codex_effort_none_khong_bi_doi_thanh_medium():
    """`effort: none` phải xuống CLI đúng là `none` — TẮT HẲN suy nghĩ.

    `_args` dùng `CODEX_EFFORT.get(effort, "medium")`, nên một giá trị hợp lệ mà THIẾU trong bảng sẽ bị âm thầm
    đổi thành `medium`: cấu hình nói một đằng, CLI chạy một nẻo, và không có lỗi nào báo ra.

    Đo được 2026-09-05 trên gpt-5.6-terra: `none` cho `reasoning_output_tokens: 0` và 18 token đầu ra; còn
    `minimal` bị model TỪ CHỐI (HTTP 400 `unsupported_value`, chỉ nhận none/low/medium/high/xhigh/max) — nên
    `minimal` giữ trong bảng cho model cũ, không phải là lựa chọn cho model này."""
    from company.llm import CODEX_EFFORT, CodexClient

    assert CODEX_EFFORT["none"] == "none", "thiếu `none` là mọi cấu hình tắt-suy-nghĩ bị đổi thành medium"

    cfg = LLMConfig(provider="codex", models={"strong": "m"}, effort={"strong": "none"})
    c = CodexClient(cfg, runner=lambda a, s: "")
    assert "model_reasoning_effort=none" in c._args("m", cfg.effort["strong"])
    # giá trị lạ vẫn rơi về medium (giữ nguyên hành vi cũ, không im lặng hỏng)
    assert "model_reasoning_effort=medium" in c._args("m", "khong-ton-tai")
