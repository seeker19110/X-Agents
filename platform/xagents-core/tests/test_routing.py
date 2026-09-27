"""`xagents_core.routing` — xoay backend theo gói tài khoản (K3.3d; company ADR-0019, studio ADR-0006).

Ca ở ĐÂY vì mã ở đây. Trước K3.3d mỗi công ty có một bản `routing.py` và một bộ ca riêng, nên một đột biến trong
phân loại lỗi chỉ đỏ ở một suite — đọc ra "lỗi của company" trong khi nó là lỗi của cơ chế dùng chung (bài học đã
ghi ở nhật ký phiên 2026-09-08 khi `TransientError` lên core mà ca ở lại company).

Bốn nhóm ca dưới đây là bốn điểm studio ĐƯỢC NÂNG; mỗi ca đỏ nếu ai đó gỡ điểm nâng ấy:

1. `test_ma_http_thang_hon_regex` — phân loại theo `LLMError.status` trước, regex chỉ là đường lùi cho CLI/gateway.
2. `test_quota_patterns_co_ranh_gioi_tu` — "unlimited"/"billingham"/4290 KHÔNG phải hết quota (bug thật của studio).
3. `test_loi_xac_thuc_401_403_cho_backend_nghi_thay_vi_nem_cho_agent` — `is_auth_error`, studio trước không có.
4. `test_moi_backend_deu_nghi_nem_transient_error` — `TransientError` chứ không `LLMError` trần, để orchestrator
   phân biệt được "chưa gọi được" với "model trả lời sai".
"""
from __future__ import annotations

import pytest

from xagents_core.llm import Completion, LLMError, Refused, TransientError
from xagents_core.routing import (
    Backend,
    RoutingClient,
    is_auth_error,
    is_missing_error,
    is_quota_error,
    plain,
    reset_clock_seconds,
    retry_after_seconds,
)
from xagents_core.tools import ToolSpec


class _Client:
    """Backend giả: `fail` = ngoại lệ ném ở N lần đầu; sau đó trả lời."""

    def __init__(self, name: str, fail: list[BaseException] | None = None):
        self.name, self.fail, self.calls = name, list(fail or []), []

    def complete(self, *, system, user, schema, model_tier, cache_key=None, tools=None, messages=None, workdir=None):
        self.calls.append(model_tier)
        if self.fail: raise self.fail.pop(0)
        return Completion(text="{}", input_tokens=10, output_tokens=1, model=f"{self.name}-{model_tier}")


def _router(*backends, clock=None, **kw):
    t = {"now": 1000.0}
    r = RoutingClient(list(backends), clock=clock or (lambda: t["now"]), **kw)
    r._t = t  # type: ignore[attr-defined]
    return r


def _call(r, tier="standard", tools=None):
    return r.complete(system="s", user="u", schema={"type": "object"}, model_tier=tier, tools=tools)


# ---------- xoay backend ----------

def test_quota_error_rotates_to_next_backend_and_rests_first():
    a, b = _Client("a", [TransientError("HTTP 429: quota exceeded, thử lại sau 120s")]), _Client("b")
    r = _router(Backend("a", a), Backend("b", b))
    c = _call(r)
    assert c.model == "b-standard" and a.calls == ["standard"] and b.calls == ["standard"]
    st = {s["name"]: s for s in r.status()}
    assert not st["a"]["ready"] and st["a"]["cooldown_remaining"] == 120 and st["b"]["ready"]
    notes = r.drain_retries()
    assert any("hết quota" in n and "nghỉ 120s" in n for n in notes) and any("đi backend b" in n for n in notes)
    assert r.drain_retries() == []
    # còn nghỉ → không gọi a; hết nghỉ → a lại đứng đầu
    _call(r); assert a.calls == ["standard"]
    r._t["now"] += 121
    _call(r); assert a.calls == ["standard", "standard"]


