"""Mô phỏng giao dự án web donghanhcungban.com (bản demo) cho công ty AI.

Không gọi model thật: `FakeClient` đóng vai 20 agent với đầu ra có nội dung theo dự án; khối kỹ thuật sửa code THẬT
trong worktree của repo khách (được tạo tạm), lint/test thật chạy, reviewer/QA đọc diff thật. Ticket T3 (form đăng ký
tình nguyện viên, chạm PII) cố ý làm sai ở lần đầu để xem QA có bắt được và vòng retry có hoạt động không.

Chạy:  cd software-company && PYTHONPATH=src uv run python examples/donghanhcungban_demo.py [--out DIR]
Model thật (`--real`): không còn client giả — 20 agent do model sinh, model theo tier trong front matter agent
(16 agent `strong`, 4 agent `standard`: intake, clarifier, supervisor, support-docs); người (kịch bản) chỉ trả lời câu
hỏi làm rõ theo mặc định, duyệt gate, ký nghiệm thu. Cấu hình qua llm.yaml hoặc biến môi trường, ví dụ:
    COMPANY_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... \
    COMPANY_MODEL_STRONG=claude-opus-5 COMPANY_MODEL_STANDARD=claude-sonnet-5 COMPANY_BUDGET_USD=20 \
    PYTHONPATH=src uv run python examples/donghanhcungban_demo.py --real --out sim-real
(OpenAI-compatible: COMPANY_LLM_PROVIDER=openai COMPANY_LLM_BASE_URL=... COMPANY_LLM_API_KEY=...). Điền `prices` trong
llm.yaml để có chi phí USD; chạm `budget_usd` thì supervisor pause dự án (gate escalation) thay vì đốt tiếp.
Kết quả: transcript ra stdout; DIR/company.sqlite (bus), DIR/company.artifacts/ (PRD, C4, OpenAPI, threat
model, docs), DIR/donghanhcungban/ (repo khách với nhánh company/integration + ticket/*).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

from company.events import Envelope
from company.gate_cli import PersistentGate
from company.llm import FakeClient, ToolCall, load_config, make_client
from company.orchestrator import ENGINEERING, Orchestrator
from company.runner import artifact_store
from company.sqlite_bus import SQLiteBus

PID = "DHCB"

# ---------------------------------------------------------------- repo khách (bản demo ban đầu: gần như trống)

def init_customer_repo(path: Path) -> Path:
    if path.exists(): shutil.rmtree(path)
    path.mkdir(parents=True)
    def git(*a: str) -> None:
        subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main"); git("config", "user.email", "dev@donghanhcungban.com"); git("config", "user.name", "dhcb")
    (path / "pyproject.toml").write_text(textwrap.dedent('''\
        [project]
        name = "donghanhcungban"
        version = "0.1.0"
        description = "Website donghanhcungban.com - ban demo"
        requires-python = ">=3.11"

        [tool.ruff]
        line-length = 120
        '''), encoding="utf-8")
    (path / "README.md").write_text("# donghanhcungban.com\n\nBản demo website Đồng Hành Cùng Bạn.\n", encoding="utf-8")
    (path / "dhcb").mkdir(); (path / "dhcb" / "__init__.py").write_text('"""Website donghanhcungban.com."""\n', encoding="utf-8")
    (path / "tests").mkdir(); (path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (path / "tests" / "test_smoke.py").write_text("import dhcb\n\n\ndef test_import():\n    assert dhcb.__doc__\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "chore: khung dự án demo")
    return path


# ---------------------------------------------------------------- code mà "khối kỹ thuật" sẽ viết (theo ticket)

ROUTER = '''\
"""Router tối giản: đường dẫn → (status, html). Không phụ thuộc framework để demo chạy được ở mọi nơi."""
from __future__ import annotations

from collections.abc import Callable

Handler = Callable[[], str]
_ROUTES: dict[str, Handler] = {}


def route(path: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _ROUTES[path] = fn
        return fn
    return deco


def handle(path: str) -> tuple[int, str]:
    fn = _ROUTES.get(path)
    if fn is None:
        return 404, "<h1>404 - Không tìm thấy trang</h1>"
    return 200, fn()


@route("/")
def home() -> str:
    return "<h1>Đồng Hành Cùng Bạn</h1><p>Kết nối tình nguyện viên với người cần đồng hành.</p>"


@route("/gioi-thieu")
def about() -> str:
    return "<h1>Giới thiệu</h1><p>Sứ mệnh: lắng nghe, đồng hành, không phán xét.</p>"
'''
TEST_ROUTER = '''\
from dhcb.web import handle


def test_home_ok():
    status, html = handle("/")
    assert status == 200 and "Đồng Hành Cùng Bạn" in html


def test_about_ok():
    assert handle("/gioi-thieu")[0] == 200


def test_404():
    assert handle("/khong-co")[0] == 404
'''
LAYOUT = '''\
"""Layout chung: header, nav, footer. Mọi trang bọc qua `page()`."""
from __future__ import annotations

NAV = [("/", "Trang chủ"), ("/gioi-thieu", "Giới thiệu"), ("/dang-ky", "Đăng ký tình nguyện")]


def page(title: str, body: str, lang: str = "vi") -> str:
    nav = "".join(f'<a href="{href}">{label}</a>' for href, label in NAV)
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} | Đồng Hành Cùng Bạn</title>'
        f'<link rel="stylesheet" href="/static/site.css"></head><body>'
        f'<header><a class="logo" href="/">Đồng Hành Cùng Bạn</a><nav aria-label="Chính">{nav}</nav></header>'
        f'<main id="main">{body}</main>'
        f'<footer><p>© 2026 Đồng Hành Cùng Bạn · <a href="mailto:donghanhcungban.org@gmail.com">Liên hệ</a></p></footer>'
        f"</body></html>"
    )
'''
CSS = ''':root{--c:#1f6f5f;--bg:#fff;--fg:#1a1a1a;font-family:system-ui,sans-serif}
body{margin:0;color:var(--fg);background:var(--bg)}header{display:flex;gap:1rem;padding:1rem;border-bottom:1px solid #ddd}
nav a{margin-right:1rem}main{max-width:64rem;margin:0 auto;padding:1rem}footer{padding:1rem;font-size:.9rem;color:#555}
'''
TEST_LAYOUT = '''\
from dhcb.layout import page


def test_page_has_lang_and_nav():
    html = page("Trang chủ", "<p>x</p>")
    assert 'lang="vi"' in html and 'aria-label="Chính"' in html and "/dang-ky" in html
'''
SIGNUP_BUGGY = '''\
"""Đăng ký tình nguyện viên: validate ở biên, không lưu PII thô ra log."""
from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL = re.compile(r"^[^@\\s]+@[^@\\s]+$")
PHONE = re.compile(r"^0\\d{9}$")


@dataclass(frozen=True)
class Volunteer:
    name: str
    email: str
    phone: str
    consent: bool


def validate(form: dict[str, str]) -> list[str]:
    errors = []
    if not form.get("name", "").strip():
        errors.append("name: bắt buộc")
    if not EMAIL.match(form.get("email", "")):
        errors.append("email: không hợp lệ")
    if not PHONE.match(form.get("phone", "")):
        errors.append("phone: 10 số, bắt đầu bằng 0")
    return errors


def register(form: dict[str, str]) -> Volunteer:
    errs = validate(form)
    if errs:
        raise ValueError("; ".join(errs))
    return Volunteer(form["name"].strip(), form["email"], form["phone"], consent=True)
'''
SIGNUP_FIXED = SIGNUP_BUGGY.replace(
    '    if not PHONE.match(form.get("phone", "")):\n        errors.append("phone: 10 số, bắt đầu bằng 0")\n',
    '    if not PHONE.match(form.get("phone", "")):\n        errors.append("phone: 10 số, bắt đầu bằng 0")\n'
    '    if form.get("consent") != "yes":\n        errors.append("consent: phải đồng ý xử lý dữ liệu cá nhân")\n',
).replace('consent=True)', 'consent=form["consent"] == "yes")')
TEST_SIGNUP = '''\
import pytest

from dhcb.signup import register, validate

OK = {"name": "Nguyễn An", "email": "an@example.com", "phone": "0912345678", "consent": "yes"}


def test_register_ok():
    v = register(OK)
    assert v.name == "Nguyễn An" and v.consent is True


def test_missing_consent_is_rejected():
    # Yêu cầu bảo vệ dữ liệu cá nhân: không có đồng ý thì không được ghi nhận
    assert any(e.startswith("consent") for e in validate({**OK, "consent": "no"}))
    with pytest.raises(ValueError):
        register({**OK, "consent": "no"})


def test_bad_phone():
    assert validate({**OK, "phone": "12345"}) == ["phone: 10 số, bắt đầu bằng 0"]
'''
SCHEMA_SQL = '''\
-- Lược đồ demo: tình nguyện viên. PII: email, phone → mã hoá at-rest, TTL 24 tháng (threat model T-03).
CREATE TABLE IF NOT EXISTS volunteers (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    phone         TEXT NOT NULL,
    consent_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_volunteers_created ON volunteers(created_at);
'''
DB_PY = '''\
"""Kết nối SQLite + migration tối giản cho bản demo."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return conn
'''
TEST_DB = '''\
from dhcb.db import connect


