# Chính sách bảo mật — X-Agents

## Báo lỗi bảo mật

**Đừng mở issue công khai.** Dùng GitHub Security Advisory của repo:
*Security → Report a vulnerability*. Nếu không truy cập được, gửi email tới người bảo trì repo
(xem `git log`) với tiêu đề bắt đầu bằng `[security]`.

Hãy kèm: phiên bản/commit, thư mục liên quan (`companies/software-company/`, `platform/gateway/`), các bước tái
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
`*.example.yaml` được commit. Khóa cũng có thể đặt bằng biến môi trường `COMPANY_LLM_*`, và biến
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
- **Reviewer có chữ ký** (ADR gốc 0024, mặc định TẮT — `COMPANY_GATE_REVIEWER=1` mới bật): actor `reviewer:<id>` chỉ
  được `approve` gate `escalation` ticket/dự án, mỗi subject một lần, và chỉ được tin khi chữ ký Ed25519 khớp registry
  public key ngoài repo (`COMPANY_GATE_REVIEWER_REGISTRY`). Spec, release, nghiệm thu, nợ kiến trúc, reject/close vẫn
  là người. **Trần đã biết:** khoá bí mật là file của cùng user OS — mã khách chạy qua `SubprocessSandbox` đọc được
  (F1, ADR gốc 0023); chỉ bật reviewer cùng sandbox container.
- **Phạm vi `rong`** (ADR gốc 0025, `COMPANY_GATE_REVIEWER_SCOPE=rong`, chủ dự án chọn 2026-09-26): reviewer (phiên
  chính, `reviewer:phien-chinh`) `approve`/`reject` mọi gate trừ `spec`, không trần, kể cả chấp nhận finding của release
  và nghiệm thu thay khách. Four-eyes thực chất không còn; dấu vết vẫn trung thực (không `human:*`). Lộ khoá ở phạm vi
  này = mã khách tự duyệt được release/nghiệm thu.
- **Chống prompt injection** (`guard.py`, ADR-0012): dữ liệu nguồn nội bộ nghi injection thì từ chối chạy; dữ liệu
  nguồn ngoài (khách, web, diff repo khách) bị lọc đoạn khớp mẫu và ghi audit, vì không thể từ chối đọc.
- **Quét tài sản prompt** (`company.assetscan`, ADR-0022): `guard.py` canh dữ liệu chạy qua, còn cổng này canh
  chính các file `agents/ skills/ templates/ gates/ topics/` — thứ ghép thành system prompt và không qua lớp lọc
  nào. Bốn lỗi làm CI đỏ: mẫu injection, ký tự vô hình/đảo chiều (mắt người không thấy trong diff), lệnh nguy hiểm
  (`curl … | sh`, `rm -rf /`, POST biến môi trường), khóa lộ. Miễn trừ phải có lý do trong `assetscan-waivers.txt`.
- **Ranh giới ghi**: agent sửa code trong git worktree tách riêng, không ghi thẳng vào cây làm việc.
- **Lệnh con của repo khách** (lint/test theo stack, `git commit/merge`, CLI model): env đã lọc mọi biến trông như bí
  mật (`workspace.SECRET_ENV`: khoá API, token, mật khẩu, `*_URL`/`*_DSN`, `AWS_*`/`AZURE_*`/`GOOGLE_*`, `GITHUB_*`,
  `SSH_AUTH_SOCK`, `COMPANY_LLM_*`…), và git chạy với `core.hooksPath` trỏ vào chỗ không tồn tại nên hook của khách
  (`.git/hooks`, `.husky/`) không bao giờ chạy dưới quyền orchestrator.