def test_transient_rest_is_short_and_content_errors_are_not_routed():
    a, b = _Client("a", [TransientError("lỗi mạng: timeout")]), _Client("b")
    r = _router(Backend("a", a), Backend("b", b), transient_cooldown_s=30, cooldown_s=3600)
    assert _call(r).model == "b-standard"
    assert r.status()[0]["cooldown_remaining"] == 30
    bad = _Client("x", [LLMError("đầu ra không phải JSON")])
    r2 = _router(Backend("x", bad), Backend("y", _Client("y")))
    with pytest.raises(LLMError, match="JSON"): _call(r2)
    ref = _Client("x", [Refused("model từ chối")])
    r3 = _router(Backend("x", ref), Backend("y", _Client("y")))
    with pytest.raises(Refused): _call(r3)


def test_prefer_per_tier_and_tools_skip_backend_without_tool_support():
    sub, free = _Client("claude-sub"), _Client("antigravity")
    r = _router(Backend("claude-sub", sub, supports_tools=False), Backend("antigravity", free),
                prefer={"light": "antigravity"})
    assert _call(r, "strong").model == "claude-sub-strong"
    assert _call(r, "light").model == "antigravity-light"
    tool = [ToolSpec(name="read_file", description="", parameters={"type": "object"})]
    assert _call(r, "strong", tools=tool).model == "antigravity-strong"
    r_only = _router(Backend("claude-sub", sub, supports_tools=False))
    with pytest.raises(LLMError, match="tool"): _call(r_only, tools=tool)


def test_missing_binary_rests_backend_for_full_cooldown():
    a = _Client("a", [LLMError("không tìm thấy `claude` (cài Claude Code hoặc đổi provider)")]); b = _Client("b")
    r = _router(Backend("a", a), Backend("b", b), cooldown_s=900)
    assert _call(r).model == "b-standard" and r.status()[0]["cooldown_remaining"] == 900


def test_router_validation():
    with pytest.raises(LLMError, match="backend"): RoutingClient([])
    with pytest.raises(LLMError, match="trùng"): RoutingClient([Backend("a", _Client("a")), Backend("a", _Client("a"))])
    with pytest.raises(LLMError, match="prefer"): RoutingClient([Backend("a", _Client("a"))], prefer={"strong": "zzz"})


def test_bind_toolbox_chuyen_tiep_cho_backend_biet_bo_qua_backend_khong_biet():
    """ADR-0024: `bind_toolbox` phải gọi tới mọi backend có phương thức đó, và không sập với backend không có (vd. codex).

    Ở core vì `RoutingClient` là chỗ chuyển tiếp; cầu MCP thật thì vẫn ở lại company (K3.3c3 bước 2)."""
    class _WithBind(_Client):
        def __init__(self, name):
            super().__init__(name)
            self.bound = None

        def bind_toolbox(self, tb):
            self.bound = tb

    a, b = _WithBind("a"), _Client("b")   # b không có bind_toolbox
    r = _router(Backend("a", a), Backend("b", b))
    r.bind_toolbox("hop-tool-gia")
    assert a.bound == "hop-tool-gia"


def test_drain_retries_gom_ca_ghi_chu_cua_backend_con():
    """`drain_retries` của backend (RetryingClient) và ghi chú xoay của router phải cùng về một chỗ: runner chỉ
    hỏi router, không biết backend nào có lớp retry riêng."""
    class _WithDrain(_Client):
        def drain_retries(self):
            return ["thử lại lần 1"]

    r = _router(Backend("a", _WithDrain("a")), Backend("b", _Client("b")))
    _call(r)
    assert r.drain_retries() == ["[a] thử lại lần 1"]


# ---------- 1. mã HTTP thẳng hơn regex ----------

def test_ma_http_thang_hon_regex():
    """Có `status` thì HỎI nó, đừng đọc chuỗi. Chuỗi "401" trong thân lỗi không làm nó thành lỗi xác thực, và
    một lỗi mang status=429 vẫn là hết quota dù thông điệp không có chữ nào khớp regex."""
    assert is_quota_error(LLMError("chuyện gì đó rất lạ", status=429))
    assert not is_quota_error(LLMError("429 nằm trong thân văn bản", status=500))
    assert is_missing_error(LLMError("gì đó", status=404)) and not is_missing_error(LLMError("not found", status=500))
    assert is_auth_error(LLMError("x", status=401)) and is_auth_error(LLMError("x", status=403))
    assert not is_auth_error(LLMError("401"))   # không mã → regex, và regex không đoán lỗi xác thực