def test_schema_applies_and_email_unique():
    conn = connect()
    conn.execute("INSERT INTO volunteers(name,email,phone,consent_at) VALUES ('a','a@x.vn','0900000000','2026-09-02')")
    try:
        conn.execute("INSERT INTO volunteers(name,email,phone,consent_at) VALUES ('b','a@x.vn','0900000001','2026-09-02')")
    except Exception as ex:  # noqa: BLE001
        assert "UNIQUE" in str(ex)
    else:
        raise AssertionError("email phải unique")
'''

WEB_INTEGRATED = '''\
"""Router tối giản: đường dẫn → (status, html). Mọi trang bọc qua layout chung; có POST cho form đăng ký."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dhcb.db import connect
from dhcb.layout import page
from dhcb.signup import register, validate

Handler = Callable[[], str]
_ROUTES: dict[str, Handler] = {}
_STATIC = Path(__file__).resolve().parent.parent / "static"
_DB = connect()  # demo: SQLite trong bộ nhớ, một tiến trình


def route(path: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _ROUTES[path] = fn
        return fn
    return deco


def handle(path: str) -> tuple[int, str]:
    if path.startswith("/static/"):
        f = _STATIC / path.removeprefix("/static/")
        if f.is_file() and f.resolve().is_relative_to(_STATIC):
            return 200, f.read_text(encoding="utf-8")
        return 404, page("404", "<h1>Không tìm thấy tệp</h1>")
    fn = _ROUTES.get(path)
    if fn is None:
        return 404, page("404", "<h1>404 - Không tìm thấy trang</h1>")
    return 200, fn()


def handle_post(path: str, form: dict[str, str]) -> tuple[int, str]:
    if path != "/dang-ky":
        return 405, page("405", "<h1>Phương thức không hỗ trợ</h1>")
    errors = validate(form)
    if errors:
        items = "".join(f"<li>{e}</li>" for e in errors)
        return 422, page("Đăng ký", f'<h1>Đăng ký chưa hợp lệ</h1><ul class="errors">{items}</ul>{_FORM}')
    v = register(form)
    _DB.execute("INSERT OR IGNORE INTO volunteers(name,email,phone,consent_at) VALUES (?,?,?,datetime('now'))",
                (v.name, v.email, v.phone))
    return 201, page("Cảm ơn", f"<h1>Cảm ơn {v.name}!</h1><p>Chúng tôi sẽ liên hệ qua email.</p>")


_FORM = (
    '<form method="post" action="/dang-ky">'
    '<label>Họ tên <input name="name" required></label>'
    '<label>Email <input name="email" type="email" required></label>'
    '<label>Điện thoại <input name="phone" pattern="0[0-9]{9}" required></label>'
    '<label><input type="checkbox" name="consent" value="yes" required> Tôi đồng ý cho xử lý dữ liệu cá nhân</label>'
    '<button type="submit">Đăng ký</button></form>'
)


@route("/")
def home() -> str:
    return page("Trang chủ", "<h1>Đồng Hành Cùng Bạn</h1><p>Kết nối tình nguyện viên với người cần đồng hành.</p>")


@route("/gioi-thieu")
def about() -> str:
    return page("Giới thiệu", "<h1>Giới thiệu</h1><p>Sứ mệnh: lắng nghe, đồng hành, không phán xét.</p>")


@route("/dang-ky")
def signup_form() -> str:
    return page("Đăng ký tình nguyện", f"<h1>Đăng ký tình nguyện viên</h1>{_FORM}")
'''
TEST_INTEGRATION = '''\
from dhcb.layout import NAV
from dhcb.web import handle, handle_post

OK = {"name": "Nguyễn An", "email": "an@example.com", "phone": "0912345678", "consent": "yes"}


def test_every_nav_link_resolves_and_uses_layout():
    for href, _ in NAV:
        status, html = handle(href)
        assert status == 200 and 'lang="vi"' in html and 'aria-label="Chính"' in html, href


def test_static_css_served_and_no_traversal():
    assert handle("/static/site.css")[0] == 200
    assert handle("/static/../pyproject.toml")[0] == 404


def test_post_signup_ok_then_rejects_missing_consent():
    assert handle_post("/dang-ky", OK)[0] == 201
    status, html = handle_post("/dang-ky", {**OK, "consent": "no"})
    assert status == 422 and "consent" in html
'''

TICKETS: list[dict[str, Any]] = [
    {"ticket_id": "DHCB-1", "assignee": "backend", "requirement_id": "REQ-1", "title": "Router + trang chủ + giới thiệu",
     "acceptance": ["Given người dùng mở / Then thấy tiêu đề Đồng Hành Cùng Bạn", "Given đường dẫn lạ Then 404"],
     "estimate_tokens": 8_000, "budget_tokens": 20_000, "priority": 1},
    {"ticket_id": "DHCB-2", "assignee": "frontend", "requirement_id": "REQ-2", "title": "Layout chung, nav, CSS, a11y cơ bản",
     "acceptance": ["Given mọi trang Then có lang=vi, nav có aria-label, viewport meta"], "depends_on": ["DHCB-1"],
     "estimate_tokens": 8_000, "budget_tokens": 20_000, "priority": 2},
    {"ticket_id": "DHCB-3", "assignee": "backend", "requirement_id": "REQ-3", "title": "Form đăng ký tình nguyện viên (validate, consent)",
     "acceptance": ["Given form thiếu consent Then từ chối", "Given phone sai định dạng Then báo lỗi rõ"],
     "depends_on": ["DHCB-1"], "risk_tags": ["pii"], "estimate_tokens": 12_000, "budget_tokens": 30_000, "priority": 1},
    {"ticket_id": "DHCB-4", "assignee": "database", "requirement_id": "REQ-3", "title": "Lược đồ volunteers + migration",
     "acceptance": ["Given schema Then email unique, có consent_at"], "depends_on": ["DHCB-3"], "risk_tags": ["pii"],
     "estimate_tokens": 6_000, "budget_tokens": 15_000, "priority": 2},
    # Ticket tích hợp — mở sau lần mô phỏng đầu (báo cáo S1–S3): nav 404, trang không dùng layout, static 404.
    {"ticket_id": "DHCB-5", "assignee": "backend", "requirement_id": "REQ-2", "title": "Tích hợp: /dang-ky GET+POST, bọc layout mọi trang, static",
     "acceptance": ["Given mọi link trong nav Then 200 và có lang=vi", "Given POST /dang-ky hợp lệ Then 201 và lưu DB",
                    "Given POST thiếu consent Then 422", "Given /static/site.css Then 200"],
     "depends_on": ["DHCB-2", "DHCB-3", "DHCB-4"], "risk_tags": ["pii"], "estimate_tokens": 10_000, "budget_tokens": 25_000, "priority": 1},
]
for t in TICKETS: t.update(project_id=PID, retry=0)

FILES_BY_TICKET: dict[str, dict[str, str]] = {
    "DHCB-1": {"dhcb/web.py": ROUTER, "tests/test_web.py": TEST_ROUTER},
    "DHCB-2": {"dhcb/layout.py": LAYOUT, "static/site.css": CSS, "tests/test_layout.py": TEST_LAYOUT},
    "DHCB-3": {"dhcb/signup.py": SIGNUP_BUGGY, "tests/test_signup.py": TEST_SIGNUP},
    "DHCB-4": {"dhcb/schema.sql": SCHEMA_SQL, "dhcb/db.py": DB_PY, "tests/test_db.py": TEST_DB},
    "DHCB-5": {"dhcb/web.py": WEB_INTEGRATED, "tests/test_integration.py": TEST_INTEGRATION},
}


# ---------------------------------------------------------------- client giả

def _agent_of(system: str) -> str: return system.split("\n", 1)[0].lstrip("# ").strip()
def _inp(user: str) -> dict[str, Any]: return json.loads(user.split("```json\n", 1)[1].split("\n```", 1)[0])
def _first_turn(msgs: list[dict[str, Any]]) -> bool: return not any(m["role"] == "assistant" for m in msgs)
def _tc(name: str, **args: Any) -> ToolCall: return ToolCall(id=f"c-{name}-{len(json.dumps(args))}", name=name, args=args)

PRD = """# PRD — donghanhcungban.com (bản demo) v1
## Mục tiêu
Website giới thiệu tổ chức Đồng Hành Cùng Bạn và tiếp nhận đăng ký tình nguyện viên; chạy được ở dạng demo để khách xem.
## Phạm vi (Must)
- REQ-1 Trang chủ, giới thiệu, 404. Gherkin: Given mở / Then thấy tiêu đề; Given đường dẫn lạ Then 404.
- REQ-2 Layout chung, điều hướng, a11y cơ bản (lang, aria, viewport).
- REQ-3 Đăng ký tình nguyện viên: validate name/email/phone, BẮT BUỘC đồng ý xử lý dữ liệu cá nhân; lưu SQLite.
## Should
- REQ-4 Trang tin tức (ngoài bản demo).
## Out of scope
Thanh toán/quyên góp online, đăng nhập, đa ngôn ngữ (chỉ tiếng Việt).
## Rủi ro
R1 PII tình nguyện viên (email, phone) — cần consent, mã hoá at-rest, TTL.
"""
C4 = """# C4 L1–L2 donghanhcungban.com demo
L1: Người dùng (khách, tình nguyện viên) → Website. Quản trị viên xem danh sách đăng ký (ngoài demo).
L2: Router (dhcb.web) → Layout (dhcb.layout) → Signup (dhcb.signup) → SQLite (dhcb.db, schema.sql). Không framework ngoài.
"""
OPENAPI = """openapi: 3.1.0
info: {title: donghanhcungban demo, version: 1.0.0}
paths:
  /: {get: {summary: Trang chủ, responses: {'200': {description: HTML}}}}
  /gioi-thieu: {get: {summary: Giới thiệu, responses: {'200': {description: HTML}}}}
  /dang-ky: {post: {summary: Đăng ký tình nguyện viên, responses: {'201': {description: đã ghi nhận}, '422': {description: lỗi validate}}}}
