"""ADR-0049: tool `read_artifact` — agent đọc đủ artifact blackboard đã bị cắt khỏi ngữ cảnh, theo TÊN namespace.

Trước đây nhãn cắt trỏ đường dẫn tuyệt đối `<db>.artifacts/…` mà `WorkspaceTools._path` từ chối mọi đường tuyệt
đối: agent không có cách nào đọc phần bị cắt (`context_trimmed` 692 lần, PRD mất tiêu chí nghiệm thu). Không gọi
mạng, không model thật: client giả."""

from __future__ import annotations

import pytest

from company.blackboard import Blackboard
from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.registry import load_agents
from company.runner import AgentRunner
from company.tools import MAX_OUTPUT, ArtifactTools, ToolBox, ToolError
from test_orchestrator import _drive_to_plan, handler
from test_tools_and_agentic import _first_turn, _init_repo, _pr, _repo_tool_handler, _task_env, _tc

PRD = "# PRD\n\nmở đầu\n\n## Phạm vi\n\nREQ-1 đăng nhập\n\n## Tiêu chí nghiệm thu\n\nAC-1 sai mật khẩu báo lỗi\n\n## Phi chức năng\n\nNFR-1 p95 < 200ms\n"


def _bb(tmp_path) -> Blackboard:
    bb = Blackboard(InMemoryBus(), store=tmp_path / "art")
    bb.write("product", "prd", "docs/prd.md", "PRD v1", content="# PRD cũ", project_id="P1")
    bb.write("product", "prd", "docs/prd.md", "PRD v2", content=PRD, project_id="P1")
    return bb


def _tool(bb: Blackboard, agent: str = "qa", pid: str | None = "P1") -> ArtifactTools:
    return ArtifactTools(bb, pid, load_agents()[agent])


def test_read_artifact_tra_dung_latest(tmp_path):
    assert _tool(_bb(tmp_path)).read_artifact("prd") == PRD, "bản mới nhất, toàn văn"


def test_read_artifact_cat_theo_muc(tmp_path):
    t = _tool(_bb(tmp_path))
    assert t.read_artifact("prd", "tiêu chí NGHIỆM THU") == "## Tiêu chí nghiệm thu\n\nAC-1 sai mật khẩu báo lỗi\n\n", (
        "đúng một mục, tới tiêu đề ## kế, không phân biệt hoa thường"
    )
    assert t.read_artifact("prd", "Phi chức năng") == "## Phi chức năng\n\nNFR-1 p95 < 200ms\n", (
        "mục cuối tới hết văn bản"
    )


def test_read_artifact_muc_khong_co_liet_ke_tieu_de(tmp_path):
    out = _tool(_bb(tmp_path)).read_artifact("prd", "Rủi ro")
    assert out.startswith("lỗi") and "Phạm vi, Tiêu chí nghiệm thu, Phi chức năng" in out


def test_read_artifact_dai_qua_tran_goi_y_muc(tmp_path):
    """Không có `section` mà artifact dài hơn `MAX_OUTPUT`: `ToolBox` sẽ cắt đuôi — đúng chỗ PRD để tiêu chí
    nghiệm thu. Đầu ra phải nói trước cách đọc tiếp (danh sách mục), không chỉ "(cắt, còn N ký tự)"."""
    bb = _bb(tmp_path)
    bb.write(
        "product",
        "prd",
        "docs/prd.md",
        "PRD v3",
        content="## Dài\n" + "x" * MAX_OUTPUT + "\n## Cuối\nAC-9\n",
        project_id="P1",
    )
    tb = _tool(bb).add_to(ToolBox())
    out = tb.call(_tc("read_artifact", namespace="prd"))
    assert out.startswith("(") and "section" in out.split("\n")[0] and "Dài, Cuối" in out.split("\n")[0]
    assert tb.call(_tc("read_artifact", namespace="prd", section="cuối")) == "## Cuối\nAC-9\n"


def test_read_artifact_tu_choi_namespace_ngoai_pham_vi_doc(tmp_path):
    bb = _bb(tmp_path)
    bb.write("security", "threat-model", "docs/threat.md", "16 mối", content="T-01 XSS", project_id="P1")
    with pytest.raises(ToolError, match="phạm vi đọc"):
        _tool(bb, "qa").read_artifact("threat-model")  # qa: context_namespace_read = [prd, api-contract]
    assert _tool(bb, "security").read_artifact("threat-model") == "T-01 XSS", "chủ namespace vẫn đọc được"


