# ADR gốc 0038: agent đại diện khách — trả lời câu hỏi làm rõ và đứng tên ký văn bản của khách

Ngày: 2026-10-14 · Trạng thái: **được chấp nhận** 2026-10-14. Chủ repo trả lời câu CQ-CR2-01 ("ai có thẩm quyền ký
ADR supersede OD-2 và ngoại lệ T5b?") bằng *"thiết kế 1 agent khách ký"*. · Mở rộng: ADR gốc 0033 (phạm vi `toan-bo`),
ADR gốc 0035 (change request không cần người), ADR gốc 0036 (reviewer ký miễn CVE/DPIA dữ liệu giả), ADR gốc 0037
(`reviewer:tu-dong` quyết CR máy nộp).

## Bối cảnh

Hub thật 2026-10-14, dự án `QLKH-DD-CSV`, CR-DDCSV-INFRA-002 (image postgres dẫn xuất). `product` pha intake hỏi ba
câu làm rõ. Hai câu có phương án chủ dự án đã chọn. Câu còn lại hỏi **ai ký** hai loại văn bản trong repo khách: ADR
supersede một quyết định cũ (OD-2), và từng dòng ngoại lệ T5b (CVE chưa có bản sửa). Không có người ký thì ticket đổi
compose/CI phải chờ, và security chặn release vì thiếu chữ ký.

Hai chỗ chặn, cả hai đều ngoài tầm phiên chính:

| Chỗ | Hiện trạng |
|---|---|
| ACL bus `clarification-answers` (`core.TOPIC_PRODUCERS`) | `frozenset()` — chỉ `human:*` (HUMAN_TOPICS). Reviewer không chuyển được câu trả lời của chủ dự án vào hệ |
| CLI `orchestrator publish` | từ chối mọi actor không phải `human:*`, trừ `change-requests` (ADR gốc 0035) |

Còn "chữ ký văn bản khách" thì hub không có khái niệm nào: agent viết "Người ký: (chờ)" vào markdown, rồi chờ mãi.

## Quyết định

1. **Agent đại diện khách là hai reviewer đã có**, không phải tiến trình mới: `reviewer:tu-dong` (unit
   `xagents-reviewer`, ký trước) và `reviewer:phien-chinh` (xét phần máy giữ). Hai principal này đã có khoá Ed25519,
   registry, cờ `COMPANY_GATE_REVIEWER` và phạm vi `toan-bo` — dựng thêm một agent nữa là nhân đôi đường tin cậy.
   Agent đại diện khách **không bao giờ** dùng `human:*`.
2. **Trả lời câu hỏi làm rõ.** Ở phạm vi `toan-bo`, `reviewer:*` được phát `clarification-answers`, cùng luật ghi/tin
   với change request (ADR gốc 0035): CLI kiểm `cr_actor_refusal` khi ghi, orchestrator chỉ tính câu trả lời của
   reviewer khi cờ + phạm vi đang bật (`cr_trusted`) — bỏ biến môi trường là câu trả lời của reviewer thôi được tính
   khi replay. Câu trả lời phải nêu nguồn: lệnh chủ dự án (chat/ngày) hoặc quyết định đã có trên bus (CR, câu trả lời
   cũ); không có nguồn thì chọn `default` của câu hỏi và ghi rõ là giả định.
3. **Đứng tên ký văn bản của khách** — chỉ ba loại, mỗi loại có bằng chứng máy:
   - ngoại lệ CVE **không có bản sửa** (T5b), hạn xem lại ≤ 90 ngày — bằng chứng là chữ ký Ed25519 của gate
     escalation `REL-*` theo ADR gốc 0036;
   - ADR trong repo khách **ghi lại một quyết định chủ dự án đã đưa ra** (CR đã `accepted`, câu trả lời làm rõ) —
     bằng chứng là mã CR/câu trả lời đó;
   - câu trả lời làm rõ ở mục 2.

   Văn bản ghi người ký là `reviewer:<id> (đại diện khách, ADR gốc 0038)` kèm mã bằng chứng.
4. **Không đổi phần của người.** DPIA cho dữ liệu thật, ngoại lệ license copyleft, chuyển dữ liệu ra nước ngoài, A/B
   test chạm PII, đẩy image lên registry: agent đại diện khách trả lời "cần chủ dự án" và để chờ (hold), không chọn
   `default` thay.
5. **Cài đặt theo hai bước.** Bước 1 (PR cùng ADR này): ACL + CLI + chiều tin cho `clarification-answers`. Bước 2:
   `reviewer:tu-dong` tự trả lời câu hỏi làm rõ đang chờ (khuôn `cr_reviewer` của ADR gốc 0037), giữ cho phiên chính
   những câu chạm mục 4.

## Cái giá đã biết

- **Chữ ký văn bản là chữ trong markdown**, không phải chữ ký số trên văn bản. Bằng chứng đáng tin nằm ở chỗ khác (gate
  có chữ ký, CR trên bus); người đọc văn bản phải lần theo mã bằng chứng. Ký số từng văn bản cần ADR riêng.
- **Agent trả lời câu hỏi nghiệp vụ thay khách** có thể chọn sai ý khách. Khuôn hiện có (24 h không ai trả lời →
  lấy `default`, `COMPANY_CLARIFY_TIMEOUT_H`) đã chấp nhận rủi ro đó; mục 2 chỉ rút ngắn chờ và bắt ghi nguồn.
- Agent của công ty (security, builder) chưa được dặn trong prompt rằng `reviewer:*` là người ký hợp lệ; chúng đọc
  điều đó từ câu trả lời làm rõ và PRD. Nếu security vẫn chặn vì "chưa có người ký" thì cần sửa prompt (7 bước
  CONTRIBUTING §3).

## Phương án đã loại

- **Agent mới `khach:*` chạy riêng.** Thêm principal, khoá, registry, unit — trùng hoàn toàn đường tin cậy reviewer.
- **Phát `clarification-answers` dưới tên `human:liend`.** Giả danh người, ngược luật "không bao giờ `human:*`".
- **Chỉ chờ hạn 24 h.** `default` của CQ-CR2-01 là "chủ dự án ký" — đúng cái chủ dự án vừa bảo đừng chờ.
