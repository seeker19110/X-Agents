"""K6.2/K6.3 kịch bản B — ranh giới kiểu giữa orchestrator, runner và các module `orch/`.

K6 sinh ra để chặn một kiểu trôi cụ thể: ranh giới giữa hai lớp dần biến thành `dict[str, Any]` đi qua đi lại,
và tới lúc đó mypy không còn nói được gì về nó. Ba test dưới đây khoá ba mặt của ranh giới đó.

**Một lưu ý về con số.** K6.3 gốc đặt "grep `dict[str, Any]` trong `orch/` giảm ≥ 50% so với `orchestrator.py`
hiện tại", tức đích ≤ 14 (bản 2269 dòng có 28 dòng chứa chuỗi này). Đo lại 2026-09-07 bằng SỐ LẦN XUẤT
HIỆN chứ không phải số dòng: `orch/` có 25, `orchestrator.py` còn 13 — và **phần lớn trong số đó là ĐÚNG** — chúng là
`payload` của event trên bus, tức JSON mà hợp đồng đã nằm ở `topics/schemas/*.json` và được `guard` kiểm lúc
chạy. Dựng TypedDict cho chúng là chép 19 schema sang hệ kiểu, tạo NGUỒN SỰ THẬT THỨ HAI, và nó sẽ lệch ở lần
đổi schema đầu tiên. Con số 14 vì thế đo sai thứ cần đo — cùng khuôn với K1.8 (xem `TRAPS.md` §2, "tiêu chí
nghiệm thu cũng có thể là proxy sai").

Thay bằng thứ giữ được ý định mà không ép sai thiết kế: **một cái chốt bánh cóc** — số hiện tại là trần, chỉ
được giảm, không được tăng. Ai thêm một `dict[str, Any]` mới vào `orch/` phải hoặc kiểu hoá nó, hoặc hạ trần
bằng cách kiểu hoá chỗ khác, hoặc sửa con số này KÈM lý do trong PR.
"""
from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "company"
ORCH = SRC / "orch"

# Trần bánh cóc, đo 2026-09-07. Giảm được thì giảm; tăng thì phải sửa dòng này kèm lý do trong PR.
# 25 → 27 (2026-09-08, ADR-0039 D1b): `verify.deploy_release` nhận và trả `payload` của `release-events` —
# đúng loại "kiểu ĐÚNG" mà docstring trên nói tới (hợp đồng nằm ở `topics/schemas/release-events.json` và
# `guard` kiểm lúc chạy). Chỉ +2 vì thân hàm đi một đường duy nhất thay vì ba hàm lồng nhau, mỗi hàm một chú
# kiểu; bản ghi `deploy` không cần chú kiểu riêng vì `DeployRecord.record()` mới là nguồn hình dạng của nó.
# 27 → 28 (2026-09-09, audit): `ticket_fsm._task_tu_log` nhận một phần tử `tickets` của bản ghi `plan.proposed`
# đọc thẳng từ audit-log — chính là "payload của bus" mà docstring trên gọi là kiểu ĐÚNG. Không kiểu hoá chặt
# hơn được: hàm này tồn tại để xử lý bản ghi thế hệ CŨ, tức là hình dạng KHÔNG khớp `Task` hiện hành.
# 28 → 30 (2026-09-27, ADR-0046): `verify.evidence_after` nhận và trả `payload` của `review-results` — payload của
# bus, kiểu ĐÚNG theo docstring trên. Cùng PR gom bằng chứng máy trước/sau lượt chấm (QA hồi quy + security)
# từ `orchestrator.py` vào `verify.py`, nên thân hàm của orchestrator giảm 6 dòng thay vì tăng.
TRAN_DICT_ANY = 31  # +1 (ADR-0050): `_with_debate` ở enrich.py trả payload bus như năm enrich kia


def test_k63_ba_kieu_o_ranh_gioi_van_la_dataclass_co_truong_co_kieu() -> None:
    """`StepResult` (orchestrator → CLI/console), `RunResult`/`Generated` (runner → orchestrator). Biến một
    trong ba thành `dict` là mất mọi bảo đảm kiểu ở đúng chỗ hai lớp gặp nhau, và mypy sẽ không kêu một tiếng."""
    from company.orchestrator import StepResult
    from company.runner import Generated, RunResult

    for kieu in (StepResult, RunResult, Generated):
        assert is_dataclass(kieu), f"{kieu.__name__} phải là dataclass, không phải dict"
        ten = {f.name for f in fields(kieu)}
        assert ten, f"{kieu.__name__} không có trường nào"
        for f in fields(kieu):
            assert f.type, f"{kieu.__name__}.{f.name} thiếu chú kiểu"

    assert {"event_id", "topic", "key", "actions", "deferred", "transient"} <= {f.name for f in fields(StepResult)}
    assert {"output", "tokens", "model"} <= {f.name for f in fields(RunResult)}


def test_k63_banh_coc_dict_any_trong_orch_khong_duoc_tang() -> None:
    """Đọc docstring đầu file trước khi sửa `TRAN_DICT_ANY`."""
    dem = {p.name: len(re.findall(r"dict\[str, Any\]", p.read_text(encoding="utf-8")))
           for p in sorted(ORCH.glob("*.py"))}
    tong = sum(dem.values())
    assert tong <= TRAN_DICT_ANY, (
        f"`dict[str, Any]` trong orch/ tăng lên {tong} (trần {TRAN_DICT_ANY}):\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in sorted(dem.items(), key=lambda kv: -kv[1]) if v)
        + "\n\nNếu là payload của bus thì đó là kiểu ĐÚNG — kiểu hoá một chỗ khác để hạ trần, hoặc sửa "
          "`TRAN_DICT_ANY` kèm lý do trong PR.")


@pytest.mark.parametrize("ten", ["gates_flow", "release_fsm", "scheduler", "ticket_fsm",
                                 "verify", "worktree_flow", "routes", "rehydrate"])
def test_k62_tham_so_orchestrator_luon_co_chu_kieu(ten: str) -> None:
    """`o: Orchestrator` — không phải trang trí. Bốn module trên có 46 hàm nhận `o` mà bỏ trống kiểu từ lúc tách
    (ADR-0034), nên `disallow_untyped_defs` không bật được và mypy im lặng ở đúng lớp điều phối. `from __future__
    import annotations` biến chú kiểu thành chuỗi, nên `Orchestrator` dưới `TYPE_CHECKING` là đủ, không tốn gì
    lúc chạy và không tạo vòng import."""
    src = (ORCH / f"{ten}.py").read_text(encoding="utf-8")
    tran = re.findall(r"\ndef ([a-z_]+)\(o(,|\))", src)
    assert not tran, f"{ten}.py: hàm nhận `o` mà không chú kiểu: {[t[0] for t in tran]}"


def test_k62_cau_hinh_mypy_siet_orch_theo_tien_to() -> None:
    """Khoá theo TIỀN TỐ `company.orch.*` chứ không liệt kê từng module: module mới thêm vào `orch/` tự động
    nằm trong phạm vi, không phải nhớ khai thêm. Đó là điểm của cách siết này."""
    cfg = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'module = "company.orch.*"' in cfg
    assert "disallow_untyped_defs = true" in cfg
    assert "warn_unused_ignores = true" not in cfg, (
        "cố ý KHÔNG bật: nó báo `# type: ignore` phụ thuộc nền (vd. `ctypes.windll`) là thừa trên máy này mà "
        "cần trên máy kia — CI chạy cả ubuntu lẫn windows, bật là dựng cổng đúng-sai theo máy chạy")
