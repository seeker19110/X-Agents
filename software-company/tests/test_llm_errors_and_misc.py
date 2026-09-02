"""Bổ sung sau rà soát: đường lỗi của adapter (429/5xx/timeout), bus SQLite hai tiến trình, graph, demo."""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from company import demo
from company.events import Envelope
from company.graph import RESEARCH_ORDER, research_order
from company.llm import Completion, LLMError, OpenAICompatClient, Refused, Transient, with_retry
from company.registry import load_agents
from company.sqlite_bus import SQLiteBus


def _server(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def _client(url, **kw):
    from company.llm import LLMConfig
    cfg = LLMConfig(provider="openai", models={"strong": "m", "standard": "m"}, base_url=url)
    return OpenAICompatClient(cfg, sleep=lambda _s: None, **kw)


def _complete(c):
    return c.complete(system="s", user="u", schema={"type": "object"}, model_tier="standard")


class _Flaky(BaseHTTPRequestHandler):
    hits = 0
    def do_POST(self):
        type(self).hits += 1
        if type(self).hits < 3:
            self.send_response(429); self.end_headers(); self.wfile.write(b'{"error":"rate"}'); return
        body = json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 5, "completion_tokens": 1}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


class _AlwaysDown(_Flaky):
    def do_POST(self):
        self.send_response(503); self.end_headers(); self.wfile.write(b'{"error":"down"}')


class _BadRequest(_Flaky):
    def do_POST(self):
        self.send_response(400); self.end_headers(); self.wfile.write(b'{"error":"schema"}')


def test_rate_limit_is_retried_then_succeeds():
    _Flaky.hits = 0
    srv, url = _server(_Flaky)
    try:
        assert _complete(_client(url)).input_tokens == 5
        assert _Flaky.hits == 3, "429 phải được thử lại chứ không hỏng ngay"
    finally:
        srv.shutdown()


def test_server_error_gives_up_after_attempts_as_transient():
    srv, url = _server(_AlwaysDown)
    try:
        with pytest.raises(Transient):
            _complete(_client(url, attempts=2))
    finally:
        srv.shutdown()


def test_client_error_is_not_retried():
    """400 là lỗi của request, gọi lại cũng vậy — chỉ tốn token."""
    srv, url = _server(_BadRequest)
    try:
        with pytest.raises(LLMError) as e:
            _complete(_client(url, attempts=3))
        assert not isinstance(e.value, Transient)
    finally:
        srv.shutdown()


def test_with_retry_does_not_retry_refusal():
    calls = []
    def call():
        calls.append(1); raise Refused("từ chối")
    with pytest.raises(Refused):
        with_retry(call, attempts=4, sleep=lambda _s: None)
    assert len(calls) == 1


def test_with_retry_backs_off_between_attempts():
    waits: list[float] = []
    calls = []
    def call():
        calls.append(1); raise Transient("429")
    with pytest.raises(Transient):
        with_retry(call, attempts=3, sleep=waits.append)
    assert len(calls) == 3 and len(waits) == 2 and waits[1] > waits[0], "backoff phải tăng dần"


def test_completion_json_rejects_garbage():
    with pytest.raises(LLMError):
        Completion(text="không phải json", input_tokens=1, output_tokens=1, model="m").json()


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
