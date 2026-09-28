"""Phủ nốt các nhánh chưa được test_translation.py/test_failover.py chạm tới trong client.py:
coerce content edge case, probe/fetch model qua mạng thật (mock httpx), response_format lỗi,
tool_choice/tool_call edge case, và các nhánh xoay vòng còn lại trong stream/non-stream."""

from __future__ import annotations

import json

import httpx
import pytest

from gateway import auth as gw_auth
from gateway import client as gw
from gateway.client import AntigravityClient

# ---------- _coerce_content_to_text / _coerce_content_to_parts ----------


def test_coerce_content_to_text_edge_cases():
    assert gw._coerce_content_to_text(None) == ""
    assert gw._coerce_content_to_text("hi") == "hi"
    assert gw._coerce_content_to_text([{"type": "text", "text": "a"}, "b", {"type": "other"}]) == "a\nb"
    assert gw._coerce_content_to_text(123) == "123"


def test_coerce_content_to_parts_edge_cases():
    assert gw._coerce_content_to_parts(None) == []
    assert gw._coerce_content_to_parts("") == []
    assert gw._coerce_content_to_parts(123) == [{"text": "123"}]
    # phần tử list không phải dict/str bị bỏ qua
    assert gw._coerce_content_to_parts([123, "", "ok"]) == [{"text": "ok"}]
    # image_url dạng chuỗi thô, không phải data: URL -> không sinh part nào
    assert gw._coerce_content_to_parts([{"type": "image_url", "image_url": "http://x/y.png"}]) == []
    # data: URL hỏng (không split được) -> nuốt lỗi, không thêm part
    assert gw._coerce_content_to_parts([{"type": "image_url", "image_url": {"url": "data:badurl"}}]) == []
    # Anthropic style image
    parts = gw._coerce_content_to_parts(
        [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}]
    )
    assert parts == [{"inlineData": {"mimeType": "image/png", "data": "AAAA"}}]
    # inlineData đã có sẵn dạng Gemini
    parts = gw._coerce_content_to_parts([{"inlineData": {"mimeType": "image/gif", "data": "BB"}}])
    assert parts == [{"inlineData": {"mimeType": "image/gif", "data": "BB"}}]
    # dict chỉ có "text" không kèm "type" (fallback cuối)
    parts = gw._coerce_content_to_parts([{"text": "trần trụi"}])
    assert parts == [{"text": "trần trụi"}]
    # type="text" nhưng text rỗng -> không thêm
    assert gw._coerce_content_to_parts([{"type": "text", "text": ""}]) == []
    # dict không khớp nhánh nào -> bỏ qua
    assert gw._coerce_content_to_parts([{"type": "weird"}]) == []


def test_coerce_content_to_parts_image_base64_with_missing_url_field():
    # image_url là dict nhưng thiếu key "url" -> img.get("url") None, không phải str -> bỏ qua an toàn
    assert gw._coerce_content_to_parts([{"type": "image_url", "image_url": {}}]) == []


# ---------- probe_code_assist_model / fetch_available_models (mock httpx.Client) ----------


class _FakeSyncResponse:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text else (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=httpx.Request("POST", "http://x"), response=httpx.Response(self.status_code))


class _FakeSyncClient:
    def __init__(self, response: _FakeSyncResponse) -> None:
        self._response = response
        self.posted_to: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        self.posted_to.append(url)
        return self._response


def test_probe_code_assist_model_returns_status_and_body(monkeypatch):
    fake = _FakeSyncClient(_FakeSyncResponse(200, text="OK BODY"))
    monkeypatch.setattr(gw.httpx, "Client", lambda timeout=30.0: fake)
    status, body = gw.probe_code_assist_model("gemini-3.8-flash-medium", "tok", "proj")
    assert status == 200 and body == "OK BODY"
    assert fake.posted_to == [f"{gw.CODE_ASSIST_BASE_URL}:generateContent"]