- **Sandbox tiến trình** (ADR-0035): ba điểm chạy mã của khách — tool `run` của model (`tools.py`), lint/test của
  `run_checks` (`workspace.py`), lệnh khởi động smoke theo `runtime` của spec (`smoke.py`) — đi qua một giao diện
  `Sandbox` duy nhất. Backend `container` (docker/podman `run --rm`) chạy chúng với **mạng tắt**, hạn mức
  cpu/ram/pid, cwd mount vào `/w`, env qua `/dev/stdin` trên POSIX (Windows truyền env trong argv và ghi rõ `:env-argv`); backend
  `subprocess` giữ nguyên hành vi cũ. Chọn bằng `COMPANY_SANDBOX` (env) hoặc `sandbox:` trong `llm.yaml`:
  `auto` (mặc định — yêu cầu container runtime), `container`, `subprocess`. **Fail-closed**: `auto` hoặc
  `container` mà thiếu binary đều ném `SandboxError` ngay lúc khởi động `run`/`redeploy`/`recheck`; chỉ khai
  `subprocess` tường minh mới chạy ngoài container. Chế độ được ghi audit `sandbox.mode` khi bắt đầu lệnh. Lớp bảo vệ đã dùng được ghi vào chính bằng chứng: `pull-requests.local_checks.sandbox` và
  `release-events.smoke.sandbox` — người ký gate đọc được lint/test vừa chạy trong container hay bằng quyền người
  vận hành, thay vì phải suy từ tài liệu này.
  **Giới hạn còn lại**: (1) `git` KHÔNG đi qua sandbox — argv hard-code, hook đã bị vô hiệu, và push cần credential
  của người vận hành; (2) CLI model (`claude`/`codex`) cũng không — nó là đường ra API, nhốt vào mạng tắt là cắt
  chính nó; tool nó xin chạy vẫn quay về `tools.py` qua cầu MCP nên vẫn trong sandbox; (3) `subprocess` khi người vận hành khai tường minh vẫn là mã của khách chạy bằng quyền người vận hành và thấy `HOME`
  (`~/.ssh`, `~/.claude`) — repo khách không tin cậy thì đặt `COMPANY_SANDBOX=container`, hoặc chạy cả orchestrator
  trong container/user riêng. Nó cũng ghi thẳng được vào `company.sqlite`: ACL của bus chỉ chạy lúc `publish`,
  nên một dòng `gate.decide` mang actor `human:*` (hay `orchestrator` trên gate `UAT-*`) do mã khách tự chèn vào
  file vẫn được tin như quyết định thật. Ở chế độ này, human gate **không** phải ranh giới chống mã khách. Đã tái
  hiện có đối chứng; phương án (a) đã được chọn trong ADR gốc 0023; container chỉ mount cwd của khách, không mount bus
  (`docs/adr/0023-ma-khach-khong-chay-cung-quyen-ghi-bus.md`).
- **Guardrail chi phí**: ước lượng token trước khi dispatch, ngân sách theo việc, supervisor cắt khi vượt hạn mức;
  audit-log ghi token thật và quy ra USD.
- **Trần quyền theo agent**: mỗi agent chỉ được đọc/ghi những topic đã khai trong registry; ghi sai topic là lỗi
  chạy, không phải cảnh báo.

Danh tính `--by` khi duyệt gate hay publish (`gate_cli`, lệnh publish) chỉ là **chuỗi gõ tay trên CLI, không được
xác thực**: ai có shell trên máy đó đều ghi được tên người khác. Quy tắc "bốn mắt" (người duyệt khác người tạo) vì vậy
là kiểm soát *quy trình* trên một máy tin cậy duy nhất, không phải ranh giới xác thực. Nếu gate được đưa lên giao diện
web hoặc dùng chung nhiều người, nó cần xác thực thật (đăng nhập, phiên, audit theo danh tính đã xác minh) trước khi
tin vào `--by`.

Gateway lắng nghe `127.0.0.1:1123` và **không có xác thực người dùng**. Đừng bind nó ra địa chỉ công khai; muốn
dùng từ máy khác thì đi qua SSH tunnel.

Vì không có xác thực, hai header là toàn bộ hàng rào giữa pool tài khoản Google và một trang web bất kỳ người dùng
đang mở (`guard_middleware` trong `platform/gateway/src/gateway/server.py`, đối xứng với `platform/console/src/console/server.py::_guard`):

- `Host` không phải loopback → **404** (không xác nhận có server ở đây). Chặn DNS rebinding: trình duyệt gửi tên
  miền kẻ tấn công điều khiển dù bản ghi A của nó trỏ về 127.0.0.1.
- `Origin` có mặt mà không phải loopback → **403**. Vắng `Origin` (curl, SDK OpenAI) thì cho qua; origin loopback ở
  cổng bất kỳ cũng cho qua, vì một trang dev cục bộ gọi sang gateway là việc hợp lệ.

Chỉ dựa vào CORS là **không đủ**: CORS chặn trang lạ ĐỌC phản hồi, nhưng request vẫn chạy — `POST
/v1/chat/completions` đốt quota thật và `POST /auth/login` mở luồng thêm tài khoản. Hai luật trên chạy ở
middleware, trước handler. Khi bind ra ngoài loopback thì chúng tự tắt (`Host`/`Origin` hợp lệ lúc đó là tên miền
thật) — đó là chế độ đã cảnh báo ở trên và đòi firewall/reverse proxy lo xác thực.

## Chạy code do agent sinh ra

Agent trong `software-company` sinh và chạy code trong repo bạn trỏ tới bằng `--repo`. Hãy coi đó là chạy code chưa
được review: dùng repo riêng, không phải môi trường có quyền production, và đọc diff trước khi merge.