def test_read_artifact_tu_choi_du_an_khac(tmp_path):
    bb = _bb(tmp_path)
    bb.write("product", "architecture", "docs/arch.md", "C4 của P2", content="# C4 P2", project_id="P2")
    assert _tool(bb, "builder").read_artifact("architecture").startswith("lỗi"), "dự án do CODE chọn, không đọc được P2"
    assert _tool(bb, "builder", pid="P2").read_artifact("architecture") == "# C4 P2"
    # `knowledge` toàn công ty: bài học của mọi dự án — runner đã bỏ bản thô khỏi ngữ cảnh, tool cũng không mở lại
    bb.write("supervisor", "knowledge", "audit-log:lesson:T9", '{"ticket_id": "T9"}', content="bài học P2")
    with pytest.raises(ToolError, match="phạm vi đọc"):
        _tool(bb, "ops").read_artifact("knowledge")  # ops có `knowledge` trong context_namespace_read


def test_nhan_cat_tro_read_artifact_khong_phai_duong_dan(tmp_path):
    bb = _bb(tmp_path)
    bb.write("product", "prd", "docs/prd.md", "PRD dài", content=PRD + "## Phụ lục\n" + "y" * 200_000, project_id="P1")
    seen: list[str] = []

    def th(msgs, tools):
        if _first_turn(msgs):
            return [_tc("read_artifact", namespace="prd", section="Tiêu chí nghiệm thu")]
        seen.append(msgs[-1]["content"])
        return []

    client = FakeClient(handler=lambda s, u: _pr({"ticket_id": "T1"}), tool_handler=th)
    AgentRunner(bb.bus, client, blackboard=bb).generate(
        "builder", _task_env(project_id="P1"), "pull-requests", tools=ToolBox()
    )
    user = client.calls[0]["user"]
    assert 'read_artifact(\\"prd\\")' in user and tmp_path.name not in user, "nhãn trỏ tool, không trỏ đường dẫn"
    assert "read_artifact" in client.calls[0]["tools"] and seen == [
        "## Tiêu chí nghiệm thu\n\nAC-1 sai mật khẩu báo lỗi\n\n"
    ]
    # chiều ngược: lượt không có tool thì không có `read_artifact` để trỏ — nhãn cũ giữ nguyên
    client2 = FakeClient(handler=lambda s, u: _pr({"ticket_id": "T1"}))
    AgentRunner(bb.bus, client2, blackboard=bb).generate("builder", _task_env(project_id="P1"), "pull-requests")
    assert "read_artifact" not in client2.calls[0]["user"] and tmp_path.name in client2.calls[0]["user"]


def test_route_co_tool_nhan_read_artifact(tmp_path):
    """Mọi route có tool (rw, ro, research, tests) đi qua `AgentRunner.generate` — tool gắn ở đó một lần."""
    repo = _init_repo(tmp_path / "repo")
    client = FakeClient(handler=handler, tool_handler=_repo_tool_handler)
    orch = Orchestrator(InMemoryBus(), client, repo=repo, base="main")
    _drive_to_plan(orch.bus, orch)
    orch.run()
    with_tools = [c for c in client.calls if c["tools"]]
    assert {c["tools"][-1] for c in with_tools} == {"read_artifact"} and any(
        "write_file" in c["tools"] for c in with_tools
    )
    assert any("write_file" not in c["tools"] for c in with_tools), "cả route chỉ đọc lẫn route ghi"


# ---------- ADR-0049 bổ sung 2026-10-16: đọc một bản CŨ theo `version` ----------
# Hub thật (QLKH-DD-CSV, DDCSV-102): định nghĩa V-SEC7-08..27 chỉ có ở threat-model v140 §11/§12; read_artifact chỉ
# trả bản mới nhất (v163/v165) nên builder lẫn security không điền được 19/27 mã, ticket kẹt ở escalation.


def test_read_artifact_doc_ban_cu_theo_version(tmp_path):
    t = _tool(_bb(tmp_path))
    assert t.read_artifact("prd", version=1) == "# PRD cũ", "bản cũ lấy từ bus — nguồn sự thật, không phải file mirror"
    assert t.read_artifact("prd", "Phạm vi", version=2) == "## Phạm vi\n\nREQ-1 đăng nhập\n\n", "version + section"


def test_read_artifact_version_khong_co_noi_khoang_co(tmp_path):
    out = _tool(_bb(tmp_path)).read_artifact("prd", version=7)
    assert out.startswith("lỗi") and "1..2" in out


def test_read_artifact_version_khong_lot_du_an_khac(tmp_path):
    bb = Blackboard(InMemoryBus(), store=tmp_path / "art")
    bb.write("product", "prd", "docs/prd.md", "của P2", content="# PRD của dự án khác", project_id="P2")
    bb.write("product", "prd", "docs/prd.md", "PRD v1", content="# PRD P1", project_id="P1")
    assert _tool(bb).read_artifact("prd", version=1) == "# PRD P1", "dự án do code chọn, không phải theo số bản"


def test_read_artifact_version_khi_du_an_chua_co_artifact(tmp_path):
    out = _tool(_bb(tmp_path), pid="P9").read_artifact("prd", version=1)
    assert out.startswith("lỗi") and "chưa có" in out