def test_quota_patterns_co_ranh_gioi_tu():
    """Bản studio trước K3.3d khớp `insufficient` và `429` trần: "unlimited", "billingham", mã 4290 đều đọc ra
    "hết quota" và cho một backend còn tốt đi nghỉ nguyên tiếng. Ranh giới từ là bản vá."""
    for lanh in ("gói unlimited của bạn còn hiệu lực", "liên hệ billingham@example.com", "mã lỗi nội bộ 4290",
                 "limited edition model"):
        assert not is_quota_error(LLMError(lanh)), lanh
    for that in ("HTTP 429: quá nhiều yêu cầu", "RESOURCE_EXHAUSTED", "You've hit your limit · resets 3pm",
                 "insufficient quota", "billing required"):
        assert is_quota_error(LLMError(that)), that


def test_loi_xac_thuc_401_403_cho_backend_nghi_thay_vi_nem_cho_agent():
    """Khoá sai là lỗi CẤU HÌNH của backend, không phải lỗi nội dung của model. Studio trước K3.3d ném thẳng cho
    agent: một backend khai sai khoá làm hỏng từng lượt thay vì tự nghỉ ra một bên."""
    a, b = _Client("a", [LLMError("HTTP 401: invalid api key", status=401)]), _Client("b")
    r = _router(Backend("a", a), Backend("b", b), cooldown_s=1800, transient_cooldown_s=60)
    assert _call(r).model == "b-standard"
    assert r.status()[0]["cooldown_remaining"] == 1800 and "xác thực" in r.status()[0]["reason"]


def test_moi_backend_deu_nghi_nem_transient_error():
    """`TransientError`, không phải `LLMError` trần: orchestrator phân biệt được "chưa gọi được" (hoãn, nhịp sau
    thử lại) với "model trả lời sai" (lỗi agent, tính retry). Nó vẫn là con của `LLMError` nên chỗ nào đang
    `except LLMError` không phải sửa."""
    a = _Client("a", [TransientError("lỗi mạng: connection reset")])
    b = _Client("b", [LLMError("HTTP 402: insufficient quota")])
    r = _router(Backend("a", a), Backend("b", b), cooldown_s=600, transient_cooldown_s=45)
    with pytest.raises(TransientError, match="thử lại sau 45s"): _call(r)   # a nghỉ 45s (mạng), b nghỉ 600s (quota)
    assert all(not s["ready"] for s in r.status()) and [s["failures"] for s in r.status()] == [1, 1]
    with pytest.raises(LLMError): _call(r)   # vẫn bắt được bằng lớp cha


# ---------- phân loại chuỗi (đường lùi cho CLI/gateway không mã) ----------

def test_retry_after_va_giai_ma_tieng_viet_bi_escape():
    assert retry_after_seconds("mọi tài khoản đều cooldown, thử lại sau 77s") == 77
    assert retry_after_seconds("Mọi tài khoản Antigravity đều đang cooldown hoặc hết hạn. Thử lại sau khoảng 77s.") == 77
    assert retry_after_seconds("Retry-After: 30") == 30 and retry_after_seconds("resets in 12s") == 12
    assert retry_after_seconds("no hint") is None
    # thân lỗi HTTP escape tiếng Việt: không giải mã thì mẫu tiếng Việt trượt hết
    assert plain(r'{"error": "Chưa có tài khoản"}') == '{"error": "Chưa có tài khoản"}'
    assert is_missing_error(LLMError(r'{"detail": "pool trống"}'))


def test_hen_gio_cua_provider_thang_cooldown_mac_dinh():
    """Provider nói "thử lại sau 120s" thì nghỉ 120s, không phải `cooldown_s` mặc định — hỏi lại sớm hơn thì phí,
    nghỉ lâu hơn thì mất một gói còn dùng được."""
    a = _Client("a", [LLMError("HTTP 429: thử lại sau 120s")])
    r = _router(Backend("a", a), Backend("b", _Client("b")), cooldown_s=3600)
    _call(r)
    assert r.status()[0]["cooldown_remaining"] == 120