def test_fetch_available_models_parses_payload(monkeypatch):
    payload = {
        "models": {"gemini-9": {"displayName": "G9"}},
        "agentModelSorts": [{"groups": [{"modelIds": ["gemini-9"]}]}],
    }
    fake = _FakeSyncClient(_FakeSyncResponse(200, payload=payload))
    monkeypatch.setattr(gw.httpx, "Client", lambda timeout=30.0: fake)
    models = gw.fetch_available_models("tok", "proj")
    assert models == [{"id": "gemini-9", "name": "G9", "code_assist_model": "gemini-9"}]
    assert fake.posted_to == [gw.MODELS_ENDPOINT]


def test_fetch_available_models_raises_on_http_error(monkeypatch):
    fake = _FakeSyncClient(_FakeSyncResponse(500, payload={}))
    monkeypatch.setattr(gw.httpx, "Client", lambda timeout=30.0: fake)
    with pytest.raises(httpx.HTTPStatusError):
        gw.fetch_available_models("tok", "proj")


# ---------- _translate_tool_call_to_gemini: JSON hỏng ----------


def test_translate_tool_call_bad_json_args_kept_as_raw():
    tc = {"id": "c1", "function": {"name": "f", "arguments": "{not json"}}
    part = gw._translate_tool_call_to_gemini(tc)
    assert part["functionCall"]["args"] == {"_raw": "{not json"}
    assert part["functionCall"]["id"] == "c1"


def test_translate_tool_call_args_not_dict_wrapped():
    tc = {"function": {"name": "f", "arguments": "42"}}
    part = gw._translate_tool_call_to_gemini(tc)
    assert part["functionCall"]["args"] == {"_value": 42}


def test_real_thought_signature_skip_marker_dropped():
    tc = {"thoughtSignature": "skip_thought_signature_validator"}
    assert gw._real_thought_signature(tc) == ""
    tc2 = {"extra_content": {"google": {"thoughtSignature": "real-sig"}}}
    assert gw._real_thought_signature(tc2) == "real-sig"


# ---------- response_format: nhánh còn thiếu ----------


def test_response_format_not_dict_raises():
    with pytest.raises(gw.ResponseFormatError):
        gw._translate_response_format_to_gemini("oops", has_tools=False)


def test_response_format_none_is_noop():
    assert gw._translate_response_format_to_gemini(None, has_tools=False) == {}


# ---------- _translate_tools_to_gemini: entries hỏng bị bỏ qua ----------


def test_translate_tools_skips_malformed_entries():
    tools = [
        "not-a-dict",
        {"type": "function", "function": {}},  # thiếu name
        {"type": "function", "function": {"name": "ok"}},
    ]
    out = gw._translate_tools_to_gemini(tools)
    assert len(out[0]["functionDeclarations"]) == 1
    assert out[0]["functionDeclarations"][0]["name"] == "ok"
    assert gw._translate_tools_to_gemini([]) == []
    assert gw._translate_tools_to_gemini(None) == []


def test_sanitize_schema_ref_variant_default_not_copied():
    """anyOf còn 1 nhánh không null và nhánh đó có $ref: default ở ngoài không được chép vào (Code Assist
    từ chối default cạnh $ref)."""
    node = {"anyOf": [{"$ref": "#/$defs/X"}, {"type": "null"}], "default": "z"}
    out = gw._sanitize_gemini_schema_node(node)
    assert out == {"$ref": "#/$defs/X"}


def test_sanitize_schema_all_variants_null_falls_back_to_string():
    node = {"anyOf": [{"type": "null"}]}
    out = gw._sanitize_gemini_schema_node(node)
    assert out["type"] == "string" and "anyOf" not in out


def test_translate_tools_includes_description():
    tools = [{"type": "function", "function": {"name": "f", "description": "làm gì đó"}}]
    decl = gw._translate_tools_to_gemini(tools)[0]["functionDeclarations"][0]
    assert decl["description"] == "làm gì đó"


def test_build_request_empty_messages_falls_back_to_hello():
    env = gw.build_code_assist_request({"model": "gemini-3.8-flash-medium", "messages": []}, "p")
    assert env["request"]["contents"] == [{"role": "user", "parts": [{"text": "Hello"}]}]


