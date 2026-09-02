---
name: database
version: 2
standards: [Chuẩn hóa 3NF, ACID và mức cô lập, Expand–contract migration, Index design, PII protection, Backup/restore có kiểm chứng]
---
# Skill: database

## Tiêu chuẩn tham chiếu
- Chuẩn hóa tới 3NF làm mặc định; phi chuẩn hóa chỉ khi có số đo biện minh
- ACID và các mức cô lập (read committed / repeatable read / serializable) — biết mức đang dùng và hiện tượng nó cho phép
- Expand–contract (mở rộng rồi thu hẹp) cho mọi thay đổi schema trên hệ thống đang chạy
- Thiết kế index theo mẫu truy vấn thật, kiểm bằng EXPLAIN
- Bảo vệ PII: phân loại, mã hóa, che, retention (xem `privacy-compliance`)
- Backup có RPO/RTO khai báo và có diễn tập phục hồi

## Quy trình (làm đúng thứ tự)
Mô hình hóa từ nghiệp vụ (thực thể, quan hệ, ràng buộc) → đặt ràng buộc toàn vẹn ở DB → viết truy vấn cho ca dùng chính → thiết kế index theo truy vấn đó và đo bằng EXPLAIN → viết migration theo expand–contract → thử migration trên bản sao dữ liệu cỡ production, đo thời gian và khóa → triển khai tách khỏi deploy code → theo dõi truy vấn chậm sau khi lên.

## Quy tắc — mô hình và toàn vẹn
- Ràng buộc là việc của DB: khóa chính, khóa ngoại, `NOT NULL`, `UNIQUE`, `CHECK`. Không dựa vào ứng dụng để giữ toàn vẹn.
- Kiểu dữ liệu đúng nghĩa: tiền là số nguyên đơn vị nhỏ nhất hoặc `numeric`, không dùng float; thời gian là `timestamptz` lưu UTC; enum có ràng buộc; không dùng chuỗi cho mọi thứ.
- Xóa mềm phải có lý do rõ và có chỉ mục lọc; nếu không, xóa thật và lưu lịch sử ở bảng riêng.
- Đa khách (multi-tenant): khóa tenant nằm trong khóa chính hoặc có row-level security; mọi truy vấn lọc theo tenant.
- Biết mức cô lập đang dùng: thao tác đọc-rồi-ghi phải khóa lạc quan (cột version) hoặc `SELECT ... FOR UPDATE`.

## Quy tắc — migration
- Expand–contract, mỗi bước tương thích ngược: thêm cột NULL → backfill theo lô có nghỉ → code ghi cả hai → `SET NOT NULL` → sau khi không còn đọc cột cũ mới xóa, ở bản phát hành sau.
- Mọi migration có đường lùi (rollback) hoặc lý do vì sao không thể lùi; migration idempotent, chạy lại không hỏng.
- Không khóa bảng lâu: tạo index dạng `CONCURRENTLY`, backfill theo lô, đặt `lock_timeout` và `statement_timeout`; ước lượng thời gian trên bản sao cỡ production trước.
- Migration chạy tách khỏi deploy code; code phiên bản mới phải chạy được với schema cũ trong suốt thời gian chuyển.
- Không có thao tác thủ công trên production; mọi thay đổi schema nằm trong repo và qua pipeline.

## Quy tắc — hiệu năng
- Mỗi index có lý do đo được: truy vấn nào, tần suất, EXPLAIN trước/sau. Index không dùng bị xóa — chúng làm chậm ghi và tốn dung lượng.
- Ưu tiên index phủ (covering) và index trên cột lọc + sắp xếp thật sự dùng; cẩn thận thứ tự cột trong index tổ hợp.
- Không N+1 (xử lý ở tầng ứng dụng, xem `backend`); mọi danh sách có phân trang; tránh `OFFSET` lớn, dùng phân trang theo con trỏ.
- Bật log truy vấn chậm; truy vấn vượt ngưỡng NFR là finding, xử lý theo `performance-testing`.
- Kết nối qua pool có giới hạn; giao dịch ngắn; không giữ giao dịch mở khi gọi mạng.

## Quy tắc — an toàn và phục hồi
- PII: phân loại trong schema, mã hóa hoặc che theo `privacy-compliance`, có job xóa theo retention, và không nằm trong log.
- Quyền theo vai trò và ít nhất có thể; ứng dụng không dùng tài khoản superuser; tài khoản chỉ đọc cho báo cáo.
- Backup có RPO/RTO khớp NFR, mã hóa, để ở nơi tách biệt; phục hồi phải được diễn tập định kỳ và ghi lại thời gian thật — backup chưa từng restore coi như chưa có.
- Dữ liệu dùng cho môi trường thử nghiệm phải được che hoặc sinh giả; không sao chép nguyên dữ liệu production.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Ràng buộc toàn vẹn đặt ở DB, kiểu dữ liệu đúng nghĩa
- [ ] Migration theo expand–contract, tương thích ngược, idempotent, có rollback
- [ ] Đã thử migration trên dữ liệu cỡ production, có số đo thời gian và khóa
- [ ] Mỗi index mới kèm truy vấn và EXPLAIN chứng minh; index thừa đã xóa
- [ ] Không truy vấn nào vượt ngưỡng NFR trong log truy vấn chậm
- [ ] PII được phân loại, bảo vệ, có retention và job xóa
- [ ] RPO/RTO đạt NFR và đã có diễn tập phục hồi gần đây
- [ ] Không thao tác schema thủ công trên production

## Ví dụ tốt
`ALTER TABLE orders ADD COLUMN coupon_code text NULL;` → backfill 5k dòng/lô, nghỉ 200ms, mất 4 phút trên bản sao → code ghi cả hai đường → `SET NOT NULL` ở bản sau → xóa cột cũ ở bản kế tiếp. Index `orders (tenant_id, created_at DESC)` giảm truy vấn danh sách từ 820ms xuống 12ms (EXPLAIN đính kèm). Diễn tập restore tháng trước: RTO thực tế 22 phút, NFR 30 phút.

## Ví dụ xấu
`DROP COLUMN` ngay trong cùng một migration với deploy code; tạo index trên bảng 40 triệu dòng lúc cao điểm không dùng `CONCURRENTLY`; số CCCD lưu dạng plaintext trong `users`; backup có nhưng chưa ai thử phục hồi bao giờ.