def test_ghi_chu_xoay_backend_theo_thread():
    """`notes` là thread-local: với `--workers>1` audit `llm_retry` của agent nào phải là của agent đó, không phải
    ghi chú của lượt chạy song song bên cạnh."""
    import threading

    r = _router(Backend("a", _Client("a")))
    r.notes.append("của thread chính")
    thay: list[list[str]] = []
    t = threading.Thread(target=lambda: thay.append(list(r.notes)))
    t.start(); t.join()
    assert thay == [[]] and r.notes == ["của thread chính"]


def test_backend_ready_va_status_phan_anh_dong_ho_tiem_vao():
    b = Backend("a", _Client("a"))
    assert b.ready(1000.0)
    b.cooldown_until = 1100.0
    assert not b.ready(1000.0) and b.ready(1100.0)


# ---------- phân loại không đọc chữ do MODEL viết ----------

_MODEL_NOI = ("Tôi đã kiểm: file config not found, billing module exhausted, quota bảng 429 rate limit, "
              "thử lại sau 900s")


def _loi_cli_that():
    """Hai lỗi CLI thật mang chữ model viết trong thông điệp: subtype hết lượt (qua `_parse`) và thoát mã 1 với
    subtype hết lượt (qua `cli_exit_error`). `result` ở cả hai là câu trả lời dở của model, không phải lời CLI."""
    import json

    from xagents_core.llm import ClaudeCodeClient, LLMConfig, cli_exit_error

    class _CC(ClaudeCodeClient):
        def complete(self, **kw): raise NotImplementedError

    cc = _CC(LLMConfig(provider="claude-code", models={"standard": "x"}), binary="claude")
    try:
        cc._parse(json.dumps({"subtype": "error_max_turns", "result": _MODEL_NOI}), "x")
    except LLMError as e:
        parse_err = e
    return [parse_err, cli_exit_error(1, json.dumps({"subtype": "error_max_turns", "result": _MODEL_NOI}), "")]


@pytest.mark.parametrize("i", [0, 1])
def test_chu_model_trong_loi_cli_khong_lam_backend_nghi(i):
    """`claude -p error_max_turns: ...; <chữ model>` — regex quota/thiếu khớp "not found"/"billing"/"exhausted"
    trong câu model viết và cho một backend còn tốt nghỉ một tiếng. Lỗi hết lượt là lỗi NỘI DUNG: ném thẳng cho
    agent, không xoay, không nghỉ; thông điệp vẫn giữ chữ model cho người đọc."""
    e = _loi_cli_that()[i]
    assert "billing module exhausted" in str(e)
    assert not isinstance(e, TransientError)
    assert not is_quota_error(e) and not is_missing_error(e)
    a = _Client("a", [e])
    r = _router(Backend("a", a), Backend("b", _Client("b")))
    with pytest.raises(LLMError, match="billing module exhausted"):
        _call(r)
    assert r.status()[0]["ready"] is True


def test_hen_gio_trong_chu_model_khong_thanh_thoi_gian_nghi():
    """Lỗi hết lượt kèm `api_error_status=529` (quá tải thật, trường có cấu trúc) → nghỉ `cooldown_s` như mọi 529.
    "thử lại sau 900s" nằm trong câu MODEL viết, không phải lời hẹn của provider — không được thành thời gian nghỉ."""
    import json

    from xagents_core.llm import cli_exit_error
    e = cli_exit_error(1, json.dumps({"subtype": "error_max_turns", "api_error_status": 529, "result": _MODEL_NOI}), "")
    assert isinstance(e, TransientError)
    r = _router(Backend("a", _Client("a", [e])), Backend("b", _Client("b")), cooldown_s=3600)
    _call(r)
    assert r.status()[0]["cooldown_remaining"] == 3600


# ---------- mốc reset dạng giờ đồng hồ, nghỉ lùi dần (audit 2026-09-27 B5) ----------

def _luc(gio: int, phut: int = 0) -> float:
    """Dấu thời gian của một giờ đồng hồ ĐỊA PHƯƠNG ngày 26/09/2026 — CLI in mốc reset theo múi của máy chạy nó."""
    from datetime import datetime
    return datetime(2026, 9, 26, gio, phut).timestamp()