"""
THREAT = """# Threat model v1 — donghanhcungban.com demo (STRIDE)
T-01 Spoofing: form đăng ký bị bot spam → rate limit + captcha nhẹ (ngoài demo).
T-02 Tampering: bypass validate phía client → validate lại ở server (REQ-3).
T-03 Information disclosure: PII email/phone trong log/DB → không log PII thô, mã hoá at-rest, TTL 24 tháng, consent bắt buộc.
T-04 DoS: không áp dụng ở demo.
"""
DOCS = """# Ghi chú phát hành demo v1.0.0 — donghanhcungban.com
- Trang chủ, giới thiệu, layout chung, form đăng ký tình nguyện viên (validate + consent), lược đồ SQLite.
- Chạy: `python -m pytest -q`; render trang qua `dhcb.web.handle(path)`.
- Runbook: lỗi 5xx → xem log có correlation id; PII không xuất hiện trong log.
"""


def handler(system: str, user: str) -> dict[str, Any]:
    a, p = _agent_of(system), _inp(user)
    pid = p.get("project_id", PID)
    if a == "intake":
        return {"project_id": pid, "kind": "intake", "data": {"goals": ["Website giới thiệu tổ chức", "Tiếp nhận đăng ký tình nguyện viên",
                 "Bản demo để khách duyệt trước khi làm bản đầy đủ"], "constraints": ["Chỉ tiếng Việt", "Không thanh toán online"]}}
    if a == "researcher":
        return {"project_id": pid, "kind": "researcher", "data": {"domain": {"segment": "tổ chức cộng đồng / hỗ trợ tâm lý đồng đẳng",
                 "references": ["website các tổ chức tình nguyện tương tự: trang chủ, giới thiệu, đăng ký, liên hệ"]},
                 "ux": {"pages": ["/", "/gioi-thieu", "/dang-ky"], "a11y": "WCAG 2.2 AA cơ bản"},
                 "codebase": {"stack": "python, chưa có code", "note": "repo khách gần trống"}}}
    if a == "synthesizer":
        return {"project_id": pid, "kind": "draft", "requirements": [
            {"id": "REQ-1", "type": "FR", "priority": "must", "text": "Trang chủ + giới thiệu + 404", "source": "brief.pdf"},
            {"id": "REQ-2", "type": "FR", "priority": "must", "text": "Layout chung, nav, a11y cơ bản", "source": "researcher/ux"},
            {"id": "REQ-3", "type": "FR", "priority": "must", "text": "Đăng ký tình nguyện viên có consent, lưu SQLite", "source": "brief.pdf"},
            {"id": "REQ-4", "type": "FR", "priority": "should", "text": "Tin tức", "source": "researcher/domain"},
            {"id": "NFR-1", "type": "NFR", "priority": "must", "text": "A11y WCAG 2.2 AA cơ bản", "source": "researcher/ux",
             "quality_char": "accessibility", "measure": "axe critical = 0"}]}
    if a == "risk":
        return {"project_id": pid, "kind": "risk", "risks": [{"id": "R1", "text": "PII tình nguyện viên: cần consent, mã hoá, TTL", "severity": "high"},
                                                            {"id": "R2", "text": "Phạm vi demo phình to (tin tức, đăng nhập)", "severity": "medium"}]}
    if a == "clarifier":
        if p.get("answers"): return {"project_id": pid, "round": 2, "questions": []}
        return {"project_id": pid, "round": 1, "questions": [
            {"id": "Q1", "text": "Bản demo có cần lưu đăng ký vào DB hay chỉ hiển thị form?", "options": ["lưu SQLite", "chỉ form"], "default": "lưu SQLite"},
            {"id": "Q2", "text": "Có cần trang tin tức trong demo?", "options": ["có", "không"], "default": "không"}]}
    if a == "spec-writer":
        return {"payload": {"project_id": pid, "status": "pending_human",
                            "artifacts": {"prd": "docs/prd.md", "requirements": "docs/requirements.json", "glossary": "docs/glossary.md",
                                          "tech-decisions": "docs/adr/0001-python-no-framework.md", "risk-register": "docs/risk-register.json"}},
                "context_writes": [{"namespace": "prd", "content_ref": "docs/prd.md", "summary": "PRD v1: 3 Must (REQ-1..3), 1 Should", "content": PRD}]}
    if a == "delivery-lead":
        if p.get("decision") == "pending":
            return {"actor": "delivery-lead", "action": "change.impact", "project_id": pid,
                    "evidence": json.dumps({"change_id": p["change_id"], "impact": {"estimate_days": 1.5, "estimate_tokens": 15_000,
                                                                                    "note": "thêm trang tin tức: 1 ticket backend + 1 frontend"}})}
        return {"items": TICKETS, "context_writes": [
            {"namespace": "architecture", "content_ref": "docs/c4.md", "summary": "C4 L1-L2 demo", "content": C4},
            {"namespace": "api-contract", "content_ref": "openapi.yaml", "summary": "OpenAPI 3.1 v1: /, /gioi-thieu, POST /dang-ky", "content": OPENAPI}]}
    if a in ENGINEERING:
        return {"ticket_id": p["ticket_id"], "branch": f"ticket/{p['ticket_id']}", "pr_ref": "#0",
                "summary": f"{p['title']} ({p['requirement_id']}); retry={p.get('retry', 0)}" + (f"; hint: {p['hint']}" if p.get("hint") else ""),
                "impact": {"requirement_id": p["requirement_id"], "rollback": "revert merge commit", "observability": "log có correlation id",
                           "licenses": "không thêm dependency"},
                "local_checks": {"lint": True, "tests": True}}
    if a in {"reviewer", "qa-debugger", "security-engineer"}:
        tid = p.get("ticket_id") or p.get("release_id") or f"SPEC-{pid}"
        if a == "security-engineer" and "artifacts" in p:
            return {"payload": {"ticket_id": tid, "source": "security", "verdict": "pass", "findings": [
                        {"level": "warn", "text": "T-03: PII → consent bắt buộc, không log PII, TTL 24 tháng", "location": "docs/threat-model.md"}]},
                    "context_writes": [{"namespace": "threat-model", "content_ref": "docs/threat-model.md", "summary": "STRIDE v1: T-01..T-04", "content": THREAT}]}
        lc = p.get("local_checks", {})
        diff = p.get("diff", "")
        if a == "reviewer" and "diff" in p:
            findings = []
            if "+++ b/dhcb/signup.py" in diff and "consent" not in diff.split("+++ b/dhcb/signup.py", 1)[1].split("\ndiff --git", 1)[0]:
                findings.append({"level": "block", "text": "REQ-3: register() không kiểm tra consent — vi phạm T-03", "location": "dhcb/signup.py"})
            if lc.get("tests") is False:
                findings.append({"level": "block", "text": "Test local fail (local_checks.tests=false)", "location": "PR"})
            if "print(" in diff: findings.append({"level": "warn", "text": "Dùng print thay vì structured log"})
            return {"ticket_id": tid, "source": "reviewer", "verdict": "block" if any(f["level"] == "block" for f in findings) else "pass",
                    "findings": findings}
        if a == "qa-debugger":
            if "release_id" in p:  # hồi quy trên staging
                return {"ticket_id": tid, "source": "qa", "verdict": "pass", "metrics": {"p95_ms": 48, "axe_critical": 0, "smoke": "3/3 trang 200"}}
            if lc.get("tests") is False:
                return {"ticket_id": tid, "source": "qa", "verdict": "fail",
                        "root_cause": "validate() không kiểm tra trường consent nên register() nhận form thiếu đồng ý; test_missing_consent_is_rejected đỏ",
                        "bug_reports": ["BUG-1: đăng ký thành công dù consent=no (dhcb/signup.py)"],
                        "metrics": {"tests_failed": 1}}
            return {"ticket_id": tid, "source": "qa", "verdict": "pass", "metrics": {"tests_failed": 0}}
        # security trên PR có risk_tags hoặc trên release
        return {"ticket_id": tid, "source": "security", "verdict": "pass",
                "metrics": {"dast_high": 0, "license_violations": 0, "pii_in_logs": 0}}
    if a == "release-engineer":
        return {"release_id": p["release_id"], "version": p.get("version", "0.0.0"), "env": p["target_env"], "status": "deployed",
                "notes": f"deploy {p['target_env']} từ integration {p.get('integration_sha', '?')[:7]}"}
    if a == "support-docs":
        if "release_id" in p:
            return {"context_writes": [{"namespace": "docs", "content_ref": f"docs/release-{p['release_id']}.md", "summary": "release notes + runbook", "content": DOCS}]}
        if "text" in p:
            return {"items": []}
        return {"items": []}
    if a == "account-manager":
        if "verdict" in p:
            return {"items": [{"change_id": "CR-DHCB-1", "project_id": pid, "requested_by": p["signed_by"],
                               "description": "Khách muốn thêm trang tin tức vào bản đầy đủ (REQ-4)", "decision": "pending"}]}
        return {"change_id": "CR-DHCB-2", "project_id": pid, "requested_by": p.get("from", "customer"), "description": p.get("text", ""), "decision": "pending"}
    raise AssertionError(f"agent không mong đợi: {a}")


def tool_handler(msgs: list[dict[str, Any]], tools: list[Any]) -> list[ToolCall]:
    names = {t.name for t in tools}
    if not _first_turn(msgs): return []
    p = _inp(msgs[0]["content"])
    if "write_file" in names:  # khối kỹ thuật
        tid = p["ticket_id"]; files = dict(FILES_BY_TICKET[tid])
        if tid == "DHCB-3" and p.get("retry", 0) >= 1:
            files["dhcb/signup.py"] = SIGNUP_FIXED
        return [_tc("list_files"), *(_tc("write_file", path=k, content=v) for k, v in files.items()), _tc("run", command="test")]
    if "run" in names:  # QA chỉ đọc: tự chạy test
        return [_tc("run", command="test")]
    return []


# ---------------------------------------------------------------- điều khiển mô phỏng

class Sim:
    def __init__(self, out: Path, real: bool = False, relay: Path | None = None, resume: bool = False,
                 auto_escalate: bool = False):
        self.out = out; out.mkdir(parents=True, exist_ok=True); self.real = real or relay is not None; self.relay = relay
        self.resume, self.auto_escalate = resume, auto_escalate
        self.db = out / "company.sqlite"
        if resume:
            self.repo = out / "donghanhcungban"
        else:
            for f in (self.db, out / "company.artifacts"):
                if f.is_dir(): shutil.rmtree(f)
                elif f.exists(): f.unlink()
            self.repo = init_customer_repo(out / "donghanhcungban")
        self.bus = SQLiteBus(self.db)
        if relay is not None:  # model = người điều phối bên ngoài (vd. Claude Code giao subagent theo tier) qua file
            from relay_client import RelayClient
            self.client: Any = RelayClient(relay, repo=self.repo, clear=not resume)
        else:
            self.client = make_client() if real else FakeClient(handler=handler, tool_handler=tool_handler)
        self.orch = Orchestrator(self.bus, self.client, repo=self.repo, base="main", artifacts=artifact_store(self.db),
                                 batch_releases=True)  # F7: một release cho cả bản demo
        self.gate: PersistentGate = self.orch.gate
        self.log: list[str] = []; self.escalated: dict[str, int] = {}

    def say(self, s: str = "") -> None:
        print(s); self.log.append(s)

    def stop_if_stuck(self, what: str) -> bool:
        """Với model thật, dự án có thể kẹt (agent lỗi → gate escalation, hết ngân sách → pause). Kịch bản không tự
        approve escalation: in trạng thái để người quyết, ghi transcript, và dừng. Trả về False nếu kẹt.
        `--auto-escalate`: người lead trong kịch bản duyệt escalation CỦA TICKET (cấp thêm ngân sách, mở lại với hint),
        tối đa 3 lần mỗi ticket; escalation cấp dự án vẫn dừng."""
        if self.auto_escalate:
            for _ in range(10):
                st = self.orch.status()
                esc = [g for g, k in st["gates_pending"].items() if k == "escalation" and g in self.orch.lead.tickets]
                if not esc: break
                for tid in esc:
                    n = self.escalated.get(tid, 0)
                    if n >= 3: continue
                    self.escalated[tid] = n + 1
                    reason = f"lead duyệt lần {n + 1}: cấp thêm ngân sách (ước lượng thấp hơn thực tế), làm tiếp theo hint"
                    self.say(f"  lead: approve escalation {tid} — {reason}")
                    self.gate.decide(tid, "approve", by="human:lead", reason=reason)
                self.orch.run()
        st = self.orch.status()
        # paused chỉ là kẹt khi có event đang bị hoãn vì nó (ticket approved bị cắt ngân sách không giữ ai lại)
        paused_blocking = sorted({r.split(":", 1)[1] for r in st["deferred"].values() if r.startswith("paused:")})
        stuck = st["stalled"] or [g for g, k in st["gates_pending"].items() if k == "escalation"] or paused_blocking
        if not stuck and (self.gate.pending or self.orch.lead.releases or not self.real): return True
        if not stuck: return True
        self.say(f"\n!! Dự án kẹt ({what}): stalled={st['stalled']} escalation={[g for g, k in st['gates_pending'].items() if k == 'escalation']} "
                 f"paused_blocking={paused_blocking} cost_usd={st['cost_usd']}")
        self.say(f"   Quyết định bằng: PYTHONPATH=src uv run python -m company.gate_cli approve|reject <subject> --by human:lead --db {self.db}")
        (self.out / "transcript.md").write_text("\n".join(self.log), encoding="utf-8")
        return False

    def pub(self, topic: str, key: str, actor: str, payload: dict[str, Any]) -> None:
        self.bus.publish(Envelope(topic=topic, key=key, actor=actor, payload=payload))

    def run(self, title: str, tick: bool = False) -> None:
        before = len(self.bus)
        self.orch.tick() if tick else self.orch.run()  # tick = như --watch: nạp event do tiến trình khác (CLI) publish
        new = list(self.bus.replay())[before:]
        self.say(f"\n== {title} == ({len(new)} event mới, lỗi={self.orch.stats['errors']})")
        for e in new:
            if e.topic in {"audit-log", "shared-context", "supervisor-actions"}: continue
            self.say(f"  {e.topic:<24} {e.key:<12} {e.actor:<18} {self._brief(e)}")
        st = self.orch.lead.state
        if st: self.say("  ticket: " + ", ".join(f"{k}={v}" for k, v in st.items()))
        if self.gate.pending: self.say("  gate chờ: " + ", ".join(self.gate.pending))

    @staticmethod
    def _brief(e: Envelope) -> str:
        p = e.payload
        if e.topic == "review-results":
            s = f"{p['source']}:{p['verdict']}"
            if p.get("root_cause"): s += f" root_cause={p['root_cause'][:70]}…"
            if p.get("findings"): s += " findings=" + "; ".join(f"[{f['level']}] {f['text'][:60]}" for f in p["findings"])
            return s
        if e.topic == "pull-requests":
            lc = p["local_checks"]
            return f"branch={p['branch']} sha={p['pr_ref'][:7]} lint={lc.get('lint')} tests={lc.get('tests')} verified_by={lc.get('verified_by')} files={p.get('impact', {}).get('files')}"
        if e.topic == "tasks": return f"{p['assignee']} retry={p.get('retry')} hint={' '.join(str(p.get('hint')).split())[:60]}"
        if e.topic == "release-events": return f"{p['env']} {p['status']} v{p['version']}"
        if e.topic == "clarification-questions": return f"{len(p['questions'])} câu hỏi"
        if e.topic == "approved-specs": return f"status={p['status']}"
        if e.topic == "change-requests": return f"{p['decision']}: {p['description'][:60]}"
        return json.dumps(p, ensure_ascii=False)[:100]


def product_smoke(root: Path) -> list[str]:
    """Bấm thử bản demo như khách: mọi link nav, static, POST form. Chạy trong tiến trình con để không dính import."""
    code = textwrap.dedent('''
        import json
        from dhcb.layout import NAV
        import dhcb.web as w
        out = {href: w.handle(href)[0] for href, _ in NAV}
        out["/static/site.css"] = w.handle("/static/site.css")[0]
        out["layout@/"] = "lang=\\"vi\\"" in w.handle("/")[1]
        post = getattr(w, "handle_post", None)
        ok = {"name": "A", "email": "a@x.vn", "phone": "0912345678", "consent": "yes"}
        out["POST /dang-ky ok"] = post("/dang-ky", ok)[0] if post else "không có handle_post"
        out["POST /dang-ky no consent"] = post("/dang-ky", {**ok, "consent": "no"})[0] if post else "không có handle_post"
        print(json.dumps(out, ensure_ascii=False))
    ''')
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0: return ["lỗi: " + r.stderr.strip()[-500:]]
    res = json.loads(r.stdout)
    want = {"/": 200, "/gioi-thieu": 200, "/dang-ky": 200, "/static/site.css": 200, "layout@/": True,
            "POST /dang-ky ok": 201, "POST /dang-ky no consent": 422}
    return [f"{'OK ' if res.get(k) == v else 'LỖI'} {k}: {res.get(k)} (mong {v})" for k, v in want.items()]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, default=Path("sim-out"))
    ap.add_argument("--real", action="store_true", help="gọi model thật theo cấu hình llm.yaml / COMPANY_* (mặc định: client giả)")
    ap.add_argument("--relay", type=Path, help="thư mục relay: mỗi lời gọi model ghi <n>.req.json, chờ <n>.res.json (examples/relay_client.py)")
    ap.add_argument("--resume", action="store_true", help="tiếp tục từ company.sqlite + repo trong --out (sau khi người quyết gate)")
    ap.add_argument("--auto-escalate", action="store_true", help="lead trong kịch bản duyệt escalation của ticket (≤3 lần/ticket)")
    ns = ap.parse_args(argv)
    s = Sim(ns.out.resolve(), real=ns.real, relay=ns.relay.resolve() if ns.relay else None, resume=ns.resume,
            auto_escalate=ns.auto_escalate)
    s.say(f"# Mô phỏng giao dự án donghanhcungban.com (demo) — out={s.out}")
    if ns.relay: s.say(f"model qua relay: {ns.relay.resolve()} (strong/standard do người điều phối chọn)")
    if ns.real and not ns.relay:
        cfg = load_config()
        s.say(f"model thật: provider={cfg.provider} strong={cfg.models.get('strong') or '?'} standard={cfg.models.get('standard') or '?'} "
              f"effort={cfg.effort} budget_usd={cfg.budget_usd} prices={sorted(cfg.prices) or 'CHƯA ĐIỀN (unpriced)'}")

    if ns.resume:
        s.say(f"tiếp tục: {json.dumps({k: s.orch.status()[k] for k in ('tickets', 'gates_pending', 'paused', 'stalled')}, ensure_ascii=False)}")
        return run_delivery(s)
    # 1. Sales đưa yêu cầu thô
    s.pub("research-requests", PID, "human:sales", {"project_id": PID, "description":
          "Khách hàng: tổ chức Đồng Hành Cùng Bạn. Cần website donghanhcungban.com bản demo: trang chủ, giới thiệu, "
          "form đăng ký tình nguyện viên. Xem demo rồi mới quyết định bản đầy đủ.", "attachments": ["brief.pdf"]})
    s.run("Khối nghiên cứu: intake → researcher → synthesizer → risk → clarifier")

    # 2. Khách trả lời câu hỏi làm rõ (model thật: hỏi gì trả lời nấy theo phương án mặc định; tối đa 2 vòng)
    answered: set[str] = set()
    for _round in range(3):
        q = s.bus.latest("clarification-questions", PID)
        if q is None or not q.payload.get("questions") or q.event_id in answered: break
        answered.add(q.event_id)
        answers = [{"question_id": str(x.get("id")), "answer": str(x.get("default") or (x.get("options") or ["đồng ý"])[0])}
                   for x in q.payload["questions"]]
        s.say("  khách trả lời: " + "; ".join(f"{a['question_id']}={a['answer']}" for a in answers))
        s.pub("clarification-answers", PID, "human:po", {"project_id": PID, "answers": answers})
        s.run("Khách trả lời → clarifier/spec-writer")
    if not s.stop_if_stuck("chưa tới approved-specs"): return 1

    # 3. Gate 1: duyệt spec
    if f"SPEC-{PID}" in s.gate.pending: s.gate.decide(f"SPEC-{PID}", "approve", by="human:po")
    s.run("Gate spec duyệt → threat model → delivery-lead lập plan → gate plan")
    if not s.stop_if_stuck("chưa có plan"): return 1

    return run_delivery(s)


def run_delivery(s: Sim) -> int:
    """Từ gate plan tới nghiệm thu: dùng cho cả chạy mới lẫn --resume."""
    # 4. Gate 2: duyệt plan
    for plan in [g for g in list(s.gate.pending) if g.startswith("PLAN")]:
        s.say("  plan: " + ", ".join(f"{t['ticket_id']}({t['assignee']},{t.get('estimate_tokens')}tok)" for t in s.orch.plans[plan]["tickets"]))
        s.gate.decide(plan, "approve", by="human:pm")
    s.run("Gate plan duyệt → dispatch ticket → code thật → review → RC → staging → QA hồi quy → gate release")
    if not s.stop_if_stuck("chưa có release chờ gate"): return 1
    if not any(g.startswith("REL") for g in s.gate.pending):
        s.say("!! Không có release chờ gate và không kẹt: xem trạng thái ở trên"); return 1

    # 5. Gate 3: release production
    for rid in [g for g in list(s.gate.pending) if g.startswith("REL")]:
        s.gate.decide(rid, "approve", by="human:release-manager")
    s.run("Gate release duyệt → production → support-docs viết docs")

    # 6. Khách nghiệm thu: conditional (muốn thêm tin tức)
    rels = list(s.orch.lead.releases)
    for rid in rels:
        s.pub("acceptance-results", rid, "account-manager", {"release_id": rid, "project_id": PID, "verdict": "accepted" if rid != rels[-1] else "conditional",
              "signed_by": "customer:po", "findings": [] if rid != rels[-1] else [{"level": "nit", "text": "Muốn thêm trang tin tức ở bản đầy đủ"}]})
    s.run("Khách nghiệm thu (release cuối conditional) → account-manager mở change request → delivery-lead ước lượng impact")

    # 7. Khách quyết định change request: hoãn sang bản đầy đủ
    from company.orchestrator import main as orch_main
    for cr in {e.key for e in s.bus.replay(topic="change-requests")}:
        orch_main(["--db", str(s.db), "decide-change", cr, "deferred", "--by", "human:po", "--reason", "để bản đầy đủ"])
    s.run("Change request deferred → không lập plan mới, ticket của release đó đóng", tick=True)

    # 8. Tổng kết
    s.say("\n== Tổng kết ==")
    status = s.orch.status(); report = s.orch.supervisor.sprint_report()
    s.say("status: " + json.dumps({k: status[k] for k in status if k in {"tickets", "queue", "deferred", "gates", "cost"} and status.get(k)}, ensure_ascii=False))
    s.say("sprint_report: " + json.dumps({k: report[k] for k in ("tickets", "rework_rate", "review_catch_rate", "prs_unverified") if k in report}, ensure_ascii=False))
    calls = len(s.client.calls) if hasattr(s.client, "calls") else sum(1 for a in s.bus.replay(topic="audit-log") if a.payload["action"].startswith("produced:"))
    s.say(f"lời gọi model{'' if s.real else ' giả'}: {calls}; lỗi orchestrator: {s.orch.stats['errors']}; event: {len(s.bus)}; "
          f"chi phí USD: {status.get('cost_usd')}; unpriced: {report.get('unpriced_calls')}")
    s.say("artifact store: " + ", ".join(sorted(str(p.relative_to(s.out)) for p in (s.out / "company.artifacts").rglob("latest.*"))))
    git = lambda *a: subprocess.run(["git", "-C", str(s.repo), *a], capture_output=True, text=True, encoding="utf-8").stdout.strip()  # noqa: E731
    s.say("repo khách branches:\n" + git("branch", "--list"))
    s.say("integration log:\n" + git("log", "--oneline", "--graph", "company/integration"))
    s.say("main của khách: " + git("log", "--oneline", "main"))
    s.say("\n== Kiểm tra sản phẩm demo trên company/integration (ngoài quy trình, như khách bấm thử) ==")
    for line in product_smoke(s.repo / ".worktrees" / "_integration"): s.say("  " + line)
    audits = [e.payload for e in s.bus.replay(topic="audit-log")]
    odd = [a for a in audits if a["action"] in {"invalid_output", "budget_exhausted", "context_no_content", "local_checks.unverified",
                                                "injection_sanitized", "context_trimmed", "agent_error", "error"}
           or a["action"].startswith("error")]
    s.say(f"audit bất thường ({len(odd)}): " + "; ".join(f"{a['actor']}:{a['action']}" for a in odd))
    (s.out / "transcript.md").write_text("\n".join(s.log), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
