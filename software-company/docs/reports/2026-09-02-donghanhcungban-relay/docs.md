# Runbook — DHCB bản demo v0.1.1, production (REL-001)

Dành cho: người trực vận hành bản demo hoặc người đang trình diễn cho khách, đang gặp
sự cố và cần xử lý ngay, không có thời gian đọc lý thuyết.

Kế thừa: `docs/runbooks/REL-001-staging.md`. Phát hành: `docs/runbooks/REL-001-production.md`
tại tag `v0.1.1` (`company/integration@3856f6d`).

## Bối cảnh — đọc trước khi làm bất cứ gì

"Production" ở đây là máy cục bộ, không phải hạ tầng đám mây:

- Không có domain công khai. `donghanhcungban.com` chưa được đăng ký/triển khai — không
  URL công khai nào là thật.
- Máy chủ bind cứng vào `127.0.0.1:8000`, chỉ truy cập được từ chính máy đang chạy.
- Không có canary, không có blue-green, không traffic shifting, không hệ giám sát SLO
  (đây là sai lệch có chủ đích so với quy trình chuẩn, do bản chất bàn giao cục bộ).
- Dữ liệu đăng ký lưu trong `dhcb.sqlite3` cục bộ (quyền tệp 0600), là dữ liệu mô phỏng,
  không phải dữ liệu thật.

## Điều kiện tiên quyết

- Python đã cài trên máy (không cần gói ngoài — bản demo chỉ dùng thư viện chuẩn).
- Đã giải nén gói bàn giao `dhcb-0.1.1.tar.gz` (đã kiểm `sha256sum -c
  dhcb-0.1.1.tar.gz.sha256`), hoặc đã checkout đúng tag `v0.1.1`.
- Không có tiến trình nào khác đang chiếm cổng 8000 trên máy.

## Chạy demo cục bộ

1. Mở dòng lệnh tại thư mục gói bàn giao (hoặc thư mục checkout tag `v0.1.1`).
2. Chạy: `python -m dhcb`
3. Kết quả mong đợi: dòng lệnh báo máy chủ đang lắng nghe `127.0.0.1:8000`, không có
   dấu vết lỗi (traceback) nào trong log khởi động.
4. Mở trình duyệt tới `http://127.0.0.1:8000/` — bạn sẽ thấy trang chủ DHCB.
5. Kiểm nhanh các trang: `/gioi-thieu`, `/dang-ky` (điền form và gửi thử — dữ liệu chỉ
   là mô phỏng), đường dẫn bất kỳ không có trong danh sách (ví dụ `/khong-ton-tai`) phải
   trả về trang 404 có băng-rôn ghi rõ đây là bản demo.
6. Để dừng: nhấn `Ctrl-C` trong cửa sổ dòng lệnh đang chạy.

Cách hoàn tác bước này: dừng tiến trình (`Ctrl-C`); không có thay đổi nào khác trên máy
ngoài tệp `dhcb.sqlite3` — xem mục "Xoá dữ liệu demo" bên dưới nếu muốn dọn sạch.

## Xoá dữ liệu demo (đặt lại từ đầu)

Khi bạn muốn bắt đầu lại từ trạng thái sạch (ví dụ trước một buổi trình diễn mới):

1. Dừng tiến trình đang chạy (`Ctrl-C`, hoặc dừng theo PID ghi trong `.release/REL-001.pid`
   nếu chạy nền).
2. Xoá tệp `dhcb-demo.db` (hoặc `dhcb.sqlite3` tuỳ theo tên tệp mà gói bàn giao của bạn
   tạo ra — kiểm tra README đi kèm gói để biết tên chính xác).
3. Chạy lại `python -m dhcb` — ứng dụng tự tạo tệp cơ sở dữ liệu mới, rỗng.

Kết quả mong đợi: không còn bản ghi đăng ký cũ nào; trang `/dang-ky` hoạt động bình
thường như lần chạy đầu tiên. Vì đây là dữ liệu mô phỏng, xoá tệp này không ảnh hưởng gì
tới dữ liệu thật của tổ chức Đồng Hành Cùng Bạn.

## Triệu chứng và cách xử lý

### Máy chủ không khởi động được / báo lỗi cổng đã dùng

- Xác nhận: chạy `python -m dhcb` báo lỗi liên quan tới cổng 8000 (address already in
  use) thay vì thông báo "đang lắng nghe".
- Xử lý: tìm và dừng tiến trình cũ đang giữ cổng 8000 (có thể là một lần chạy demo trước
  chưa tắt hẳn), sau đó chạy lại `python -m dhcb`.
- Không phải lỗi mã nguồn — không cần rollback.

### Trình duyệt báo "không kết nối được" tới 127.0.0.1:8000

