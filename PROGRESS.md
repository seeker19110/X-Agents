# PROGRESS.md — X-Agents

> Giai đoạn hiện tại: cài khung X-Templates 2.0.0 vào harness có sẵn · Cập nhật: 2026-10-17 · Nhánh: claude/install-xtemplates

## Đang làm
- `T-001` Cài khung X-Templates, gộp với harness projects-template — trạng thái: chờ review + CI — chỗ dừng: commit cục bộ trên nhánh `claude/install-xtemplates`, chưa push

## Tiếp theo
1. `T-002` Người xem lại hai cổng commit chạy đôi (`pre-commit-gate.sh` cũ + `pre-bash-guard.sh` khung) rồi quyết giữ cả hai hay không (Gate: `scripts/dev-task.sh gate`)
2. `T-003` Báo lỗi doctor sai về khung: `HOOK_SIBLING_RE` khớp `$(dirname "$0")/../..` thành tên file `..`

## Quyết định
- 2026-10-17 Giữ nguyên hook cũ (`block-dangerous-git.sh`, `pre-commit-gate.sh`, `auto-format.sh`) và mọi `deny`; chỉ THÊM hook khung — lý do: luật cấm của repo + test `test_cong_khung.py` canh chúng
- 2026-10-17 `xt.yaml` trỏ vào `scripts/dev-task.sh` (đã khớp ci.yml) thay vì chép lệnh; `merge_autonomy: L1` — lý do: người merge mọi PR như hiện nay
- Nợ kỹ thuật chấp nhận: `format: ""` trong `xt.yaml` (ruff format cả cây làm phình diff) — hạn trả: khi CI bật `ruff format --check`

## Bàn giao phiên
- Commit cuối trên nhánh chính: `19fff6e54d73f1239bc40a5d3704d353e3b450b4` (tổ tiên của HEAD) · CI: chưa chạy cho nhánh này
- Lệnh kiểm nhanh: `scripts/dev-task.sh gate` (cả 5 gói) hoặc `python3 .xtemplates/scripts/xt.py doctor`
- Đang chặn: không
- Việc dở chưa commit: không
- Câu hỏi cần người: gate khung chạy cả 5 gói song song với cổng cũ chỉ chạy gói bị đụng — có chấp nhận thời gian commit gấp đôi không
