"""Span ở hai ranh giới của company (ADR-0009 `p3.1b`): `runner.step` quanh `generate`, `llm.complete` quanh
đúng lời gọi `client.complete` — cộng quan hệ cha–con với `tool.call` của core.

Hai ca đáng giá nhất là chiều ngược: (1) không cấu hình sink thì `generate` cho ra `Generated` y hệt bản không
span; (2) một lượt qua `RoutingClient(RetryingClient(FakeClient))` chỉ được đếm MỘT span — đây là ca chứng minh
quyết định 3 của ADR (chèn phía gọi, không phía client).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from xagents_core.observe import MemorySink
from xagents_core.routing import Backend, RoutingClient

from company.blackboard import Blackboard
from company.bus import InMemoryBus
from company.events import Envelope, PullRequest
from company.llm import FakeClient, RetryingClient
from company.runner import AgentRunner
from company.tools import ToolBox, ToolCall, ToolSpec

PAYLOAD = {"ticket_id": "TCK-1", "source": "reviewer", "verdict": "pass"}


def _env(tid: str = "TCK-1") -> Envelope:
    return Envelope(topic="pull-requests", key=tid, actor="builder", payload=PullRequest(
        ticket_id=tid, branch=f"ticket/{tid}", pr_ref="#1", local_checks={"lint": True, "tests": True}).model_dump())


def _toolbox(sink: Any = None) -> ToolBox:
    b = ToolBox(sink=sink)
    b.add(ToolSpec(name="read_file", description="", parameters={"properties": {"path": {"type": "string"}},
                                                                 "required": ["path"]}), lambda path: f"nội dung {path}")
    return b


def _runner(client: Any, sink: Any = None) -> AgentRunner:
    bus = InMemoryBus()
    r = AgentRunner(bus, client, blackboard=Blackboard(bus))
    r.sink = sink
    return r


def _names(sink: MemorySink) -> list[str]:
    return [s.name for s in sink.spans]


# ---------- một lượt không tool ----------

def test_generate_sinh_runner_step_bao_llm_complete():
    sink = MemorySink()
    g = _runner(FakeClient(responses=[PAYLOAD]), sink).generate("qa", _env(), "review-results")
    assert g.payloads == [PAYLOAD]
    assert _names(sink) == ["llm.complete", "runner.step"], "con đóng trước cha"
    llm, step = sink.spans
    assert llm.parent is step and step.parent is None
    assert step.attrs["agent"] == "qa" and step.attrs["topic_out"] == "review-results"
    assert llm.attrs["agent"] == "qa" and llm.attrs["model"] == g.model
    assert llm.attrs["input_tokens"] > 0 and llm.attrs["output_tokens"] > 0
    assert step.duration_ms > 0 and llm.duration_ms > 0


def test_khong_dem_trung_qua_chuoi_client_long_nhau():
    """Chiều ngược quyết định 3: routing → retry → fake là BA lớp `complete`, vẫn phải đúng MỘT span."""
    fake = FakeClient(responses=[PAYLOAD])
    client = RoutingClient(backends=[Backend(name="b1", client=RetryingClient(fake))])
    sink = MemorySink()
    _runner(client, sink).generate("qa", _env(), "review-results")
    assert _names(sink).count("llm.complete") == 1


def test_llm_error_ghi_error_vao_span_va_van_nem():
    sink = MemorySink()
    with pytest.raises(Exception, match="hết câu trả lời"):
        _runner(FakeClient(responses=[]), sink).generate("qa", _env(), "review-results")
    llm = next(s for s in sink.spans if s.name == "llm.complete")
    assert "LLMError" in llm.error, "span sống chung với nhánh audit `llm_error`, không thay nó"
    assert next(s for s in sink.spans if s.name == "runner.step").error


# ---------- vòng tool ----------

def _th(n_tool_turns: int):
    def th(msgs, tools):
        turns = sum(1 for m in msgs if m["role"] == "assistant")
        return [ToolCall(id=f"c{turns}", name="read_file", args={"path": f"f{turns}.py"})] if turns < n_tool_turns else []
    return th


def test_ba_luot_tool_sinh_ba_span_llm_complete_va_cay_dung():
    sink = MemorySink()
    client = FakeClient(responses=[PAYLOAD], tool_handler=_th(2))
    r = _runner(client, sink)
    g = r.generate("qa", _env(), "review-results", tools=_toolbox(sink))
    assert g.turns == 3
    assert _names(sink).count("llm.complete") == 3, "mỗi lượt MỘT span, không phải một span cho cả vòng"
    step = next(s for s in sink.spans if s.name == "runner.step")
    turns = [s for s in sink.spans if s.name == "llm.complete"]
    calls = [s for s in sink.spans if s.name == "tool.call"]
    assert all(t.parent is step for t in turns)
    assert len(calls) == 2 and [c.parent for c in calls] == turns[:2], "tool của lượt nào thuộc lượt đó"
    assert [c.attrs["tool"] for c in calls] == ["read_file", "read_file"]


def test_che_do_cli_khong_co_span_tool_call():
    """ADR-0023: vòng tool chạy trong CLI, không qua `ToolBox` → 0 span `tool.call`. Đây là giới hạn ĐÃ BIẾT."""
    class CliClient:
        def __init__(self) -> None: self.inner = FakeClient(responses=[PAYLOAD])

        def complete(self, **kw: Any):
            return replace(self.inner.complete(**kw), tool_mode="cli")

    sink = MemorySink()
    box = _toolbox(sink)
    g = _runner(CliClient(), sink).generate("qa", _env(), "review-results", tools=box)
    assert g.payloads == [PAYLOAD] and box.calls == []
    assert _names(sink).count("tool.call") == 0
    assert _names(sink).count("llm.complete") == 1


# ---------- chiều ngược: không sink ----------

def test_khong_sink_thi_ket_qua_y_het_va_khong_span_nao_ro_ra(monkeypatch):
    import xagents_core.observe as observe

    ref = _runner(FakeClient(responses=[PAYLOAD]), MemorySink()).generate("qa", _env(), "review-results")
    monkeypatch.setattr(observe.time, "monotonic_ns", lambda: (_ for _ in ()).throw(AssertionError("đọc đồng hồ")))
    watch = MemorySink()
    plain = _runner(FakeClient(responses=[PAYLOAD])).generate("qa", _env(), "review-results", tools=_toolbox())
    assert watch.spans == []
    assert plain.payloads == ref.payloads and plain.model == ref.model and plain.tokens == ref.tokens
    assert plain.turns == ref.turns and plain.output_tokens == ref.output_tokens
    assert plain.duration_ms >= 0, "`Generated.duration_ms` (perf_counter) giữ nguyên, span không thay nó"


def test_khong_sink_thi_khong_cham_ca_contextvar_luot(monkeypatch):
    """Quyết định 5 của ADR-0009: "không tốn gì" tính cả `ContextVar.set` — nó vẫn cấp phát một `Token`.

    Chiều ngược: gỡ `if sp is not None` ở `runner.py` thì nhánh `sink=None` đi qua `set` và ca này ĐỎ."""
    import company.runner as runner_mod

    class Tripwire:
        def __init__(self) -> None: self.sets = 0
        def get(self) -> Any: return None
        def set(self, v: Any) -> Any:
            self.sets += 1
            raise AssertionError("chạm _TURN_SPAN khi sink tắt")

    tw = Tripwire()
    monkeypatch.setattr(runner_mod, "_TURN_SPAN", tw)
    g = _runner(FakeClient(responses=[PAYLOAD])).generate("qa", _env(), "review-results")
    assert g.payloads == [PAYLOAD] and tw.sets == 0

    # ...và khi CÓ sink thì vẫn phải đi qua `set` (không phải "an toàn vì chẳng bao giờ gọi").
    seen: list[Any] = []
    monkeypatch.setattr(runner_mod, "_TURN_SPAN", type("T", (), {
        "get": lambda self: None, "set": lambda self, v: seen.append(v)})())
    _runner(FakeClient(responses=[PAYLOAD]), MemorySink()).generate("qa", _env(), "review-results")
    assert len(seen) == 1 and seen[0] is not None and seen[0].name == "llm.complete"


def test_cau_mcp_mat_cha_cua_span_tool_call():
    """Giới hạn ĐÃ BIẾT (ADR-0009): `ToolBridge` phục vụ trong THREAD handler của `socketserver`
    (`mcp_bridge.py:93-96`), nên `contextvars` Context rỗng và `tool.call` sinh ra ở đó có `parent=None` —
    khác đường `loop`, nơi cùng một `ToolBox` cho ra span có cha là `llm.complete`.

    Test này KHẲNG ĐỊNH hành vi hôm nay, không tán thành nó: ai truyền `copy_context()` qua cầu sẽ thấy nó đỏ."""
    import json as _json
    import socket as _socket

    from xagents_core.observe import span

    from company.mcp_bridge import ToolBridge

    sink = MemorySink()
    box = _toolbox(sink)
    with span("llm.complete", sink) as parent:
        with ToolBridge(box) as br:
            with _socket.create_connection(("127.0.0.1", br.port), timeout=10) as s:
                s.sendall(_json.dumps({"token": br.token, "op": "call", "id": "c1", "name": "read_file",
                                       "args": {"path": "f.py"}}).encode("utf-8") + b"\n")
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = s.recv(65536)
                    if not chunk: break
                    buf += chunk
        assert _json.loads(buf)["ok"] is True, "tool vẫn CHẠY THẬT trong ToolBox — chỉ mất liên kết cha"
        box.call(ToolCall(id="c2", name="read_file", args={"path": "g.py"}))

    calls = [s for s in sink.spans if s.name == "tool.call"]
    assert len(calls) == 2, "cả hai đường đều CÓ span"
    assert calls[0].parent is None, "qua cầu: thread handler → Context rỗng → mất cha"
    assert calls[1].parent is parent, "cùng luồng: cha là span đang mở"


# ---------- nối sink (ib1-quansat Q2): một khoá env `COMPANY_OTEL=1`, đọc lúc dựng runner của orchestrator ----------

def _orch_runner_sink() -> Any:
    from company.orchestrator import Orchestrator
    return Orchestrator(InMemoryBus(), FakeClient(handler=lambda s, u: "{}")).runner.sink


def test_sink_none_khi_khong_cau_hinh(monkeypatch):
    """Không bật thì `None` tuyệt đối như trước (quyết định 5 của ADR-0009): không đọc đồng hồ, không cấp phát."""
    monkeypatch.delenv("COMPANY_OTEL", raising=False)
    assert _orch_runner_sink() is None


def test_sink_bat_khi_cau_hinh(monkeypatch):
    import company.runner as runner_mod
    goi: list[str] = []
    sink = MemorySink()
    monkeypatch.setattr(runner_mod, "otel_sink", lambda name: goi.append(name) or sink)
    monkeypatch.setenv("COMPANY_OTEL", "1")
    assert _orch_runner_sink() is sink and goi == ["company"]


def test_sink_null_khi_thieu_otel(monkeypatch):
    """Bật nhưng người vận hành chưa cài OTel → `NullSink` (đo nhưng không phát), không phải ImportError lúc khởi động.
    `sys.modules[...] = None` làm `import opentelemetry` ném ImportError mà không cần gỡ/cài gói nào."""
    import sys

    from xagents_core.observe import NullSink
    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    monkeypatch.setenv("COMPANY_OTEL", "1")
    assert isinstance(_orch_runner_sink(), NullSink)
