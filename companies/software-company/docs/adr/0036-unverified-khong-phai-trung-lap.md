# ADR-0036: `smoke.unverified` không phải một trạng thái trung lập

Ngày: 2026-09-07 · Trạng thái: được chấp nhận · Sửa: ADR-0029 mục 3 · Epic: K1.5 của `docs/DAC-TA-KICH-BAN-B.md`

## Bối cảnh

ADR-0029 mục 3 quyết định: orchestrator không smoke được (spec thiếu `runtime`, hoặc không có worktree tích hợp)
thì ghi `smoke.unverified` kèm lý do và **giữ nguyên `status=deployed`** — "không chặn dự án chưa khai, nhưng
bằng chứng nói rõ là chưa kiểm". Việc chặn để dành cho chặng sau: QA hồi quy đọc `evidence.run`, thấy
`unverified` với `spec_kind=application` thì hạ verdict xuống `fail` (`verdict_with_run`), delivery-lead mở gate
`escalation`.

ADR-0031 sau đó bịt đầu vào: spec `kind=application` thiếu `runtime` không được mở Gate 1, bị trả lại spec-writer.
Cộng hai lớp đó lại, đọc qua thì tưởng đường này đã kín.

Nó không kín. Lần theo đúng chuỗi hàm:

1. Dự án được duyệt **trước** ADR-0031 (hoặc `integ` biến mất giữa chừng) → tới `verify.smoke` với `rt is None`.
2. `status` giữ `deployed`, RC đi tiếp.
3. QA hồi quy hạ `fail` → `Delivery._on_release_qa` mở gate `escalation` cho chính release đó.
4. Người duyệt escalation bằng `approve` → `gates_flow` gọi **`Delivery.waive_release_findings(rid)`**, hàm này
   waive **mọi** nguồn chưa `pass` — `sources = [s for s, x in release_reviews[rid] if x.verdict != "pass"]` —
   tức là gồm cả `qa`.
5. `_maybe_open_release_gate`: `got = pass ∪ waived` nay đủ → mở Gate 3.
6. Người duyệt Gate 3 → RC lên production.

Cơ chế waive được thiết kế cho **finding không có code để sửa** (DPIA, license, policy — xem docstring của
`waive_release_findings`). Nó không phân biệt được finding đó với **"chưa bao giờ kiểm sản phẩm có chạy
không"**. Người duyệt escalation nhìn thấy một dòng "qa: fail" và một lý do dài; bấm `approve` là waive luôn cả
hai loại. Đây đúng là hình dạng đã đo được ngày 2026-09-06 ở QLKH: bốn gate xanh, 25 release, 0 điểm vào chạy
được — và cách nó thoát ra là qua một chữ ký của người, không phải qua một lỗi của máy.

## Quyết định

`unverified` với sản phẩm **phải chạy được** là `failed`, quyết ngay tại `verify.smoke`, đi đúng đường của smoke
fail (RC `status=failed` + mở gate `escalation`).

1. **Loại sản phẩm quyết, không phải sự im lặng.** `kind` đọc từ `approved-specs`, thiếu `kind` = `application`
   (giữ nguyên quy ước ADR-0031: im lặng không phải miễn trừ). `library`/`docs` vẫn đi tiếp với bằng chứng
   `unverified` — chúng không có server để mà kiểm.

2. **Cửa thoát là `legacy: true` trong `research-requests.payload`**, không phải trong spec. Lý do: spec do model
   viết, `research-requests` do người mở dự án viết. Một cờ cho phép bỏ qua bằng chứng chạy được mà để model tự
   bật thì nó sẽ tự bật. Cờ khai một lần lúc mở dự án, khai tường minh trong schema (không đi lén qua
   `additionalProperties`).

3. **Chặn sớm hơn một chặng, có chủ ý.** Chặn ở smoke thay vì ở QA vì (a) `failed` không có route đi tiếp nên
   không waive được — muốn đi tiếp phải sửa spec rồi redeploy, đúng việc cần làm; (b) không tiêu lượt QA cho một
   RC đã biết là không kiểm được; (c) `status` ở staging nói thật ngay tại chỗ nó được ghi.

