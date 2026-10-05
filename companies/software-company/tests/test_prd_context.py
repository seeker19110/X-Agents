"""PRD dài phải giữ được cả mục nghiệm thu khi bị ép vào prompt."""

from company.blackboard import Blackboard
from company.bus import InMemoryBus
from company.events import Envelope, PullRequest
from company.llm import FakeClient
from company.prd_context import cut_prd_sections
from company.runner import AgentRunner


def test_cat_prd_giu_nguyen_muc_nghiem_thu_o_giua():
    context = (
        "# PRD dự án\n"
        "## 1. Bối cảnh\n" + "Bối cảnh. " * 600 + "\n"
        "## 2. Tiêu chí nghiệm thu\n- AC-01: đăng nhập được.\n- AC-02: lỗi có thông báo.\n"
        "## 3. Ghi chú triển khai\n" + "Chi tiết. " * 600 + "\n"
    )
    result = cut_prd_sections("prd", context, 900, "đọc đầy đủ ở prd.md")
    assert "AC-01: đăng nhập được" in result
    assert "AC-02: lỗi có thông báo" in result
    assert "Bối cảnh. Bối cảnh." not in result
    assert "đọc đầy đủ ở prd.md" in result
    assert len(result) <= 900


def test_prd_khong_co_heading_dung_cat_giua_va_namespace_khac_giu_mau_cu():
    plain = "p" * 5000
    assert "cắt" in cut_prd_sections("prd", plain, 700, "artifact đầy đủ trên blackboard")
    assert "cắt" in cut_prd_sections("architecture", plain, 700, "artifact đầy đủ trên blackboard")


def test_muc_nghiem_thu_qua_dai_van_duoc_uu_tien_cat_trong_muc():
    content = ("## Bối cảnh\nngắn\n"
               "## Tiêu chí nghiệm thu\nAC-01: bàn phím hoạt động.\n" + "Chi tiết. " * 400 + "\n"
               "## Ghi chú\nngắn\n")
    result = cut_prd_sections("prd", content, 500, "đọc đầy đủ ở prd.md")
    assert "AC-01: bàn phím hoạt động" in result
    assert len(result) <= 500


def test_khong_co_muc_uu_tien_thi_cat_muc_dau_co_nhan():
    content = "## Bối cảnh\n" + "b" * 3000
    result = cut_prd_sections("prd", content, 500, "đọc bản đầy đủ")
    assert result.startswith("## Bối cảnh") and "cắt" in result
    assert len(result) <= 500


def test_user_story_va_nfr_duoc_giu_khi_muc_khac_qua_dai():
    content = ("## Bối cảnh\n" + "b" * 3000 + "\n"
               "## User story\nUS-01: khách đăng nhập.\n"
               "## Yêu cầu phi chức năng\nNFR-01: phản hồi dưới 2 giây.\n")
    result = cut_prd_sections("prd", content, 600, "đọc bản đầy đủ")
    assert "US-01: khách đăng nhập" in result
    assert "NFR-01: phản hồi dưới 2 giây" in result
    assert "b" * 100 not in result


def test_prd_ngan_giu_nguyen_va_preamble_dai_khong_lam_mat_muc():
    short = "## Tiêu chí nghiệm thu\nAC-01\n"
    assert cut_prd_sections("prd", short, 500, "đọc bản đầy đủ") == short
    long_intro = "# PRD\n" + "i" * 1000 + "\n" + short
    result = cut_prd_sections("prd", long_intro, 500, "đọc bản đầy đủ")
    assert "AC-01" in result and len(result) <= 500


def test_runner_dua_muc_nghiem_thu_vao_prompt_khi_prd_qua_dai():
    bus = InMemoryBus(); bb = Blackboard(bus)
    content = ("# PRD\n## Bối cảnh\n" + "b" * 8000 + "\n"
               "## Tiêu chí nghiệm thu\nAC-01: đăng nhập được bằng bàn phím.\n"
               "## Ghi chú\n" + "g" * 8000)
    bb.write("product", "prd", "prd.md", content=content)
    client = FakeClient(responses=[{"ticket_id": "T1", "source": "reviewer", "verdict": "pass"}])
    env = Envelope(topic="pull-requests", key="T1", actor="builder", payload=PullRequest(
        ticket_id="T1", branch="ticket/T1", pr_ref="#1", local_checks={"lint": True, "tests": True}).model_dump())
    AgentRunner(bus, client, blackboard=bb, max_input_chars=5000).generate("qa", env, "review-results")
    assert "AC-01: đăng nhập được bằng bàn phím" in client.calls[0]["user"]


def test_nhan_muc_bo_van_chi_duong_dan_khi_tieu_de_dai():
    content = ("## Tiêu chí nghiệm thu\nAC-01: đăng nhập được.\n"
               "## " + "Ghi chú dài " * 30 + "\n" + "x" * 3000)
    result = cut_prd_sections("prd", content, 300, "đọc đầy đủ ở prd.md")
    assert "AC-01: đăng nhập được" in result
    assert "đọc đầy đủ ở prd.md" in result
    assert "bỏ 1 mục" in result
    assert len(result) <= 300
