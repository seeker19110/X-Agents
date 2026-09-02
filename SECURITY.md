# Chính sách bảo mật — X-Agents

## Báo lỗi bảo mật

**Đừng mở issue công khai.** Dùng GitHub Security Advisory của repo:
*Security → Report a vulnerability*. Nếu không truy cập được, gửi email tới người bảo trì repo
(xem `git log`) với tiêu đề bắt đầu bằng `[security]`.

Hãy kèm: phiên bản/commit, thư mục liên quan (`software-company/`, `Studio-creators/`, `gateway/`), các bước tái
hiện, và tác động bạn đánh giá. Có bản vá đề xuất thì càng tốt — nhưng đừng mở PR công khai cho lỗ hổng chưa vá.

Đây là dự án nguồn mở không có SLA và không có chương trình thưởng lỗi. Cam kết thực tế: phản hồi trong vòng 7
ngày, và công bố cùng bản vá khi sửa xong.

## Phạm vi

**Trong phạm vi:** rò rỉ khóa/token ra log, artifact hay repo; thoát khỏi ranh giới worktree khi agent sửa code
repo khách; bỏ qua human gate; prompt injection dẫn tới gọi tool ngoài quyền của agent; gateway phục vụ token của
tài khoản này cho phiên của tài khoản khác; SSRF từ tool web.

**Ngoài phạm vi:** chất lượng đầu ra của model; chi phí phát sinh do cấu hình sai; lỗ hổng của chính provider hoặc
của `ffmpeg`/thư viện bên thứ ba (báo cho thượng nguồn, chúng tôi sẽ nâng phiên bản); việc bạn tự chạy repo với
khóa của mình trên máy không tin cậy.

## Mô hình bí mật

Không có bí mật nào nằm trong repo. Cấu hình thật (`llm.yaml`, `media.yaml`) bị `.gitignore`; chỉ bản
`*.example.yaml` được commit. Khóa cũng có thể đặt bằng biến môi trường `COMPANY_LLM_*` / `STUDIO_LLM_*`, và biến
môi trường thắng file.

Token Google của gateway nằm ở `$XAGENTS_HOME/auth/antigravity_tokens.json` (mặc định `~/.x-agents/`), quyền 600,
ghi nguyên tử, ngoài cây repo. `GET /auth/status` trả trạng thái và hạn token nhưng không trả token.

CI có job `audit` chạy `gitleaks` trên **cả lịch sử git**, không chỉ commit cuối. Vì vậy một khóa lỡ commit rồi xoá
ở commit sau vẫn làm CI đỏ — và vẫn còn trong lịch sử với bất kỳ ai đã clone. Xử lý đúng là: **thu hồi khóa ở phía
provider trước**, rồi mới dọn lịch sử. Đổi khóa quan trọng hơn viết lại lịch sử.

## Lớp phòng thủ đang có

Đây là mô tả hiện trạng, không phải bảo đảm — hệ thống này để chạy trên máy của chính bạn (self-hosted), không phải
để mở ra Internet.

- **Human gate**: các bước không thể hoàn tác (release, đăng video) dừng lại chờ người duyệt bằng `gate_cli`.
- **Chống prompt injection** (`guard.py`, ADR-0012): dữ liệu nguồn nội bộ nghi injection thì từ chối chạy; dữ liệu
  nguồn ngoài (khách, web, diff repo khách) bị lọc đoạn khớp mẫu và ghi audit, vì không thể từ chối đọc.
- **Ranh giới ghi**: agent sửa code trong git worktree tách riêng, không ghi thẳng vào cây làm việc.
- **Guardrail chi phí**: ước lượng token trước khi dispatch, ngân sách theo việc, supervisor cắt khi vượt hạn mức;
  audit-log ghi token thật và quy ra USD.
- **Trần quyền theo agent**: mỗi agent chỉ được đọc/ghi những topic đã khai trong registry; ghi sai topic là lỗi
  chạy, không phải cảnh báo.

Gateway lắng nghe `127.0.0.1:8100` và **không có xác thực người dùng**. Đừng bind nó ra địa chỉ công khai; muốn
dùng từ máy khác thì đi qua SSH tunnel.

## Chạy code do agent sinh ra

Agent trong `software-company` sinh và chạy code trong repo bạn trỏ tới bằng `--repo`. Hãy coi đó là chạy code chưa
được review: dùng repo riêng, không phải môi trường có quyền production, và đọc diff trước khi merge.
