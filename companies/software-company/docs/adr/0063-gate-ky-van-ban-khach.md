# ADR-0063: gate ký văn bản khách — reviewer ký số một văn bản của khách bằng gate có chữ ký

## Bối cảnh
ADR gốc 0038 cho `reviewer:*` đứng tên ký văn bản của khách, nhưng chỉ ký **bằng chữ trong markdown**, và ghi rõ:
"Ký số từng văn bản cần ADR riêng." Repo khách QLKH-DD-CSV đã dựng gate DPIA (CR-DDCSV-DPIA-002, `tools/dpia_gate`).
Gate này đòi một chữ ký số thật: một bản ghi `gate.decide` của hub, ký Ed25519, gồm 8 trường của `_SIGNED`, với
`subject_id = DPIA-SD-14`, `decision = approve` và `by = reviewer:phien-chinh`. Chủ dự án đã giao việc ký cho
`reviewer:phien-chinh` (Q-DPIA-02 = C, 2026-10-15).

Đo trên hub 2026-10-16: không có đường hợp lệ nào để có bản ghi đó.
- `gate.request` chỉ nhận người (`human:*`) và bốn vai `product`, `supervisor`, `ops`, `delivery-lead`
  (`REQUEST_ACTORS`). `reviewer:*` không mở được gate.
- Four-eyes (`gates.py:89`) cấm người mở gate tự quyết gate đó.
- Có mở được gate escalation `DPIA-SD-14` đi nữa, `reviewer:tu-dong` (ADR gốc 0034) vẫn ký trước mọi gate chờ. Chữ ký
  của nó có `by` sai principal, và gate đóng luôn trước khi phiên chính ký được.
- Orchestrator coi việc duyệt một escalation lạ là mở lại ticket (`reopen:DPIA-SD-14`).
- Không có lệnh xuất bản ghi đã ký ra định dạng repo khách đọc. Định dạng đó là phong bì
  `{record: base64(byte đã ký), signatures: [{key_id, signature: base64}]}` cùng khoá công khai base64 32 byte.

## Quyết định
1. **Gate ký là gate escalation mang dấu trong checklist**: `ky:<principal>` (người duy nhất được ký) và
   `brief:<sha256>` (hồ sơ duy nhất được ký). Trạng thái nằm trong sổ gate, nên dựng lại sau restart như mọi gate.
2. **Phiên chính xin, coordinator mở**: `python -m company.ky_van_ban request <subject> --by reviewer:<id> --brief
   <file>`.
   - Điều kiện như mọi việc reviewer làm thay khách: cờ bật và phạm vi `toan-bo` (`cr_actor_refusal`).
   - Subject phải là mã viết hoa có gạch nối, không bắt đầu bằng `REL-`, `SPEC-`, `UAT-`, và không trùng subject của
     gate nào khác gate ký trong sổ (ticket từng escalate, dự án, RC).
   - Gate do `delivery-lead` mở, nên four-eyes vẫn đúng: người mở khác người ký.
   - Audit `sign.requested` ghi đúng tên reviewer đã xin.
3. **Chỉ đúng người, đúng hồ sơ.**
   - `decide()` từ chối principal khác `ky:`, và từ chối hồ sơ có sha khác `brief:`.
   - `trusted_reviewer` kiểm lại cả hai ở chiều tin, nên bản ghi tự viết lên bus không qua được.
   - Phạm vi `toan-bo` được đọc lại mỗi lần ở cả hai chiều, như điều kiện lúc xin.
   - `reviewer:tu-dong` bỏ qua **mọi** gate ký. Nó đọc hồ sơ `gate_brief` của hub, không phải hồ sơ của khách, nên
     sha không bao giờ khớp dấu `brief:`. Gate ký là việc của người được nêu tên.
4. **Orchestrator không mở lại gì**: duyệt hay bác gate ký chỉ ghi audit `sign.decided` với `{subject_id, decision,
   by, reason}`, hành động `sign:<subject>:<decision>`.
5. **Xuất đúng byte đã ký**: `python -m company.ky_van_ban export <subject> --signature <file> --keys <dir>`.
   - Lệnh lấy bản ghi `gate.decide` mới nhất của subject mà nhánh tin cậy (registry, chữ ký, dấu `ky:`/`brief:`)
     chấp nhận.
   - Ghi phong bì `{record, signatures}`, trong đó `record` là base64 của đúng `_message` đã ký.
   - Ghi `<key_id>.pub`, là base64 của khoá công khai thô 32 byte.
   - Không có bản ghi đáng tin thì không ghi gì và thoát 1.
   - Private key không bao giờ ra khỏi máy hub.

## Cái giá đã biết
- Thẩm quyền ký đến từ quyết định của chủ dự án. Ed25519 chỉ chứng minh khoá nào đã ký (ADR DD-DPIA-23 của khách).
- Phiên chính vừa xin vừa ký. Four-eyes ở đây chỉ là hình thức (người mở là coordinator theo lời xin), giống rủi ro tự
  đề xuất tự duyệt mà chủ dự án đã chấp nhận ngày 2026-10-15.

## Phương án đã loại
- **Thêm `reviewer:*` vào `REQUEST_ACTORS`.** Four-eyes vẫn cấm phiên chính tự ký gate mình mở. Phải thêm ngoại lệ
  four-eyes cho reviewer, và mọi gate reviewer mở sẽ lọt ngoại lệ đó.
- **Ký tách rời, không có gate** (lệnh ký thẳng một digest). Bản ghi không có thế hệ gate, không có trong sổ gate,
  không có `gate.decide` trên bus để người sau lần lại. Đó đúng là thứ ADR gốc 0024 dựng gate để tránh.
- **Mở gate bằng `gate_cli request --by delivery-lead` gõ tay.** Đó là mạo danh một vai agent, không có audit nào nói
  ai xin. Gate cũng không có dấu để chặn `reviewer:tu-dong`.
