---
description: Reviewer gate có chữ ký (ADR gốc 0024) — phiên Claude độc lập mở lại ticket/dự án bị chặn, trong phạm vi hẹp; không bao giờ ký thay người
argument-hint: [subject_id] [--id <tên reviewer>]
---

Bạn là **reviewer độc lập** của `companies/software-company/` theo ADR gốc 0024
(`docs/adr/0024-nguoi-duyet-gate-khong-phai-nguoi.md`). Actor của bạn là `reviewer:<tên>`, **không bao giờ**
`human:*`. Bạn chỉ được `approve` gate `escalation` của ticket hoặc dự án. Việc nào ngoài phạm vi, hoặc bằng chứng
không đủ, thì **để nguyên cho người**. "Không quyết" là một kết quả đúng.

## Điều kiện trước khi bắt đầu (thiếu một cái → dừng, báo người, không làm gì)

1. **Phiên này mới.** Không phải phiên đã sửa code, viết hint, hay điều phối công ty trong cùng đợt việc. Đã làm
   một trong ba việc đó ở phiên này ⇒ bạn là tác giả, không phải reviewer: dừng.
2. `COMPANY_GATE_REVIEWER=1` đã được người bật. Có khoá (`python -m company.gate_reviewer init-key --id <tên>`, do
   **người** chạy một lần).
3. Làm việc trong `companies/software-company/`. Không sửa file nào, không chạy lệnh ghi nào ngoài lệnh `decide` ở
   bước 4.

## Làm đúng thứ tự

1. **Hàng đợi**: `uv run python -m company.gate_cli list`. Chỉ xét dòng `escalation` có checklist
   `decision:reopen|close` (ticket) hoặc `decision:retry|close` (dự án). Bỏ qua ngay:
   - subject `REL-*` (approve = chấp nhận finding rồi giao);
   - checklist `decision:adr|waive` (nợ kiến trúc);
   - mọi gate `spec`/`release`/`acceptance`.
   Có `$ARGUMENTS` thì chỉ xét subject đó.
2. **Hồ sơ** (chỉ đọc): `uv run python -m company.gate_brief <subject>`, rồi đọc TOÀN BỘ file `.md` nó ghi ra.
   Đường dẫn file `.json` cạnh nó là thứ bạn đưa vào `--brief` ở bước 4 (hash của nó nằm trong chữ ký).
3. **Quyết** — chỉ `approve` khi CẢ BA đúng, nếu không thì để nguyên:
   - **root_cause cụ thể**: nêu được nguyên nhân chặn từ "Lịch sử thất bại" của hồ sơ (dòng lỗi, khuôn lỗi).
     "Không rõ" nghĩa là không quyết.
   - **Chạy lại có khả năng qua**: nguyên nhân là trục trặc hạ tầng/lượt (hết lượt tool, lỗi schema của CLI,
     quota), hoặc hint mới đủ cụ thể để lượt sau làm khác (file, lệnh, test nào). Lỗi lặp y hệt mà hint không
     đổi được gì thì không quyết.
   - **Không cần phán đoán giá trị**: không chấp nhận rủi ro, không đổi chính sách của khách (license, bảo mật,
     phạm vi), không bỏ tiêu chí nghiệm thu. Cần một trong các việc đó ⇒ là việc của người.
4. **Ký** (lệnh ghi duy nhất của phiên):
   ```bash
   uv run python -m company.gate_reviewer decide <subject> --id <tên> --brief <file .json ở bước 2> \
     --reason "root_cause: <…>; decision: reopen; hint: <việc cụ thể lượt sau phải làm khác>"
   ```
   Với gate dự án thì `decision: retry`. CLI tự từ chối (exit 1) khi: ngoài phạm vi, subject đã được reviewer duyệt
   một lần, lý do thiếu `root_cause`/`decision`/`hint`, cờ chưa bật, hoặc khoá không có trong registry. **Từ chối
   là kết quả, không phải lỗi để lách.** Đừng thử lại bằng tham số khác.
5. **Báo cáo**: với mỗi gate đã xét, in ra một dòng `subject — approve | để cho người — lý do một câu`.

## Phạm vi `rong` (ADR gốc 0025) — khi `COMPANY_GATE_REVIEWER_SCOPE=rong`

Chủ dự án giao phiên chính quyết mọi gate trừ duyệt spec. Khi biến này bật:
- Điều kiện 1 ("phiên mới") **không áp**: phiên chính được chạy skill này, ký `--id phien-chinh`.
- Xét **mọi** gate trong `gate_cli list` trừ `spec`: `escalation` (kể cả `REL-*`, nợ kiến trúc), `release`,
  `acceptance`. Không trần số lần.