4. **Một chỗ quyết duy nhất** cho cả hai nhánh không-kiểm-được (thiếu `runtime`, thiếu worktree). Hai nhánh xử
   lý giống nhau mà viết hai chỗ thì sớm muộn lệch.

   > Đối chiếu 2026-09-22: cài đặt thật là hàm `smoke.unverified(reason)` (một chỗ dựng khối `smoke` chưa kiểm),
   > gọi từ hai nhánh trong `orch/verify.py::smoke` (thiếu `runtime`, và ADR-0041 `runtime.deploy` đã khai) —
   > không có hàm `verify._chua_kiem` như bản đầu ADR viết.

## Hệ quả

**Được.** Lỗ "waive nuốt cả bằng chứng chạy được" đóng lại ở đầu vào của nó. Người duyệt escalation không còn
phải phân biệt hai loại finding trông giống nhau — loại nguy hiểm không tới được tay họ dưới dạng waive được nữa.

**Mất.** Dự án cũ đang chạy mà chưa khai `legacy` sẽ thấy RC chuyển `failed` sau khi nâng cấp. Đó là **có chủ ý**:
lỗi hiện ra ồn ào ở lần release đầu tiên sau nâng cấp, kèm gate escalation nói rõ phải làm gì (khai `runtime`,
hoặc khai `legacy: true`), thay vì im lặng đi tiếp. Đường sửa là một dòng trong `research-requests`.

**Không đổi.** ADR-0029 mục 3 vẫn đúng cho `library`/`docs` và cho dự án `legacy`: `unverified` không chặn, bằng
chứng nói thẳng là chưa kiểm. Chuỗi QA hồi quy → `verdict_overridden` → escalation vẫn nguyên vẹn và vẫn là lớp
chặn cho đường `legacy` (test `test_khong_runtime_kind_application_legacy_thi_qa_hoi_quy_van_chan`).

**Chưa làm.** `waive_release_findings` vẫn waive theo nguồn chứ không theo từng finding. ADR này chỉ chặn loại
finding nguy hiểm nhất **không đi vào** đường waive; nó không sửa cơ chế waive. Nếu sau này có loại finding thứ
hai "không được waive" thì phải phân loại finding thật sự, không thêm case-by-case ở đây.

## Bổ sung 2026-10-17: nguồn fail đến SAU khi miễn đã áp thì hỏi lại
Hub thật (QLKH-DD-CSV, REL-126): escalation của RC đã duyệt và miễn đã áp (`release_waived` có nguồn). Sau đó một nguồn
khác báo `fail`. `_on_release_qa` chỉ hỏi escalation khi `not _gate_kind_approved(rid, "escalation")`, mà escalation cũ
đã duyệt, nên không mở gate nào. Nguồn mới cũng không nằm trong `release_waived`, nên Gate 3 không mở. RC treo im lặng.

Quyết định: escalation đã duyệt chỉ chặn hỏi lại khi miễn **chưa áp** (`release_waived[rid]` rỗng). Khi đó miễn sắp áp
sẽ phủ mọi nguồn đang fail, nên hỏi lại là trùng. Đã áp rồi thì nguồn fail mới chưa ai thấy, nên mở escalation mới.

Còn hở (chưa làm): miễn áp MUỘN vẫn phủ cả nguồn fail đến giữa lúc ký và lúc áp, dù người ký chưa thấy nguồn đó. Muốn đóng
thì phải ghi tập nguồn người ký đã thấy vào quyết định, tức là đổi schema gate.

Test: `tests/test_release_escalation_orchestrator.py`, hai ca mới. Hai chiều: trước khi sửa, ca "fail sau khi đã áp"
đỏ (`gate.pending` rỗng); ca "đã duyệt chưa áp" xanh ở cả hai phía và canh không hỏi trùng.

## Liên quan

- ADR-0029 (bằng chứng máy chạy cho `deployed`) — mục 3 bị sửa bởi ADR này.
- ADR-0031 (Gate 1 đòi `runtime`) — lớp chặn ở đầu vào; ADR này là lớp sau cho dự án lọt trước nó.
- `docs/DAC-TA-KICH-BAN-B.md` K1.5 và T2 ("có lời khai nào của model thành sự thật mà không qua code?").
- `docs/reports/2026-09-06-ban-giao-khong-chay-duoc.md` — chỗ hình dạng lỗi này được đo lần đầu.
