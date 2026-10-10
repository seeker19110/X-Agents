from pathlib import Path

from keeper import drift


def _write_source_agent(company_root: Path, rel: str, *, version: int | None) -> None:
    p = company_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    front = "---\nid: foo\nblock: engineering\n" + (f"version: {version}\n" if version is not None else "") + "---\n"
    p.write_text(front + "\n## Vai trò\nlàm việc\n", encoding="utf-8")


def _write_sc_agent(claude_dir: Path, name: str, *, src: str, recorded_version: int) -> None:
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / f"{name}.md").write_text(
        f"---\nname: {name}\n---\n\n<!-- SINH TỰ ĐỘNG từ {src} version={recorded_version} — sửa nguồn rồi "
        "chạy make subagents -->\n\nnội dung\n",
        encoding="utf-8",
    )


def test_sc_agent_drift_phat_khi_lech(tmp_path: Path) -> None:
    company_root = tmp_path / "software-company"
    claude_dir = tmp_path / ".claude" / "agents"
    _write_source_agent(company_root, "agents/engineering/foo.md", version=2)
    _write_sc_agent(claude_dir, "sc-foo", src="agents/engineering/foo.md", recorded_version=1)

    out = drift.sc_agent_drift(claude_dir, company_root)

    assert len(out) == 1
    assert out[0].kind == "drift"
    assert "sc-foo.md" in out[0].subject


def test_sc_agent_drift_im_khi_khop(tmp_path: Path) -> None:
    """Chiều ngược của ca trên: hoàn nguyên version cho khớp lại → im lặng, không phát signal."""
    company_root = tmp_path / "software-company"
    claude_dir = tmp_path / ".claude" / "agents"
    _write_source_agent(company_root, "agents/engineering/foo.md", version=1)
    _write_sc_agent(claude_dir, "sc-foo", src="agents/engineering/foo.md", recorded_version=1)

    assert drift.sc_agent_drift(claude_dir, company_root) == []


def test_sc_agent_drift_mac_dinh_version_1(tmp_path: Path) -> None:
    company_root = tmp_path / "software-company"
    claude_dir = tmp_path / ".claude" / "agents"
    _write_source_agent(company_root, "agents/engineering/foo.md", version=None)  # không khai version → default 1
    _write_sc_agent(claude_dir, "sc-foo", src="agents/engineering/foo.md", recorded_version=1)

    assert drift.sc_agent_drift(claude_dir, company_root) == []


def test_sc_agent_drift_nguon_khong_ton_tai(tmp_path: Path) -> None:
    """File nguồn KHÔNG tồn tại → báo sai đường dẫn, không im lặng.

    Bản cũ trả mặc định `version=1` cho file thiếu, nên một bản dẫn xuất ghi `version=1` trỏ vào đường dẫn
    trống lọt lưới hoàn toàn — đúng ca đã xảy ra thật với `sc-supervisor.md` (trỏ `agents/supervision/`, thư
    mục thật là `agents/supervisor/`). Ghi `recorded_version=1` ở đây để khoá đúng ca lọt lưới ấy."""
    company_root = tmp_path / "software-company"
    claude_dir = tmp_path / ".claude" / "agents"
    _write_sc_agent(claude_dir, "sc-foo", src="agents/engineering/khong-ton-tai.md", recorded_version=1)

    out = drift.sc_agent_drift(claude_dir, company_root)
    assert len(out) == 1
    assert "KHÔNG có file đó" in out[0].detail


