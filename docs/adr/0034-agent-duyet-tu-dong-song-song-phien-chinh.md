# ADR gốc 0034: agent duyệt tự động `reviewer:tu-dong` chạy song song phiên chính — phiên chính chỉ can thiệp khi máy giữ

Ngày: 2026-10-12 · Trạng thái: **được chấp nhận** 2026-10-12 (chủ dự án quyết trong chat, xem Bối cảnh) · Sửa: ADR gốc
0025/0033 (phiên chính không còn là người duyệt đầu tiên) · Liên quan: ADR gốc 0024 (đường chữ ký, độc lập bằng code),
ADR gốc 0032 (hub systemd), ADR-0043 của software-company (sàn tự duyệt)

## Bối cảnh

- Sau ADR gốc 0033, mọi gate do **phiên chính** ký (`reviewer:phien-chinh`, phạm vi `toan-bo`). Đo 2026-10-12 trên hub
  thật: phiên chính vừa sửa X-Agents (PR #436–#442, ADR-0053) vừa phải quay lại đọc hồ sơ cho từng gate; 11 gate
  escalation (REL-001→010, DDCSV-02) xếp hàng trong lúc phiên chính đang sửa code. Người và phiên chính đều thành
  nút thắt.
- Chủ dự án yêu cầu: *"sửa luật không cần người phải duyệt nữa: tạo thêm 1 agent duyệt, song song với phiên chính,
  không duyệt được thì phiên chính mới can thiệp"*.
- Kho `stored` của chủ dự án (mục 03, 07, 21, đọc 2026-10-12) rút ra: tách **generator–evaluator** (Anthropic Labs
  2026-03), evaluator chỉ đáng tiền khi task vượt ngưỡng model làm ổn một mình; guardrail tối thiểu cho workflow tự
  trị = giới hạn vòng + ngân sách là hard stop + cổng người theo mức rủi ro + kiểm chứng ngoài + hạn sử dụng +
  observability; "evidence or it's a FAIL".
- ADR gốc 0024 đã dựng xong đường ghi: chữ ký Ed25519, registry public key, `refusal()` một chỗ cho chiều ghi và
  chiều tin, hồ sơ `gate_brief` có hash trong chữ ký. Thiếu đúng một thứ: **tiến trình tự đọc hồ sơ rồi ký**.

## Quyết định

1. **Một principal mới `reviewer:tu-dong`, khoá riêng**, không dùng chung khoá với `phien-chinh`. Người chạy
   `gate_reviewer init-key --id tu-dong` một lần. Lịch sử gate phân biệt được máy tự quyết với phiên chính quyết.
2. **Tiến trình riêng `python -m company.gate_reviewer run --id tu-dong --watch <giây>`**, unit systemd
   `xagents-reviewer.service` (bật mặc định cùng ba unit kia, ADR gốc 0032). Mỗi vòng: nạp trạng thái chỉ đọc
   (`gate_brief.load_state`), với mỗi gate đang chờ mà **chưa có lượt nào ở thế hệ này**: dựng hồ sơ `gate_brief`
   (ghi ra đĩa như người đọc), gọi model tier `strong` với prompt `gates/reviewer-tu-dong.md`, nhận JSON
   `{decision: approve|reject|hold, root_cause, hint}`; `approve`/`reject` đi đúng `gate_reviewer.decide()` (chữ ký,
   `refusal()`, hash hồ sơ); `hold` hoặc đầu ra không hợp lệ ⇒ ghi audit `reviewer.hold` kèm lý do, **không** ghi
   gì vào gate.
3. **Độc lập bằng code (ADR gốc 0024 §3)**: tiến trình không có tool ghi, không có worktree, không đọc hội thoại
   nào; đầu vào duy nhất là hồ sơ `gate_brief` + checklist của gate. Prompt nằm ở `gates/reviewer-tu-dong.md`
   (không phải `agents/`: nó không đọc/ghi topic, không phải vai của công ty; 7 bước `CONTRIBUTING.md` §3 không
   áp — test cổng kiểm cấu trúc prompt thay cho golden).
4. **Bốn số của một vòng tự trị** (kho `stored` mục 21 §8): mỗi (subject, thế hệ gate) **đúng một lượt** — hold
   thì để phiên chính, không hỏi model lần hai; tối đa `COMPANY_GATE_REVIEWER_MAX_PER_TICK` gate một vòng (mặc
   định 5); hồ sơ cắt theo `max_input_chars` của cấu hình LLM; token/USD mỗi lượt ghi vào audit `reviewer.decided`
   / `reviewer.hold`.
5. **Phiên chính là lớp sau**: `gate_cli list` in `máy giữ: <lý do>` cạnh gate có `reviewer.hold` ở thế hệ hiện tại;
   `/gate-review` xét **những gate đó trước**, rồi gate chưa được máy chạm (reviewer chưa bật/chưa tới lượt). Người
   `reject`/`rollback` sau đó luôn thắng như ADR gốc 0024 §5.
6. **Phạm vi và cờ dùng chung** với phiên chính: `COMPANY_GATE_REVIEWER=1`, `COMPANY_GATE_REVIEWER_SCOPE` (hub này
   `toan-bo`). Tắt agent = tắt unit; tắt cả hai = bỏ cờ.

## Phương án đã loại

- **Agent thứ 7 trong `agents/`** (`reads`/`writes` rỗng): 6 chỗ khoá cứng "6 agent" (registry, subagents, thresholds,
  eval REQUIRED, README, assetscan) và nó không phải vai của công ty — không đọc topic nào, không ghi topic nào.
- **Phiên chính chạy `/loop` tự duyệt**: không độc lập (ADR gốc 0024 §Bối cảnh 3), chiếm context của phiên đang sửa
  code, và chết cùng phiên.
- **Hai reviewer độc lập cùng rubric, cả hai phải đồng ý** (Santa method, kho `stored` mục 07): đúng hướng khi
  `reviewer:tu-dong` đo được tỷ lệ sai; chưa có số thì chưa thêm. Ghi ở "Chưa làm".
- **Hỏi lại model khi hold**: tốn tiền cho cùng hồ sơ; hold là dữ liệu cho phiên chính, không phải lỗi tạm.

## Hệ quả

- **Đổi code** (`companies/software-company`): `gate_reviewer.py` thêm `run`, `holds`, hàm `review_one()` với client
  tiêm được (test dùng `FakeClient`); `gates/reviewer-tu-dong.md`; `gate_cli list` in `máy giữ`. Hub: unit
  `deploy/systemd/xagents-reviewer.service`, `scripts/systemd.sh`, `hub.env.example`, `docs/TRIEN-KHAI-SYSTEMD.md`.
- **Đổi luật**: `CLAUDE.md` §"Khi vận hành công ty" và `.claude/commands/gate-review.md`: phiên chính không còn duyệt
  mọi gate, chỉ gate `máy giữ`. `docs/TRUC-VA-DUNG-KHAN.md`: lệnh dừng khẩn `systemctl --user stop xagents-reviewer`.
- **Chưa làm, cố ý**: Santa (hai reviewer); console hiển thị `reviewer.hold`; eval với model thật cho prompt reviewer
  (chưa có bản ghi — điểm chấm đầu tiên lấy từ hub thật, ghi `docs/reports/`).
- **Đo hai chiều**: tắt `review_one` ⇒ gate chờ mãi, `reviewer.hold` không xuất hiện; model trả `hold` ⇒ không có
  `gate.decide`; model trả `approve` ngoài phạm vi ⇒ `refusal()` chặn, ghi hold với lý do từ chối; cùng (subject,
  thế hệ) hai vòng ⇒ model chỉ được gọi một lần.