def test_build_request_empty_messages_with_system_only_uses_system_text():
    payload = {"model": "gemini-3.8-flash-medium", "messages": [{"role": "system", "content": "chỉ dẫn"}]}
    env = gw.build_code_assist_request(payload, "p")
    assert env["request"]["contents"] == [{"role": "user", "parts": [{"text": "chỉ dẫn"}]}]


def test_build_request_tool_config_included():
    payload = {
        "model": "gemini-3.8-flash-medium",
        "messages": [{"role": "user", "content": "x"}],
        "tool_choice": "required",
    }
    req = gw.build_code_assist_request(payload, "p")["request"]
    assert req["toolConfig"] == {"functionCallingConfig": {"mode": "ANY"}}


def test_translate_tool_choice_dict_without_function_name():
    assert gw._translate_tool_choice_to_gemini({"function": {}}) is None
    assert gw._translate_tool_choice_to_gemini({"type": "auto"}) is None
    assert gw._translate_tool_choice_to_gemini(123) is None
    assert gw._translate_tool_choice_to_gemini("bogus") is None


# ---------- _extract_tool_calls_from_text: literal_eval fallback + args không phải dict ----------


def test_extract_tool_calls_from_text_ast_fallback():
    text = "[Tool call: f({'a': 1})]"
    calls, cleaned = gw._extract_tool_calls_from_text(text)
    assert calls[0]["function"]["name"] == "f"
    assert json.loads(calls[0]["function"]["arguments"]) == {"a": 1}
    assert cleaned == ""


def test_extract_tool_calls_from_text_totally_unparseable_args():
    text = "[Tool call: f(not valid at all !!)]"
    calls, _ = gw._extract_tool_calls_from_text(text)
    assert calls[0]["function"]["name"] == "f"
    assert json.loads(calls[0]["function"]["arguments"]) == {"_raw": "not valid at all !!"}


def test_extract_tool_calls_from_text_value_not_dict():
    text = "[Tool call: f(42)]"
    calls, _ = gw._extract_tool_calls_from_text(text)
    assert json.loads(calls[0]["function"]["arguments"]) == {"_value": 42}


def test_extract_tool_calls_from_text_no_args():
    text = "[Tool call: f()]"
    calls, _ = gw._extract_tool_calls_from_text(text)
    assert json.loads(calls[0]["function"]["arguments"]) == {}


# ---------- build_code_assist_request: nhánh message không phải dict ----------


def test_build_request_skips_non_dict_messages():
    payload = {"model": "gemini-3.8-flash-medium", "messages": ["not a dict", {"role": "user", "content": "hi"}]}
    env = gw.build_code_assist_request(payload, "p")
    assert len(env["request"]["contents"]) == 1


def test_build_request_tool_call_entries_not_dict_are_skipped():
    payload = {
        "model": "gemini-3.8-flash-medium",
        "messages": [
            {"role": "assistant", "content": "x", "tool_calls": ["oops", {"function": {"name": "f", "arguments": "{}"}}]},
        ],
    }
    env = gw.build_code_assist_request(payload, "p")
    # contents[0] là "user" placeholder tự chèn (Gemini không cho bắt đầu bằng model)
    parts = env["request"]["contents"][1]["parts"]
    # chỉ có text + 1 functionCall hợp lệ
    assert sum("functionCall" in p for p in parts) == 1


def test_build_request_top_p_generation_config():
    payload = {
        "model": "gemini-3.8-flash-medium",
        "messages": [{"role": "user", "content": "x"}],
        "top_p": 0.5,
        "max_completion_tokens": 50,
    }
    cfg = gw.build_code_assist_request(payload, "p")["request"]["generationConfig"]
    assert cfg["topP"] == 0.5 and cfg["maxOutputTokens"] == 50


# ---------- _parts_to_openai: phần tử không phải dict bị bỏ qua ----------


def test_parts_to_openai_skips_non_dict_parts():
    text, reasoning, calls = gw._parts_to_openai(["not-a-dict", {"text": "hi"}], with_index=False)
    assert text == "hi" and reasoning == "" and calls == []


# ---------- translate_gemini_stream_event: không có candidates ----------


def test_stream_event_no_candidates_returns_none():
    assert gw.translate_gemini_stream_event({"response": {"candidates": []}}, "m", "id") is None
    assert gw.translate_gemini_stream_event({"response": {"candidates": ["bad"]}}, "m", "id") is None