def test_sc_agent_drift_bo_qua_file_khong_co_comment_nguon(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude" / "agents"
    claude_dir.mkdir(parents=True)
    (claude_dir / "sc-khac.md").write_text("---\nname: sc-khac\n---\n\nkhông có comment dẫn xuất\n",
                                            encoding="utf-8")
    assert drift.sc_agent_drift(claude_dir, tmp_path / "software-company") == []


def test_golden_drift_bo_qua_file_khong_co_comment(tmp_path: Path) -> None:
    golden_dir = tmp_path / "tests" / "golden" / "agents"
    golden_dir.mkdir(parents=True)
    (golden_dir / "khac.md").write_text("không có comment golden\n", encoding="utf-8")
    assert drift.golden_drift(golden_dir, tmp_path / "software-company") == []


def test_sc_agent_drift_bo_qua_sc_gate(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude" / "agents"
    claude_dir.mkdir(parents=True)
    (claude_dir / "sc-gate-spec.md").write_text(
        "---\nname: sc-gate-spec\n---\n\n<!-- SINH TỰ ĐỘNG từ gates/checklists.md (spec) — sửa nguồn -->\n",
        encoding="utf-8",
    )
    assert drift.sc_agent_drift(claude_dir, tmp_path / "software-company") == []


def test_golden_drift_phat_khi_lech(tmp_path: Path) -> None:
    company_root = tmp_path / "software-company"
    golden_dir = tmp_path / "tests" / "golden" / "agents"
    golden_dir.mkdir(parents=True)
    _write_source_agent(company_root, "agents/engineering/foo.md", version=3)
    (golden_dir / "foo.md").write_text("<!-- golden agent=foo version=1 -->\n# foo\n", encoding="utf-8")

    out = drift.golden_drift(golden_dir, company_root)
    assert len(out) == 1
    assert out[0].kind == "drift"


def test_golden_drift_im_khi_khop(tmp_path: Path) -> None:
    company_root = tmp_path / "software-company"
    golden_dir = tmp_path / "tests" / "golden" / "agents"
    golden_dir.mkdir(parents=True)
    _write_source_agent(company_root, "agents/engineering/foo.md", version=1)
    (golden_dir / "foo.md").write_text("<!-- golden agent=foo version=1 -->\n# foo\n", encoding="utf-8")

    assert drift.golden_drift(golden_dir, company_root) == []


def test_golden_drift_nguon_khong_ton_tai(tmp_path: Path) -> None:
    company_root = tmp_path / "software-company"
    golden_dir = tmp_path / "tests" / "golden" / "agents"
    golden_dir.mkdir(parents=True)
    (company_root / "agents").mkdir(parents=True)
    (golden_dir / "ghost.md").write_text("<!-- golden agent=ghost version=2 -->\n", encoding="utf-8")

    out = drift.golden_drift(golden_dir, company_root)
    assert len(out) == 1
    assert "không có file nguồn" in out[0].detail  # không còn giả vờ "version=1"


def test_scan_tong_hop(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude" / "agents"
    claude_dir.mkdir(parents=True)
    golden_dir = tmp_path / "tests" / "golden" / "agents"
    golden_dir.mkdir(parents=True)
    company_root = tmp_path / "software-company"
    (company_root / "agents").mkdir(parents=True)

    out = drift.scan(
        claude_agents_dir=claude_dir, golden_agents_dir=golden_dir, company_root=company_root,
        changelog=tmp_path / "CHANGELOG.md",
    )
    assert out == []


# --- phép (d): chỗ trống chưa điền số PR. Ba trong bốn ca thiếu dòng CHANGELOG (2026-09-09) là "quên điền
# --- số" chứ không phải "quên viết dòng".

def test_placeholder_bat_cho_trong_that(tmp_path: Path) -> None:
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("- feat(x): việc gì đó (#PRNUM)\n", encoding="utf-8")

    out = drift.changelog_placeholder_drift(cl)
    assert len(out) == 1
    assert out[0].subject == "changelog-L1"
    assert out[0].evidence == "(#PRNUM)"


def test_placeholder_im_voi_van_xuoi_trong_backtick(tmp_path: Path) -> None:
    """Chiều ngược của ca trên: CHANGELOG **kể lại** các ca placeholder bằng văn xuôi.

    Chính `CHANGELOG.md` của repo có hai dòng như vậy (mô tả bug và mô tả luật §10). Một bộ dò báo động vì
    tài liệu MÔ TẢ nó là bộ dò người ta sẽ tắt — nên chỗ trong code span không tính."""
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("- fix: đổi `(#208)` về `(#PENDING)` → đỏ; điền `(#<n>)` rồi commit (#226)\n", encoding="utf-8")

    assert drift.changelog_placeholder_drift(cl) == []


def test_placeholder_khong_co_file_thi_im(tmp_path: Path) -> None:
    assert drift.changelog_placeholder_drift(tmp_path / "khong-co.md") == []


def test_placeholder_so_that_khong_bi_bat(tmp_path: Path) -> None:
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("- feat(x): việc gì đó (#226)\n", encoding="utf-8")
    assert drift.changelog_placeholder_drift(cl) == []
