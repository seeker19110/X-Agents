"""`xagents_core.runner` — khung runner chung (K3.6d1 + d2).

`AgentRunner` ở đây chỉ có PHẦN NGOÀI: `generate` và vòng lặp tool ở lại từng công ty vì chúng dựng prompt, mà
đổi một dấu cách trong prompt là mọi bản ghi eval lệch (docstring module). Ca của d2 vì thế đo đúng hai thứ:
cơ chế (publish, audit, blackboard) chạy đúng, và **bốn hook giữ được hành vi riêng của mỗi công ty** — đặc
biệt `wants_content` và `_new_envelope`, hai chỗ mà chép nguyên bản company sẽ đổi hành vi studio âm thầm.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from conftest import FakeEnvelope
from xagents_core.bus import BusError
from xagents_core.runner import AgentRunner as CoreAgentRunner
from xagents_core.runner import Generated, RunnerError, RunResult, output_schema, payload_schema
from xagents_core.runner import Generated as CoreGenerated
from xagents_core.runner import RunResult as CoreRunResult

WRITES = {"type": "array", "items": {"type": "object",
                                     "properties": {"namespace": {"type": "string"}, "content_ref": {"type": "string"}},
                                     "required": ["namespace", "content_ref"]}}
TOPIC = {"type": "object", "properties": {"tieu_de": {"type": "string"}}, "required": ["tieu_de"]}


# ---------- payload_schema ----------

def test_payload_schema_lay_dung_phan_payload(tmp_path):
    (tmp_path / "ban-tin.json").write_text(json.dumps({"properties": {"payload": TOPIC}}), encoding="utf-8")
    assert payload_schema(tmp_path, "ban-tin") == TOPIC


def test_payload_schema_topic_khong_co_schema_thi_bao_loi_chu_khong_lot_qua(tmp_path):
    with pytest.raises(RunnerError, match="không có schema cho topic khong-co"):
        payload_schema(tmp_path, "khong-co")


# ---------- output_schema ----------

def test_khong_namespace_va_mot_payload_thi_giu_nguyen_schema_topic():
    """Đường phổ biến nhất: không bọc gì cả, model trả thẳng payload của topic."""
    assert output_schema(TOPIC, [], many=False, writes_schema=WRITES) is TOPIC


def test_co_namespace_thi_boc_payload_va_context_writes():
    got = output_schema(TOPIC, ["giong"], many=False, writes_schema=WRITES)
    assert got["required"] == ["payload"]
    assert got["properties"]["payload"] is TOPIC and got["properties"]["context_writes"] is WRITES


def test_many_thi_boc_thanh_items_mang():
    got = output_schema(TOPIC, [], many=True, writes_schema=WRITES)
    assert got["required"] == ["items"] and got["properties"]["items"] == {"type": "array", "items": TOPIC}
    assert "context_writes" not in got["properties"], "không sở hữu namespace thì không hỏi context_writes"


def test_many_va_co_namespace_thi_co_ca_hai():
    got = output_schema(TOPIC, ["giong"], many=True, writes_schema=WRITES)
    assert set(got["properties"]) == {"items", "context_writes"} and got["required"] == ["items"]


def test_context_only_chi_hoi_context_writes():
    """`schema=None` = agent chỉ ghi blackboard, không publish topic nào."""
    got = output_schema(None, ["giong"], many=False, writes_schema=WRITES)
    assert got == {"type": "object", "properties": {"context_writes": WRITES}, "required": ["context_writes"]}


def test_writes_schema_la_THAM_SO_chu_khong_dung_tai_cho():
    """Hình dạng `context_writes` là hợp đồng đầu ra của agent — tức prompt, tức của từng công ty. Company đòi
    `content` (ADR-0012), studio không. Core không được dựng nó, nếu không một trong hai bên đổi prompt."""
    khac = {"type": "array", "items": {"type": "object", "required": ["namespace", "content_ref", "content"]}}
    got = output_schema(TOPIC, ["giong"], many=False, writes_schema=khac)
    assert got["properties"]["context_writes"] is khac


# ---------- lớp kết quả ----------

def test_generated_mang_dung_phan_chung_hai_cong_ty():
    """Năm trường company có thêm (`output_tokens`, `cost_usd`, `priced`, `duration_ms`, `phase`) KHÔNG được ở
    đây: đưa `phase` (ADR-0037) lên core là bắt studio mang một trường nó không bao giờ ghi (bài học K3.5a)."""
    from dataclasses import fields
    ten = {f.name for f in fields(Generated)}
    assert ten == {"payloads", "tokens", "model", "context_writes", "cache_hit_ratio", "turns", "tool_calls"}
    assert not (ten & {"output_tokens", "cost_usd", "priced", "duration_ms", "phase"})


def test_generated_default_khong_dung_chung_giua_hai_the_hien():
    a, b = Generated([], 0, "m"), Generated([], 0, "m")
    a.context_writes.append({"namespace": "x"}); a.tool_calls["web"] = 1
    assert b.context_writes == [] and b.tool_calls == {}


def test_lop_con_thu_hep_output_va_them_truong_cua_minh():
    """Tiền lệ K3.5a: core để `output: Any`, lớp con thu hẹp về `Envelope` của mình và thêm trường của miền."""
    @dataclass
    class ConRunResult(RunResult):
        cost_usd: float = 0.0

    @dataclass
    class ConGenerated(Generated):
        phase: str | None = None

    r = ConRunResult(output="env", tokens=5, model="m", cost_usd=1.5)
    assert (r.output, r.tokens, r.cost_usd) == ("env", 5, 1.5)
    g = ConGenerated([], 0, "m", phase="review")
    assert g.phase == "review" and g.turns == 1


def test_runner_error_la_exception_thuong():
    with pytest.raises(RunnerError):
        raise RunnerError("x")


# ---------- K3.6d2: AgentRunner (phần ngoài) ----------

class FakeAudit(BaseModel):
    actor: str
    action: str
    tokens: int = 0
    evidence: str = ""
    pham_vi: str | None = None      # đứng thay `ticket_id`/`video_id`: trường PHẠM VI của một miền


class FakeGenerated(CoreGenerated):
    pass


class FakeRunResult(CoreRunResult):
    pass


class FakeSpec:
    def __init__(self, id_="bien-tap", ns=("giong",)):
        self.id = id_
        self.namespaces_write = list(ns)


class FakeBus:
    """Bus giả: ghi lại envelope, và ném `BusError` cho topic `noi-bo` (đứng thay một payload sai schema)."""
    def __init__(self): self.published: list[FakeEnvelope] = []
    def publish(self, env):
        if env.topic == "noi-bo": raise BusError("payload sai schema")
        self.published.append(env); return env


class FakeBB:
    def __init__(self): self.writes: list[tuple] = []
    def write(self, actor, ns, ref, summary="", **kw): self.writes.append((actor, ns, ref, summary, kw))


class Runner(CoreAgentRunner):
    envelope_cls = FakeEnvelope
    audit_cls = FakeAudit
    generated_cls = FakeGenerated
    run_result_cls = FakeRunResult

    def _audit_scope(self, inp): return {"pham_vi": inp.payload.get("pham_vi")}

    def generate(self, agent_id, inp, topic_out, **kw):
        return FakeGenerated(payloads=[{"x": 1}], tokens=9, model="m1", context_writes=kw.get("writes") or [])


def _inp(**kw):
    return FakeEnvelope(topic="ban-tin", key="K1", actor="human", payload={"tieu_de": "t", **kw})


def _runner(**kw):
    bus = FakeBus()
    r = Runner(bus, object(), {"bien-tap": FakeSpec()}, **kw)
    return r, bus


def test_audit_mang_truong_pham_vi_do_lop_con_khai():
    """Core không được biết `ticket_id` hay `video_id` là gì — nó chỉ gọi `_audit_scope` (khuôn K3.5a)."""
    r, bus = _runner()
    r._audit(FakeSpec(), "thu", _inp(pham_vi="DA1"), evidence="e", tokens=3)
    (a,) = bus.published
    assert a.topic == "audit-log" and a.payload["pham_vi"] == "DA1" and a.payload["tokens"] == 3


def test_publish_ghi_audit_produced_va_tra_envelope():
    r, bus = _runner()
    out = r.publish("bien-tap", _inp(), "ban-tin", {"tieu_de": "moi"}, tokens=5, model="m1")
    assert out.payload == {"tieu_de": "moi"} and out.actor == "bien-tap"
    (_, audit) = bus.published
    assert audit.payload["action"] == "produced:ban-tin" and "m1" in audit.payload["evidence"]


def test_publish_bus_tu_choi_thi_ghi_invalid_output_roi_nem_RunnerError():
    r, bus = _runner()
    with pytest.raises(RunnerError, match="đầu ra không hợp lệ"):
        r.publish("bien-tap", _inp(), "noi-bo", {"x": 1}, tokens=2)
    (a,) = bus.published
    assert a.payload["action"] == "invalid_output" and a.payload["tokens"] == 2


def test_run_goi_generate_roi_publish_va_tra_run_result():
    r, bus = _runner()
    got = r.run("bien-tap", _inp(), "ban-tin")
    assert type(got) is FakeRunResult and got.tokens == 9 and got.model == "m1"
    assert [e.topic for e in bus.published] == ["ban-tin", "audit-log"]


def test_run_context_ghi_blackboard_va_audit_produced_shared_context():
    bb = FakeBB()
    r, bus = _runner(blackboard=bb)
    r.run_context("bien-tap", _inp(), writes=[{"namespace": "giong", "content_ref": "g.md", "summary": "s"}])
    assert bb.writes[0][:4] == ("bien-tap", "giong", "g.md", "s")
    assert [a.payload["action"] for a in bus.published] == ["context_written", "produced:shared-context"]


def test_write_context_bo_namespace_khong_thuoc_agent_va_khi_khong_co_blackboard():
    bb = FakeBB()
    r, bus = _runner(blackboard=bb)
    assert r.write_context("bien-tap", _inp(), [{"namespace": "cua-nguoi-khac", "content_ref": "x"}]) == []
    assert bus.published[0].payload["action"] == "context_rejected" and bb.writes == []

    r2, bus2 = _runner()   # không có blackboard
    assert r2.write_context("bien-tap", _inp(), [{"namespace": "giong", "content_ref": "x"}]) == []
    assert bus2.published[0].payload["action"] == "context_rejected"


def test_wants_content_TAT_khong_ghi_content_va_khong_audit_context_no_content():
    """Quyết định 1 của K3.6d2. `context_writes` của studio không có `content`; bật cờ này cho nó là sinh một
    audit rác MỖI LẦN ghi context."""
    bb = FakeBB()
    r, bus = _runner(blackboard=bb)
    r.write_context("bien-tap", _inp(), [{"namespace": "giong", "content_ref": "g.md"}])
    assert bb.writes[0][4] == {}, "không truyền `content`/`project_id` khi công ty không dùng"
    assert [a.payload["action"] for a in bus.published] == ["context_written"]


def test_wants_content_BAT_thi_ghi_toan_van_va_bao_khi_thieu():
    """Nửa kia của quyết định 1: company bật cờ, và thiếu toàn văn thì phải hiện ra sổ (ADR-0012)."""
    class Company(Runner):
        wants_content = True
        def _context_project(self, inp): return inp.payload.get("pham_vi")

    bb = FakeBB(); bus = FakeBus()
    r = Company(bus, object(), {"bien-tap": FakeSpec(ns=("giong", "nhip"))}, blackboard=bb)
    r.write_context("bien-tap", _inp(pham_vi="DA1"), [
        {"namespace": "giong", "content_ref": "co.md", "content": "toàn văn"},
        {"namespace": "nhip", "content_ref": "thieu.md", "content": "   "}])
    assert bb.writes[0][4] == {"content": "toàn văn", "project_id": "DA1"}
    assert bb.writes[1][4] == {"content": None, "project_id": "DA1"}, "khoảng trắng = không có toàn văn"
    assert [a.payload["action"] for a in bus.published] == ["context_written", "context_no_content"]


class _CompanyND(Runner):
    """Company bật `wants_content` (ADR-0012) — dùng cho các ca gộp namespace."""
    wants_content = True
    def _context_project(self, inp): return inp.payload.get("pham_vi")


def test_write_context_gop_nhieu_ban_ghi_cung_namespace_thay_vi_de():
    """Lỗi thật 2026-10-11 (QLLH-TRUONG): `product[spec]` trả 4 `context_writes` cùng namespace `prd` (PRD,
    requirements, risk register, ADR). Blackboard chỉ giữ bản mới nhất mỗi namespace, nên ghi từng cái là ADR 3 KB
    đè mất PRD và requirements 27 KB. Một lượt có nhiều bản ghi cùng namespace phải thành MỘT lần ghi gộp."""
    bb = FakeBB(); bus = FakeBus()
    r = _CompanyND(bus, object(), {"bien-tap": FakeSpec(ns=("giong", "nhip"))}, blackboard=bb)
    got = r.write_context("bien-tap", _inp(pham_vi="DA1"), [
        {"namespace": "giong", "content_ref": "PRD.md", "summary": "prd", "content": "# PRD"},
        {"namespace": "nhip", "content_ref": "n.md", "summary": "n", "content": "nhịp"},
        {"namespace": "giong", "content_ref": "req.json", "summary": "", "content": "   "},
        {"namespace": "giong", "content_ref": "risk.json", "summary": "risk", "content": '{"r": 1}'},
        {"namespace": "giong", "content_ref": "adr.md", "summary": "adr", "content": "# ADR"}])
    assert got == ["giong", "nhip"], "mỗi namespace một lần, theo thứ tự xuất hiện đầu tiên"
    assert [w[1] for w in bb.writes] == ["giong", "nhip"], "một lần ghi blackboard mỗi namespace — không đè"
    _, _, ref, summary, kw = bb.writes[0]
    assert ref == "PRD.md+req.json+risk.json+adr.md"
    assert summary == "prd | risk | adr", "summary rỗng không để lại ' |  | '"
    assert kw == {"content": '# PRD\n\n---\n\n{"r": 1}\n\n---\n\n# ADR', "project_id": "DA1"}
    assert bb.writes[1][2:] == ("n.md", "n", {"content": "nhịp", "project_id": "DA1"}), "bản ghi đơn giữ nguyên"
    acts = [(a.payload["action"], a.payload["evidence"]) for a in bus.published]
    assert acts == [("context_merged", "giong x4"), ("context_written", "giong,nhip")], \
        "có một phần thiếu toàn văn nhưng bản gộp vẫn có toàn văn → không audit context_no_content"


def test_write_context_gop_ma_moi_phan_deu_thieu_toan_van_thi_van_bao_context_no_content():
    bb = FakeBB(); bus = FakeBus()
    r = _CompanyND(bus, object(), {"bien-tap": FakeSpec()}, blackboard=bb)
    r.write_context("bien-tap", _inp(pham_vi="DA1"), [
        {"namespace": "giong", "content_ref": "a.md"}, {"namespace": "giong", "content_ref": "b.md", "content": " "}])
    assert bb.writes == [("bien-tap", "giong", "a.md+b.md", "", {"content": None, "project_id": "DA1"})]
    assert [(a.payload["action"], a.payload["evidence"]) for a in bus.published] == [
        ("context_merged", "giong x2"), ("context_written", "giong"),
        ("context_no_content", "chỉ có con trỏ, không có toàn văn: giong")]


def test_write_context_gop_khi_wants_content_TAT_va_bo_ban_ghi_bi_tu_choi():
    """Studio (không `content`) cũng không được đè; bản ghi namespace lạ vẫn bị từ chối từng cái như cũ."""
    bb = FakeBB()
    r, bus = _runner(blackboard=bb)
    r.write_context("bien-tap", _inp(), [
        {"namespace": "giong", "content_ref": "a.md", "summary": "a"},
        {"namespace": "la", "content_ref": "x"},
        {"namespace": "giong", "content_ref": "b.md", "summary": "b"}])
    assert bb.writes == [("bien-tap", "giong", "a.md+b.md", "a | b", {})]
    assert [a.payload["action"] for a in bus.published] == ["context_rejected", "context_merged", "context_written"]


def test_new_envelope_la_hook_nen_studio_giu_envelope_moi_con_company_noi_chuoi():
    """Quyết định 2 của K3.6d2: cho studio `inp.child()` là đổi NỘI DUNG event trên bus, không phải chuyển mã."""
    r, _ = _runner()
    out = r.publish("bien-tap", _inp(), "ban-tin", {"tieu_de": "x"})
    assert out.causation_id is None, "mặc định: envelope mới, không nối chuỗi nhân quả"

    class Company(Runner):
        def _new_envelope(self, inp, topic, key, actor, payload):
            return inp.child(topic=topic, key=key, actor=actor, payload=payload)

    bus2 = FakeBus()
    inp = _inp()
    out2 = Company(bus2, object(), {"bien-tap": FakeSpec()}).publish("bien-tap", inp, "ban-tin", {"tieu_de": "x"})
    assert out2.causation_id == inp.event_id


def test_generate_la_hook_bat_buoc():
    """`generate` dựng prompt, mà prompt là khoá bản ghi eval — nó không được ở core."""
    r = CoreAgentRunner(FakeBus(), object(), {})
    with pytest.raises(NotImplementedError):
        r.generate("a", _inp(), "ban-tin")


def test_max_input_chars_lay_tu_client_roi_moi_toi_mac_dinh():
    class C: max_input_chars = 111
    assert Runner(FakeBus(), C(), {}).max_input_chars == 111
    assert Runner(FakeBus(), object(), {}, max_input_chars=222).max_input_chars == 222
    assert Runner(FakeBus(), object(), {}, default_max_input_chars=333).max_input_chars == 333


def test_hai_hook_mac_dinh_la_khong_lam_gi():
    """`_context_project` và `_extra_audit_on_publish` mặc định trung tính: công ty không cần thì không phải
    khai. Ca này giữ chúng khỏi bị "dọn" đi — bỏ chúng là company mất phân vùng dự án và mất sổ `ruling`."""
    r, _ = _runner()
    assert CoreAgentRunner._audit_scope(r, _inp(pham_vi="DA1")) == {}, "mặc định: core không biết trường phạm vi nào"
    assert r._context_project(_inp(pham_vi="DA1")) is None
    assert r._extra_audit_on_publish(FakeSpec(), _inp(), _inp(), "ban-tin", {}) is None