# ---------- AntigravityClient: các nhánh xoay vòng còn thiếu ----------


class FakeAuthManager:
    def __init__(self, accounts=None) -> None:
        self.accounts = accounts if accounts is not None else [
            gw_auth.AntigravityCredentials(access_token="token-a", email="a@example.com", project_id="project-a"),
            gw_auth.AntigravityCredentials(access_token="token-b", email="b@example.com", project_id="project-b"),
        ]
        self.marked: list[tuple[str, int]] = []

    def resolve_credential_candidates(self, bearer_token: str = ""):
        return list(self.accounts)

    def mark_account_unavailable(self, creds, status_code: int, retry_after=None) -> None:
        self.marked.append((creds.email, status_code))


def _ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"response": {"candidates": [{"content": {"parts": [{"text": text}]}}]}})


def _client(auth: FakeAuthManager, handler) -> AntigravityClient:
    client = AntigravityClient(auth)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def _token(request: httpx.Request) -> str:
    return request.headers["Authorization"].removeprefix("Bearer ")


@pytest.mark.asyncio
async def test_no_candidates_available_raises_immediately():
    auth = FakeAuthManager(accounts=[])
    client = _client(auth, lambda request: _ok("unused"))
    try:
        with pytest.raises(gw_auth.UpstreamError, match="Không có tài khoản"):
            await client.create_chat_completion({"model": "gemini-3.8-flash-medium", "messages": []})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_sibling_fallback_fails_without_cooldown_raises():
    """Model anh em cùng tài khoản thất bại với lỗi KHÔNG đáng cooldown (4xx không phải quota) → raise thẳng."""
    auth = FakeAuthManager(accounts=[
        gw_auth.AntigravityCredentials(access_token="token-a", email="a@example.com", project_id="project-a"),
    ])

    def handler(request):
        model = json.loads(request.content).get("model", "")
        if model == "gemini-3.7-flash-high":
            return httpx.Response(429, json={"error": {"message": "RESOURCE_EXHAUSTED"}})
        # model anh em (claude-sonnet-4-6): lỗi payload cứng, không phải quota, không >=500
        return httpx.Response(400, json={"error": {"message": "invalid argument"}})

    client = _client(auth, handler)
    try:
        with pytest.raises(gw_auth.UpstreamError) as exc:
            await client.create_chat_completion({"model": "gemini-3.7-flash", "messages": [{"role": "user", "content": "hi"}]})
    finally:
        await client.close()
    assert exc.value.status_code == 400
    assert auth.marked == []  # không cooldown ai, vì lỗi anh em không phải quota


@pytest.mark.asyncio
async def test_fallback_endpoint_failure_with_cooldown_rotates():
    """Endpoint chính 5xx -> dự phòng cũng lỗi kiểu đáng cooldown -> cho tài khoản nghỉ và xoay."""
    auth = FakeAuthManager()

    def handler(request):
        if request.url.host == "daily-cloudcode-pa.googleapis.com":
            return httpx.Response(503, json={"error": "unavailable"})
        if _token(request) == "token-a":
            return httpx.Response(429, json={"error": {"message": "RESOURCE_EXHAUSTED"}})
        return _ok("SECOND_OK")

    client = _client(auth, handler)
    try:
        result = await client.create_chat_completion({"model": "gemini-3.8-flash-medium", "messages": [{"role": "user", "content": "hi"}]})
    finally:
        await client.close()
    assert result["choices"][0]["message"]["content"] == "SECOND_OK"
    assert auth.marked == [("a@example.com", 429)]


@pytest.mark.asyncio
async def test_fallback_endpoint_failure_without_cooldown_raises():
    """Endpoint chính 5xx -> dự phòng lỗi 4xx không đáng cooldown -> raise thẳng."""
    auth = FakeAuthManager(accounts=[
        gw_auth.AntigravityCredentials(access_token="token-a", email="a@example.com", project_id="project-a"),
    ])

    def handler(request):
        if request.url.host == "daily-cloudcode-pa.googleapis.com":
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    client = _client(auth, handler)
    try:
        with pytest.raises(gw_auth.UpstreamError) as exc:
            await client.create_chat_completion({"model": "gemini-3.8-flash-medium", "messages": [{"role": "user", "content": "hi"}]})
    finally:
        await client.close()
    assert exc.value.status_code == 400
    assert auth.marked == []


