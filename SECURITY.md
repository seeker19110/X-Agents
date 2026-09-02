# Chính sách bảo mật

## Báo lỗi bảo mật

Không mở issue công khai cho lỗ hổng. Dùng [GitHub Security Advisories](https://github.com/seeker19110/X-Agents/security/advisories/new)
để báo riêng. Mô tả cần có: phiên bản hoặc commit, các bước tái hiện, ảnh hưởng thực tế, và bằng chứng nếu có.

Thời gian phản hồi mục tiêu: xác nhận đã nhận trong 3 ngày làm việc, đánh giá sơ bộ trong 10 ngày làm việc.

## Phạm vi

Repo này là một hệ đa agent chạy mô hình ngôn ngữ trên mã nguồn của bên thứ ba. Những thứ sau nằm trong phạm vi và
được coi là lỗ hổng:

- Thoát khỏi ranh giới tool: đọc hoặc ghi ngoài worktree của ticket, chạm `.git/`, đọc file bí mật (`tools.py`).
- Chạy lệnh ngoài allowlist, hoặc chèn tham số vào argv của lệnh trong allowlist.
- Rò rỉ khóa API qua đầu ra tool, log, `audit-log` hay prompt.
- Prompt injection từ nội dung repo khách khiến agent hành động ngoài nhiệm vụ.
- Vượt qua human gate: chuyển ticket sang production mà không có quyết định `approve`.

## Giới hạn đã biết, không phải lỗ hổng

Những điều dưới đây là hạn chế đã ghi nhận, không nhận báo cáo trùng:

- Tool `run` thực thi test do model viết trong worktree. Chưa có sandbox tiến trình (container hay seccomp);
  hiện chỉ có allowlist lệnh, khóa đường dẫn và lọc biến môi trường. Đừng chạy trên repo không tin cậy.
- Phát hiện prompt injection dựa trên danh sách mẫu cố định, không đầy đủ theo thiết kế.
- Bus SQLite dành cho một máy; chưa có phân quyền giữa các tiến trình cùng đọc file đó.

## Bí mật

Không commit khóa, `llm.yaml` hay dữ liệu thật của khách. CI quét bí mật trong toàn bộ lịch sử git; nếu khóa đã lọt
thì xoay vòng khóa trước, rồi mới dọn lịch sử.
