# ADR-0053: Phụ thuộc ngoài thì bằng chứng chạy đến từ compose — Gate 1 đòi `runtime.deploy`

Trạng thái: Accepted · Ngày: 2026-10-12 · Nối tiếp ADR-0031 (`runtime` trong spec), ADR-0035 (sandbox tắt mạng),
ADR-0039 (deploy compose), ADR-0041 (smoke nhường `deploy()` khi spec khai `runtime.deploy`). Chủ dự án chọn hướng
compose ngày 2026-10-12 thay cho hướng "smoke tự dựng phụ thuộc".

## Bối cảnh

Hub thật 2026-10-12, dự án `QLKH-DD-CSV`. Spec (đã qua Gate 1) khai:

```
runtime.command      = python -m qlkh.server --port {port}
runtime.dependencies = ["PostgreSQL đã áp migration …; chuỗi kết nối qua QLKH_DB_DSN, thiếu biến này thì tiến
                        trình thoát với mã khác 0", "Môi trường Python đã cài phụ thuộc của repo …"]
runtime.deploy       = (không khai)
```

Kết quả đo: REL-001 → REL-010 đều `failed` ở smoke staging, mỗi RC một gate escalation. Ngay cả khi điểm vào có mặt
(ticket DDCSV-02), smoke vẫn chắc chắn đỏ: `run_smoke` chạy `command` trần trong sandbox `--network none`
(ADR-0035). Không ai dựng PostgreSQL, và chính spec nói thiếu DB thì thoát khác 0.

Hai lỗ:

1. **Gate 1 cho qua một spec mà release không bao giờ kiểm được.** `spec_runtime_gap` chỉ đòi `command`/`port`/
   `health`, không đối chiếu `dependencies` với cách sẽ dựng chúng. Người ký spec thấy "có runtime" và ký.
2. **Smoke không đọc `dependencies`.** ADR-0041 chỉ nhường `deploy()` khi `runtime.deploy` được khai đích danh.
   Trong khi đó `deploy()` (ADR-0039 §1) vẫn tự dò `docker-compose.yml` / `compose.yaml` khi không khai. Hai nơi
   đọc cùng khối `runtime` nhưng kết luận khác nhau về "có compose hay không".

## Quyết định

1. **Gate 1: phụ thuộc ngoài ⇒ phải khai `runtime.deploy`.** Spec `kind=application` có `runtime.dependencies`
   khác rỗng (bỏ dòng trắng) mà `runtime.deploy` rỗng ⇒ `spec_runtime_gap` trả lý do. Spec đi đúng đường ADR-0031:
   trả `product` pha `spec` kèm `hint`, quá `SPEC_RUNTIME_REWORKS` thì escalation cấp dự án. `hint` yêu cầu ba việc:
   - khai `runtime.deploy` là file compose trong repo khách, dựng đủ phụ thuộc, migration và app;
   - kế hoạch phải có ticket tạo file đó;
   - phụ thuộc chạy trong tiến trình (sqlite, in-memory) thì để `dependencies` rỗng, đúng mô tả của schema
     ("rỗng = chạy in-memory được").
2. **Spec duyệt trước quyết định 1: smoke nhường `deploy()` khi có cả hai điều kiện.** Hai điều kiện là
   `dependencies` khác rỗng **và** `compose_file()` (đúng hàm `deploy()` dùng) dò ra file trong thư mục sẽ deploy.
   Khi đó `smoke()` và `regression_run()` ghi `unverified` kèm tên file, rồi đi tiếp như ADR-0041 quyết định 1–2.
   Hai hàm dùng **một** điều kiện (`verify._deploy_thay_smoke`), không phải hai bản sao.
3. **Không đổi hành vi khi thiếu một trong hai.**
   - Có compose mà không khai phụ thuộc: app tự chạy được, smoke trần vẫn là bằng chứng (ADR-0041 quyết định 3).
   - Khai phụ thuộc mà repo chưa có compose: smoke trần chạy và fail thật. Escalation nói đúng chuyện "chưa có cách
     dựng", không giả vờ đã kiểm.
4. **Người vận hành bật `COMPANY_DEPLOY=compose` trên hub có dự án như vậy.** Đây là chế độ fail-closed của ADR-0039
   §4. Thiếu `docker` thì là lỗi, không phải `skipped`. Như thế nhường smoke cho `deploy()` không thành "không ai kiểm".

## Từ chối

- **Smoke tự dựng phụ thuộc** (đọc `dependencies`, bật container postgres trên mạng riêng, áp migration). Cách này
  không đòi khách có compose, nhưng orchestrator phải biết dựng **từng loại** phụ thuộc và cách migrate của **từng**
  khách. Ngược nguyên tắc "compose/script là của khách, công ty chỉ chạy nó" (ADR-0039 §Bối cảnh, ADR-0041 §Từ chối).
  Chủ dự án không chọn.
- **Nhường `deploy()` mỗi khi repo có compose file.** Có file chưa nói gì về việc app cần nó. App tự chạy được
  thì smoke trần rẻ hơn và vẫn là bằng chứng thật.

## Hệ quả

- Dự án đã duyệt spec (như QLKH-DD-CSV) cần compose file trong repo khách. File đó đi qua change request, để
  `product` lập ticket và `builder` viết. Công ty không sinh file thay khách (ADR-0039 §6).
- `runtime.deploy` khai mà `deploy()` bị `skipped` (`COMPANY_DEPLOY=off`, hoặc `auto` mà thiếu docker) thì RC vẫn
  không có bằng chứng chạy. Đây là lỗ có từ ADR-0041 và không mở rộng thêm ở đây. Quyết định 4 là cách đóng nó trên
  hub; đóng bằng code là việc sau.
- Chưa làm, cố ý:
  - `_check_plan` chưa đối chiếu "spec khai `runtime.deploy` mà repo chưa có file đó thì kế hoạch phải có ticket tạo
    nó". Hiện mới dựa vào `hint` của quyết định 1.
  - Prompt `product` chưa nhắc `runtime.deploy`. Sửa prompt cần bảy bước `CONTRIBUTING.md` §3 với model thật.

## Đo hai chiều

- Bỏ nhánh mới của `spec_runtime_gap` ⇒ `test_gap_phu_thuoc_ngoai_ma_khong_khai_deploy` đỏ.
- Bỏ vế `dependencies + compose_file` của `_deploy_thay_smoke` ⇒ hai test sau đỏ (`failed`, `run_smoke` chạy):
  - `test_phu_thuoc_ngoai_va_repo_co_compose_thi_smoke_tran_nhuong_deploy`;
  - `test_hoi_quy_phu_thuoc_ngoai_va_compose_khong_chay_smoke_tran`.
- Hai chiều ngược phải giữ xanh: `test_compose_ma_khong_khai_phu_thuoc_thi_van_smoke_tran` và
  `test_phu_thuoc_ngoai_khong_co_compose_thi_van_smoke_tran`.