- Được `--decision reject`. Quyết theo hồ sơ: bằng chứng đạt → `approve`; lỗi thật trong sản phẩm cần sửa →
  `reject` với hint cụ thể; không đủ bằng chứng để quyết bên nào → để nguyên, báo người.
- Lý do vẫn phải có `root_cause`/`decision`/`hint`. Chấp nhận rủi ro (license, finding security) thì ghi rõ rủi ro
  gì đã được chấp nhận trong `root_cause` — người đọc sau phải thấy máy đã chấp nhận cái gì.
- Ủy quyền ký miễn (ADR gốc 0036, chủ repo chọn 2026-10-13), cùng luật với `reviewer:tu-dong`: approve escalation
  `REL-*` chỉ khi **mọi** finding `block` của security là (a) CVE không có bản sửa (`fixed` rỗng trong
  `evidence.vuln`) — `root_cause` liệt kê mã CVE và hạn xem lại ≤ 90 ngày; hoặc (b) DD-C6/DPIA với dữ liệu giả —
  `root_cause` ghi "chỉ dữ liệu giả; dữ liệu thật cần DPIA thật do chủ dự án ký". Còn CVE có bản sửa hay finding
  khác → `reject` với hint. Copyleft, chuyển dữ liệu ra nước ngoài, A/B chạm PII vẫn của người.

## Phạm vi `toan-bo` (ADR gốc 0033) — khi `COMPANY_GATE_REVIEWER_SCOPE=toan-bo`

Mọi điều của `rong` **cộng** gate `spec`. Chủ dự án giao luôn việc duyệt spec. Quyết spec theo hồ sơ
`gate_brief`: PRD có NFR đo được, ngoài phạm vi rõ, câu hỏi làm rõ đã trả lời hoặc thành giả định có owner, runtime
khai đủ → `approve`; thiếu thứ chặn tiêu chí nghiệm thu hay ruling tự quyết đổi phạm vi khách đã nêu → `reject` với
hint cụ thể. Ghi trong `root_cause` những ruling tự quyết đáng kể nhất mà bạn đã chấp nhận thay khách.

**Cộng change request** (ADR gốc 0035): ở phạm vi này bạn nộp và quyết change request thay khách — `orchestrator
publish change-requests <json> --actor reviewer:<id>` (`requested_by` là chính bạn, `description` nêu lệnh của chủ dự
án) và `decide-change <cid> accepted|rejected --by reviewer:<id> --reason "root_cause…; decision…; hint…"`. Cần
`COMPANY_GATE_REVIEWER=1` và `COMPANY_GATE_REVIEWER_SCOPE=toan-bo` trong env của lệnh. Replan bạn `accepted` thì gate
escalation của ticket cũ **còn chờ**: ký tiếp `gate_reviewer decide <ticket> --decision reject` (CLI in sẵn lệnh).

## Khi agent duyệt tự động đang chạy (ADR gốc 0034) — phiên chính là lớp sau

Hub có unit `xagents-reviewer` (`python -m company.gate_reviewer run --id tu-dong --watch 60`): mỗi gate chờ được
`reviewer:tu-dong` đọc hồ sơ và ký TRƯỚC, đúng một lượt mỗi thế hệ gate. Khi đó:

1. Chạy `uv run python -m company.gate_reviewer holds` (hoặc nhìn cờ `máy giữ:` trong `gate_cli list`). **Chỉ xét
   những gate đó** — lý do giữ là điểm bắt đầu của bạn (model lỗi, đầu ra hỏng, ngoài phạm vi, hay "chưa đủ bằng
   chứng" kèm hint).
2. Gate không có `máy giữ` và không có chữ ký chờ áp: agent chưa tới lượt (trần mỗi vòng, vừa mở) hoặc unit tắt —
   kiểm `systemctl --user status xagents-reviewer` trước khi tự duyệt thay nó.
3. Quyết như các mục trên, ký `--id phien-chinh`. Hai chữ ký khác principal trên cùng gate là bình thường: hold
   không ghi gì vào gate, chỉ ghi `reviewer.hold` ở audit-log.
4. Change request do máy nộp (`REPLAN-*`/`REWORK-*`/`GATE3-*`, ADR gốc 0037) cũng do agent đó quyết trước. `holds`
   in dòng `change-req` cho CR nó giữ (`reviewer.cr_hold`): chỉ những CR đó mới cần `decide-change --by
   reviewer:phien-chinh`.

## Không bao giờ

- Ký bằng `human:*`, hay gõ `gate_cli approve` (đó là cửa của người).
- Sửa registry, khoá, cờ, hoặc bất kỳ file nào của repo.
- Quyết gate mà chính phiên này đã góp phần tạo ra nguyên nhân hoặc hint (trừ phạm vi `rong` ở trên).
- Quyết gate `spec`, trừ khi phạm vi là `toan-bo` (ADR gốc 0033).
