# ADR-0041: `smoke()` bỏ qua chạy-và-giết khi spec đã khai `runtime.deploy`

Trạng thái: Accepted · Ngày: 2026-09-14 · Nối tiếp ADR-0029 (smoke là bằng chứng), ADR-0039/ADR-0040 (deploy
thật). Ranh giới tin cậy và mục đích của `smoke()` (ADR-0029) giữ nguyên — ADR này chỉ thu hẹp PHẠM VI nó chạy.

## Bối cảnh

`smoke()` (ADR-0029) và `deploy()`/`deploy_process.sh` (ADR-0039/0040) đọc **chung một khối `runtime`** trong
spec nhưng có hai bản chất khác nhau:

- `smoke()`: spawn `runtime.command` **trần** bằng `subprocess` của chính orchestrator, timeout ngắn
  (`timeout_s`, mặc định 30s), rồi giết tiến trình — đúng cho app không cần cài đặt gì trước khi chạy.
- `deploy_process.sh up` (ADR-0040): tự cài venv/dependency (`pip install --require-hashes`), có thể build
  frontend, rồi mới start — có ngân sách thời gian riêng, không giới hạn 30s.

Đo thật trên QLKH (2026-09-14, sau khi vá xong ADR-0040 + agent `ops`): 6+ release liên tục fail ở đúng bước
`smoke()` với `exit_code=127` (`npm run dev` — `runtime.command` cũ, sai, viết từ 2026-09-08 khi repo QLKH chưa
đọc được) — TRƯỚC KHI kịp chạm tới `deploy_process.sh`. Không có `runtime.command` nào sửa được: orchestrator
chạy trực tiếp bằng venv của chính nó (không có gói `qlkh`, không bắc cầu WSL), nên spawn trần một devserver
Python có dependency nặng là bất khả thi bất kể nội dung lệnh.

`legacy: true` (ADR gốc, xem `_du_an_legacy`) **không giải quyết được** ca này: nó chỉ có tác dụng khi
`parse_runtime()` trả `None` (thiếu hẳn `runtime.command`) — QLKH có khai `runtime.command` (dù sai), nên
nhánh đó không bao giờ chạy tới.

## Quyết định

1. **`smoke()` bỏ qua bước spawn-và-probe khi spec đã khai `runtime.deploy`** (khác rỗng, ADR-0039/0040) —
   kiểm tra NGAY SAU khi `parse_runtime()` trả về Runtime hợp lệ, TRƯỚC `run_smoke()`. Kết quả: `smoke =
   unverified("runtime.deploy đã khai — bằng chứng thật do deploy() cung cấp")`, `status` GIỮ NGUYÊN
   `deployed` (không đổi thành `failed`) để `deploy_release()` chạy tiếp ngay sau đó.
2. **Không mở gate escalation ở bước này.** Bằng chứng thật (thành công hay thất bại) đến từ
   `evidence.deploy` của `deploy_release()` chạy ngay sau — mở gate ở CẢ hai bước là hỏi người hai lần cho
   cùng một lượt.
3. **Không đổi hành vi khi KHÔNG có `runtime.deploy`.** App không khai deploy script (chạy Docker qua
   `compose`, hoặc không cần chạy dài hạn) vẫn đi đúng đường `smoke()` cũ — ADR này chỉ thêm một lối tắt,
   không bỏ `smoke()` nói chung.
4. **Không đổi `legacy` flag.** Hai cơ chế độc lập: `legacy` cho "không biết cách dựng", `runtime.deploy` cho
   "biết cách dựng, nhưng bằng công cụ khác `smoke()` không mô phỏng được".

## Từ chối

- **Mở rộng `smoke()` tự bắc cầu WSL + tự chờ venv** (như `deploy_process.sh`): đúng hơn về lâu dài nhưng nhân
  đôi logic đã có trong script khách — `smoke()` sẽ phải biết cả cách cài dependency của MỌI khách, đi ngược
  nguyên tắc "compose/script là của khách, công ty chỉ chạy nó" (ADR-0039 §"Bối cảnh").
- **Sửa `runtime.command` cho khớp thực tế**: không giải được gốc — mọi lệnh Python cần dependency đều fail
  cùng lý do (venv/bắc cầu WSL), không phải vấn đề nội dung lệnh.

## Bổ sung 2026-10-17: hồ sơ nghiệm thu cũng theo luật này
Hub thật (QLKH-DD-CSV, UAT-REL-126): `deploy_thay_smoke` đã áp cho `smoke()`, `regression_run()` và `dast.evidence()`,
nhưng mục `acceptance.da-chay` của `gate_brief` (ADR-0029, B4) vẫn chạy smoke trần trên cổng của spec (8080). Staging
cùng máy đang giữ cổng đó, nên mục ra `gap` ("cổng 8080 đã có tiến trình khác") trong khi production đã deploy ok ở cổng
8081 (ADR-0061 bổ sung 2026-10-17). `reviewer:tu-dong` giữ gate vì "không có bằng chứng sản phẩm chạy được".

Quyết định: `_smoke_for_brief` hỏi `deploy_thay_smoke` trước. Có lý do thì đọc `evidence.deploy` của release-event
production mới nhất của RC. Nếu `ok` và có cổng thì probe cổng đó ngay lúc dựng hồ sơ (`_smoke_running`, không khởi động,
không giết gì), ghi `deploy` = tham chiếu lần deploy. Nếu không thì `unverified` kèm lý do, mục là `unknown`, không còn
`gap` sai.

Test: `tests/test_gate_brief.py`, hai ca `runtime_deploy`. Hai chiều: trước khi sửa, cả hai đỏ (`gap` vì smoke trần với
lệnh chết); tắt nhánh mới thì đỏ lại; bật thì xanh.