- Xác nhận: dòng lệnh chạy `python -m dhcb` đã báo đang lắng nghe, nhưng trình duyệt vẫn
  không vào được.
- Xử lý: kiểm tra bạn đang mở trình duyệt trên đúng máy đang chạy tiến trình (bản demo
  không thể truy cập từ máy khác — đây là thiết kế có chủ đích, không phải lỗi). Kiểm
  tra không có phần mềm chặn cổng cục bộ (tường lửa cá nhân) chặn 127.0.0.1.

### Dòng lệnh in ra `BrokenPipeError`

- Xác nhận: một đoạn traceback ngắn nhắc tới `BrokenPipeError` xuất hiện ngay sau khi
  bạn đóng tab trình duyệt hoặc mất mạng giữa lúc trang đang tải.
- Xử lý: đây là hiện tượng đã biết, vô hại (client ngắt kết nối giữa chừng). Không cần
  hành động, không phải sự cố. Đừng nhầm với lỗi nghiệp vụ khi soát log.

### Gửi form `/dang-ky` không ra trang xác nhận

- Xác nhận: bấm gửi form nhưng không thấy trang có dòng "Đăng ký này chỉ để trình diễn,
  dữ liệu không được lưu lâu dài".
- Xử lý: kiểm tra thông báo lỗi hiện lại trên form — có thể bạn chưa tích ô đồng ý, thiếu
  trường bắt buộc, hoặc phần lý do dài quá 500 ký tự (giới hạn theo thiết kế). Sửa theo
  thông báo và gửi lại; không có bản ghi nào bị tạo khi form bị từ chối.
- Nếu form gửi hợp lệ nhưng vẫn không ra trang xác nhận: đây là sự cố thật, xem mục leo
  thang bên dưới.

### `PUT /dang-ky` trả về lỗi 501 thay vì trang 404 demo

- Đây là vấn đề đã biết (không chặn phát hành, xếp vào bản sau). Không cần xử lý khi
  trình diễn cho khách bằng thao tác bình thường trên trình duyệt (form chỉ gửi GET/POST).

## Rollback (quay về bản trước)

Mục tiêu: dưới 5 phút. Không có traffic shifting vì chỉ có một tiến trình cục bộ.

1. Dừng tiến trình đang chạy (`Ctrl-C`, hoặc dừng theo PID trong `.release/REL-001.pid`).
2. Quay lại mốc trước: `git checkout <tag_trước>`. Nếu `v0.1.1` là tag đầu tiên của kho
   (chưa xác minh), quay lại commit cha: `git checkout 3856f6d^`.
3. Nếu lược đồ cơ sở dữ liệu đã đổi giữa hai bản: đổi tên `dhcb.sqlite3` thành
   `dhcb.sqlite3.bak-REL-001` để bản cũ tự tạo lại tệp sạch. Không sửa tay dữ liệu.
4. Chạy `python -m pytest -q`, xác nhận toàn bộ test pass.
5. Chạy `python -m dhcb`, smoke lại 4 route (`/`, `/gioi-thieu`, `/dang-ky`, một đường
   dẫn ngoài danh sách trả 404) như bước kiểm khi phát hành.

Đã diễn tập trên bản sao trước khi bàn giao; nếu diễn tập lại không hoàn tất dưới 5 phút
hoặc smoke không pass ở mốc lùi, không coi là "lùi được" — báo lại theo mục leo thang.

## Khi nào leo thang

Bản demo không có hệ giám sát SLO, không có nhóm trực tự động — nếu smoke sau khi khởi
động hoặc sau rollback không pass, hoặc bạn thấy lỗi nghiệp vụ (không phải
`BrokenPipeError` đã biết) trong log ngay sau khởi động, dừng lại và báo cho
release-engineer kèm nội dung log, đừng tự sửa mã nguồn tại chỗ trong buổi trình diễn.

## Giới hạn của bản demo (nhắc lại để tránh hiểu nhầm khi vận hành)

- Không phải sản phẩm production thật của tổ chức Đồng Hành Cùng Bạn — chỉ là gói trình
  diễn chạy trên máy cá nhân.
- Không có domain, không có máy chủ dùng chung, không ai khác truy cập được vào phiên
  bạn đang chạy.
- Không xác thực người dùng, không endpoint JSON, không gọi dịch vụ bên thứ ba.
- Dữ liệu đăng ký là mô phỏng; xoá được bất cứ lúc nào (xem mục "Xoá dữ liệu demo") mà
  không ảnh hưởng gì tới dữ liệu thật.
- Chưa qua kiểm thử biến đổi (mutation testing) — ghi nhận là nợ kỹ thuật, không chặn
  bản demo này.