@pytest.mark.asyncio
async def test_stream_no_candidates_raises():
    auth = FakeAuthManager(accounts=[])
    client = _client(auth, lambda request: _ok("unused"))
    try:
        with pytest.raises(gw_auth.UpstreamError):
            async for _ in client.stream_chat_completion({"model": "gemini-3.8-flash-medium", "messages": []}):
                pass
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_account_level_failure_without_sibling_cooldowns_directly():
    """Model không có anh em cùng tài khoản (vd. claude-*) trả 401/403/429 -> cho nghỉ và xoay ngay,
    không đi qua nhánh sibling."""
    auth = FakeAuthManager()

    def handler(request):
        if _token(request) == "token-a":
            return httpx.Response(403, json={"error": {"message": "forbidden"}})
        return _ok("SECOND_OK")

    client = _client(auth, handler)
    try:
        result = await client.create_chat_completion(
            {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]}
        )
    finally:
        await client.close()
    assert result["choices"][0]["message"]["content"] == "SECOND_OK"
    assert auth.marked == [("a@example.com", 403)]


@pytest.mark.asyncio
async def test_stream_4xx_not_failover_raises_directly():
    """Lỗi 4xx khi mở stream không thuộc diện xoay được (không phải 401/402/403/429, không có marker
    quota trong body) -> raise thẳng, không cooldown, không xoay."""
    auth = FakeAuthManager(accounts=[
        gw_auth.AntigravityCredentials(access_token="token-a", email="a@example.com", project_id="project-a"),
    ])

    def handler(request):
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    client = _client(auth, handler)
    try:
        with pytest.raises(gw_auth.UpstreamError) as exc:
            async for _ in client.stream_chat_completion(
                {"model": "gemini-3.8-flash-medium", "messages": [{"role": "user", "content": "hi"}]}
            ):
                pass
    finally:
        await client.close()
    assert exc.value.status_code == 400
    assert auth.marked == []


@pytest.mark.asyncio
async def test_stream_non_data_lines_in_sse_block_are_skipped():
    auth = FakeAuthManager(accounts=[
        gw_auth.AntigravityCredentials(access_token="token-a", email="a@example.com", project_id="project-a"),
    ])

    def handler(request):
        good = {"response": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}}
        # dòng comment SSE (":ping") không bắt đầu bằng "data:" -> phải bị bỏ qua, không lỗi
        body = ":ping\n" + f"data: {json.dumps(good)}\n\n" + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body.encode())

    client = _client(auth, handler)
    try:
        chunks = [c async for c in client.stream_chat_completion(
            {"model": "gemini-3.8-flash-medium", "messages": [{"role": "user", "content": "hi"}]}
        )]
    finally:
        await client.close()
    assert any("ok" in c for c in chunks)


@pytest.mark.asyncio
async def test_stream_tool_call_carries_thought_signature():
    auth = FakeAuthManager(accounts=[
        gw_auth.AntigravityCredentials(access_token="token-a", email="a@example.com", project_id="project-a"),
    ])

    def handler(request):
        event = {
            "response": {
                "candidates": [
                    {"content": {"parts": [{"functionCall": {"name": "f", "args": {}}, "thoughtSignature": "sig-1"}]}}
                ]
            }
        }
        body = f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body.encode())

    client = _client(auth, handler)
    try:
        chunks = [c async for c in client.stream_chat_completion(
            {"model": "gemini-3.8-flash-medium", "messages": [{"role": "user", "content": "hi"}]}
        )]
    finally:
        await client.close()
    objs = [json.loads(c[6:]) for c in chunks if c.startswith("data: {")]
    tool_calls = next(o["choices"][0]["delta"]["tool_calls"] for o in objs if o["choices"][0]["delta"].get("tool_calls"))
    assert tool_calls[0]["thoughtSignature"] == "sig-1"
    assert tool_calls[0]["extra_content"]["google"]["thought_signature"] == "sig-1"