def test_moc_reset_gio_dong_ho_thanh_so_giay_toi_moc():
    """`claude -p` hết session limit báo "resets 10:40pm (Asia/Ho_Chi_Minh)" — một GIỜ ĐỒNG HỒ, không phải số giây,
    nên không mẫu `RETRY_AFTER_PATTERNS` nào đọc được: backend nghỉ `cooldown_s` rồi hỏi lại dù mốc còn xa. Mốc chỉ
    tới phút nên cộng một phút; mốc vừa qua (reset thật trễ vài giây) là nghỉ một phút, không phải một ngày."""
    assert reset_clock_seconds("You've hit your session limit · resets 10:40pm", _luc(20)) == 2 * 3600 + 40 * 60 + 60
    assert reset_clock_seconds("resets 3:40am (Khong/Co_That)", _luc(20)) == 7 * 3600 + 40 * 60 + 60   # qua nửa đêm
    assert reset_clock_seconds("resets 12am", _luc(23)) == 3600 + 60
    assert reset_clock_seconds("resets 12pm", _luc(11)) == 3600 + 60
    assert reset_clock_seconds("resets 10:40pm", _luc(22, 41)) == 60
    assert reset_clock_seconds("resets in 12s", _luc(20)) is None and reset_clock_seconds("no hint", _luc(20)) is None


def test_moc_reset_theo_mui_gio_ghi_trong_ngoac(monkeypatch):
    """Múi trong ngoặc được dùng khi máy phân giải được nó; Windows không có cơ sở dữ liệu múi giờ (thêm gói `tzdata`
    vào lõi là quyết định kiến trúc) nên tên lạ lùi về múi của máy — nơi CLI in ra mốc."""
    from datetime import datetime, timedelta, timezone

    import xagents_core.routing as routing
    assert routing._zone("Khong/Co_That") is None
    ict = timezone(timedelta(hours=7))
    monkeypatch.setattr(routing, "_zone", lambda name: ict if name == "Asia/Ho_Chi_Minh" else None)
    now = datetime(2026, 9, 26, 20, 0, tzinfo=ict).timestamp()
    assert reset_clock_seconds("resets 10:40pm (Asia/Ho_Chi_Minh)", now) == 2 * 3600 + 40 * 60 + 60


def test_session_limit_nghi_toi_moc_reset_khong_phai_mot_gio():
    """Đo 26/09: `claude-sub` nghỉ 3600s 11 lần trong 7 giờ chờ mốc "resets 3:40am" — mỗi giờ một lượt gọi chắc
    chắn 429. Lỗi CLI thật (`cli_exit_error`) phải cho backend nghỉ đúng tới mốc."""
    import json

    from xagents_core.llm import cli_exit_error
    e = cli_exit_error(1, json.dumps({"subtype": "success", "is_error": True, "api_error_status": 429,
                                      "result": "You've hit your session limit · resets 10:40pm (Khong/Co_That)"}), "")
    r = _router(Backend("a", _Client("a", [e])), Backend("b", _Client("b")), cooldown_s=3600, clock=lambda: _luc(20))
    _call(r)
    assert r.status()[0]["cooldown_remaining"] == 2 * 3600 + 40 * 60 + 60


def test_loi_van_chuyen_lien_tiep_nghi_lui_dan_toi_tran():
    """Đo 26/09: antigravity từ chối kết nối suốt 7 giờ, mỗi lần nghỉ đúng `transient_cooldown_s` — 447 lần nghỉ
    60s, cả công ty hỏi lại mỗi phút. Lỗi vận chuyển liên tiếp trên CÙNG backend nhân đôi thời gian nghỉ tới trần
    `cooldown_s`; một lượt thành công xoá chuỗi."""
    def chet():
        return TransientError("lỗi mạng: [WinError 10061] connection refused")

    a = _Client("a", [chet() for _ in range(6)])
    r = _router(Backend("a", a), transient_cooldown_s=60, cooldown_s=600)
    nghi = []
    for _ in range(6):
        with pytest.raises(TransientError): _call(r)
        nghi.append(r.status()[0]["cooldown_remaining"]); r._t["now"] += nghi[-1]
    assert nghi == [60, 120, 240, 480, 600, 600]
    _call(r)
    a.fail = [chet()]
    with pytest.raises(TransientError): _call(r)
    assert r.status()[0]["cooldown_remaining"] == 60
