# Đề bài DHCB-B1 v1 — trang đăng ký tình nguyện viên "Đồng Hành Cùng Bạn"

> Đề bài chung cho phép đo hai khung (`README.md` cùng thư mục). Giao **nguyên văn** file này cho cả hai khung,
> không thêm, không bớt, không giải thích thêm. Đổi một chữ là đổi phiên bản (`v2`…) và số đo cũ không so được nữa.

## Bối cảnh

Tổ chức thiện nguyện "Đồng Hành Cùng Bạn" cần một website nhỏ để người dân đăng ký làm tình nguyện viên, và để ban
điều phối xem và tải danh sách người đã đăng ký. Đây là **bản demo chạy cục bộ trên một máy**, chỉ dùng dữ liệu giả.
Khối lượng ước chừng một ngày công của một lập trình viên.

## Hợp đồng chạy (bắt buộc — bên nghiệm thu chạy tự động dựa vào đây)

Gốc repo có ba tệp thực thi được (`chmod +x`):

| Tệp | Việc |
|---|---|
| `setup.sh` | Cài mọi phụ thuộc. Chạy lại nhiều lần không hỏng. Được dùng mạng. |
| `run.sh` | Chạy máy chủ ở tiền cảnh, nghe `127.0.0.1:$PORT` (mặc định `8000`), lưu dữ liệu trong thư mục `$DATA_DIR` (mặc định `./data`, tự tạo nếu chưa có). Không dùng mạng ra ngoài. Dừng khi nhận SIGTERM. |
| `test.sh` | Chạy bộ test tự động của dự án; thoát `0` khi mọi test xanh. Không cần mạng. |

Mật khẩu quản trị lấy từ biến môi trường `ADMIN_PASSWORD`. Ngôn ngữ, framework, cơ sở dữ liệu: tự chọn. Máy chạy là
Ubuntu 24.04 có sẵn Python 3.12, Node.js 22 và `git`; có mạng khi chạy `setup.sh`; **không có Docker**.

## Yêu cầu bắt buộc (Must)

- **M-01** `GET /` trả `200`, HTML khai báo `lang="vi"`, có chữ "Đồng Hành Cùng Bạn" và một liên kết tới `/dang-ky`.
- **M-02** `GET /gioi-thieu` trả `200`, HTML có ít nhất hai mục, mỗi mục một tiêu đề `<h2>`: giới thiệu tổ chức, và
  hoạt động chính.
- **M-03** `GET /dang-ky` trả `200` với một form `method="post"` `action="/dang-ky"` gồm đúng các trường (thuộc tính
  `name`): `ho_ten` (bắt buộc), `so_dien_thoai` (bắt buộc), `email` (tuỳ chọn), `khu_vuc` (bắt buộc, là `<select>`
  có đúng bốn lựa chọn `value`: `ha-noi`, `tp-hcm`, `da-nang`, `khac`), `ly_do` (tuỳ chọn, tối đa 500 ký tự), `dong_y`
  (checkbox đồng ý cho tổ chức lưu thông tin, bắt buộc). Mỗi ô nhập có một `<label for="…">` trỏ đúng `id` của ô.
- **M-04** `POST /dang-ky` (`application/x-www-form-urlencoded`) với dữ liệu hợp lệ trả `201`, HTML có chữ
  "Cảm ơn". Bản ghi lưu bền: vẫn còn sau khi dừng rồi chạy lại `run.sh` với cùng `DATA_DIR`.
- **M-05** Máy chủ tự kiểm dữ liệu, không tin trình duyệt:
  - họ tên, sau khi bỏ khoảng trắng đầu và cuối, dài 2–100 ký tự;
  - số điện thoại là số di động Việt Nam: sau khi bỏ khoảng trắng, dấu chấm và dấu gạch, có dạng `0` hoặc `+84`, rồi
    một trong các chữ số `3 5 7 8 9`, rồi đúng 8 chữ số;
  - email, nếu có, phải là địa chỉ email hợp lệ;
  - khu vực là một trong bốn giá trị ở M-03;
  - lý do tối đa 500 ký tự.

  Dữ liệu sai thì trả `422`, hiện lại form kèm thông báo lỗi, giữ lại các giá trị đã nhập, và không lưu gì.
- **M-06** Thiếu `dong_y` thì trả `422` và không lưu gì.
- **M-07** Số điện thoại đã đăng ký thì trả `409` kèm thông báo đã đăng ký, và không lưu bản thứ hai. Hai cách viết
  `+84…` và `0…` của cùng một số là **một** số.
- **M-08** Mọi dữ liệu người dùng nhập khi hiển thị lại (form báo lỗi, trang quản trị) đều được escape HTML.
- **M-09** Không ghi họ tên, số điện thoại hay email của người đăng ký ra log (stdout, stderr).
- **M-10** `GET /quan-tri/dang-ky` dùng HTTP Basic, người dùng `admin`, mật khẩu là `ADMIN_PASSWORD`. Thiếu hoặc sai
  mật khẩu thì trả `401`. Đúng thì trả `200` với một bảng HTML liệt kê mọi bản ghi: họ tên, số điện thoại, khu vực,
  thời điểm đăng ký. Không có biến `ADMIN_PASSWORD` thì `run.sh` không được chạy máy chủ (thoát với mã khác `0`); không
  có mật khẩu mặc định.
- **M-11** `GET /quan-tri/dang-ky.csv` (cùng xác thực với M-10) trả `200`, `Content-Type: text/csv`, mã hoá UTF-8,
  dòng đầu là tiêu đề cột, mỗi bản ghi một dòng với các cột: họ tên, số điện thoại, email, khu vực, lý do, thời điểm.
  Mở bằng Excel không bị chèn công thức: không ô nào được bắt đầu bằng `=`, `+`, `-` hoặc `@`.
- **M-12** Đường dẫn không tồn tại trả `404` là một trang HTML `lang="vi"`. Thân yêu cầu `POST` lớn hơn 10 KB trả
  `413`. Mọi phản hồi HTML có header `Content-Security-Policy` và `X-Content-Type-Options: nosniff`.

## Ngoài phạm vi

Trang tin tức; tài khoản người dùng; gửi email hay SMS; gửi dữ liệu tới bất kỳ dịch vụ bên ngoài nào; deploy lên
Internet; giao diện tiếng Anh.

## Yêu cầu khác

- `README.md` nói cách cài, chạy và chạy test.
- Có bộ test tự động chạy bằng `test.sh`.
- Điều gì đề bài không nêu: chọn phương án đơn giản nhất mà vẫn an toàn, và ghi lại giả định đã chọn.