@pytest.mark.asyncio
async def test_stream_unparseable_sse_event_is_skipped(caplog):
    auth = FakeAuthManager(accounts=[
        gw_auth.AntigravityCredentials(access_token="token-a", email="a@example.com", project_id="project-a"),
    ])

    def handler(request):
        good = {"response": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}}
        body = "data: {not valid json\n\n" + f"data: {json.dumps(good)}\n\n" + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body.encode())

    client = _client(auth, handler)
    try:
        with caplog.at_level("DEBUG", logger="gateway.client"):
            chunks = [c async for c in client.stream_chat_completion(
                {"model": "gemini-3.8-flash-medium", "messages": [{"role": "user", "content": "hi"}]}
            )]
    finally:
        await client.close()
    assert any("ok" in c for c in chunks)
    assert any("không parse được" in r.getMessage() for r in caplog.records)


# ---------- discovery_is_stale ----------


def test_discovery_is_stale_empty_then_fresh_then_expired(monkeypatch):
    """Chưa dò -> stale; vừa dò -> tươi; quá TTL -> stale lại. Test trực tiếp vì các test server
    monkeypatch hàm này (tránh `asyncio.to_thread` làm coverage mất trace), nên thân hàm không
    còn được chạm gián tiếp."""
    monkeypatch.setattr(gw, "_discovered", {})
    monkeypatch.setattr(gw, "_discovered_at", 0.0)
    assert gw.discovery_is_stale() is True

    gw.set_discovered_models([{"id": "m1", "name": "M1"}])
    assert gw.discovery_is_stale() is False

    monkeypatch.setattr(gw.time, "time", lambda: gw._discovered_at + gw.MODEL_CATALOG_TTL_S + 1)
    assert gw.discovery_is_stale() is True


# ---------- phủ nhánh (branch = true, audit 2026-09-27) ----------


def test_reset_hint_zero_does_not_mask_later_hint():
    # "Resets in 0s" khớp mẫu Code Assist nhưng tổng 0 giây: không dùng được, phải đọc tiếp mẫu sau.
    assert gw.reset_hint_seconds("Resets in 0s") is None
    assert gw.reset_hint_seconds("Resets in 0s. Thử lại sau 5s") == 5


def test_coerce_content_to_parts_anthropic_image_not_base64_is_skipped():
    # Ảnh kiểu Anthropic trỏ URL (không phải base64): Code Assist chỉ nhận inlineData, nên bỏ qua.
    assert gw._coerce_content_to_parts([{"type": "image", "source": {"type": "url", "url": "http://x/y.png"}}]) == []


def test_real_thought_signature_keeps_real_signature_and_ignores_non_dict_google():
    # Chữ ký thật ở `thoughtSignature` thắng chữ ký trong `extra_content`; `google` không phải dict thì bỏ qua.
    real = {"thoughtSignature": "sig-that", "extra_content": {"google": {"thought_signature": "sig-khac"}}}
    assert gw._real_thought_signature(real) == "sig-that"
    assert gw._real_thought_signature({"extra_content": {"google": "khong-phai-dict"}}) == ""


def test_sanitize_schema_keeps_union_with_several_non_null_variants():
    node = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    assert gw._sanitize_gemini_schema_node(node) == node


def test_build_request_drops_empty_system_and_empty_messages():
    # Message rỗng không thành một lượt rỗng: nếu thành, hai lượt user hai bên nó không còn liền nhau để gộp.
    payload = {"messages": [
        {"role": "system", "content": ""},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "nữa"},
    ]}
    inner = gw.build_code_assist_request(payload, "p")["request"]
    assert "systemInstruction" not in inner
    assert inner["contents"] == [{"role": "user", "parts": [{"text": "hi"}, {"text": "nữa"}]}]


def test_build_request_tool_result_without_tool_call_id_has_no_id():
    payload = {"messages": [{"role": "user", "content": "hi"}, {"role": "tool", "content": "kết quả"}]}
    contents = gw.build_code_assist_request(payload, "p")["request"]["contents"]
    assert contents[-1]["parts"][-1] == {"functionResponse": {"name": "tool", "response": {"result": "kết quả"}}}


def test_build_request_tool_calls_not_a_list_are_ignored():
    # `tool_calls` sai kiểu (một dict lẻ, một số) thì bỏ qua, giữ phần văn bản — không nổ TypeError khi lặp.
    for sai_kieu in ({"id": "c1"}, 7):
        payload = {"messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "trả lời", "tool_calls": sai_kieu},
        ]}
        contents = gw.build_code_assist_request(payload, "p")["request"]["contents"]
        assert contents[-1] == {"role": "model", "parts": [{"text": "trả lời"}]}


def test_parts_to_openai_skips_part_without_text_or_function_call():
    parts = [{"inlineData": {"mimeType": "image/png", "data": "AA"}}, {"thought": True}]
    assert gw._parts_to_openai(parts, with_index=False) == ("", "", [])


def test_translate_response_without_candidates_is_empty_stop():
    out = gw.translate_gemini_to_openai_response({"response": {"candidates": []}}, "m")
    assert out["choices"][0]["message"] == {"role": "assistant", "content": ""}
    assert out["choices"][0]["finish_reason"] == "stop"


def test_translate_response_keeps_text_when_extractor_finds_nothing(monkeypatch):
    # Nhánh phòng thủ: với hai mẫu hiện có, khớp `search` là trích được ít nhất một lời gọi; nếu bộ trích (sau
    # này đổi mẫu) trả rỗng thì phải giữ nguyên văn bản, không thay bằng bản đã gỡ mẫu.
    monkeypatch.setattr(gw, "_extract_tool_calls_from_text", lambda text: ([], ""))
    resp = {"response": {"candidates": [{"content": {"parts": [{"text": "[Tool call: f({})]"}]}}]}}
    message = gw.translate_gemini_to_openai_response(resp, "m")["choices"][0]["message"]
    assert message == {"role": "assistant", "content": "[Tool call: f({})]"}


def test_translate_response_as_content_keeps_tool_call_with_empty_arguments(monkeypatch):
    # Nhánh phòng thủ: `_parts_to_openai` luôn điền arguments bằng `json.dumps` (ít nhất "{}"); nếu arguments rỗng
    # thì không có JSON nào để đưa về `content` — giữ nguyên tool_calls thay vì trả content rỗng.
    call = {"id": "c1", "type": "function", "function": {"name": "f", "arguments": ""}}
    monkeypatch.setattr(gw, "_parts_to_openai", lambda parts, **kw: ("", "", [call]))
    resp = {"response": {"candidates": [{"content": {"parts": []}}]}}
    choice = gw.translate_gemini_to_openai_response(resp, "m", as_content=True)["choices"][0]
    assert choice["message"]["content"] is None
    assert choice["message"]["tool_calls"] == [call]
    assert choice["finish_reason"] == "tool_calls"


def test_upstream_error_message_keeps_raw_body_when_error_field_is_unusable():
    assert gw._upstream_error_message(500, '{"error": {"code": 5}}') == 'Code Assist lỗi HTTP 500: {"error": {"code": 5}}'
    assert gw._upstream_error_message(502, '{"error": 42}') == 'Code Assist lỗi HTTP 502: {"error": 42}'


@pytest.mark.asyncio
async def test_stream_event_without_candidates_emits_no_chunk():
    auth = FakeAuthManager(accounts=[
        gw_auth.AntigravityCredentials(access_token="token-a", email="a@example.com", project_id="project-a"),
    ])

    def handler(request):
        empty = {"response": {"candidates": []}}
        good = {"response": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}}
        body = f"data: {json.dumps(empty)}\n\ndata: {json.dumps(good)}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body.encode())

    client = _client(auth, handler)
    try:
        chunks = [c async for c in client.stream_chat_completion(
            {"model": "gemini-3.8-flash-medium", "messages": [{"role": "user", "content": "hi"}]}
        )]
    finally:
        await client.close()
    deltas = [json.loads(c[6:])["choices"][0]["delta"] for c in chunks if c.startswith("data: {")]
    assert deltas == [{"role": "assistant"}, {"content": "ok"}, {}]
