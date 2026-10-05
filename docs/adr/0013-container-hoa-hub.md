# ADR-0013: Container hoá hub (console + orchestrator) để chạy trên WSL

Trạng thái: Chấp nhận · Ngày: 2026-09-13 · Liên quan ADR-0039 (`companies/software-company`, deploy khách bằng
compose), ADR-0011 (hợp nhất một công ty), `docs/sessions/2026-09-09-van-hanh-qlkh.md`

## Bối cảnh

Hub (`platform/console` + `companies/software-company` orchestrator) hiện chỉ chạy đúng khi người vận hành nhớ
`cd` đúng thư mục (gốc hub có `company.sqlite` rỗng, dễ nhầm — cảnh báo sẵn trong
`companies/software-company/CLAUDE.md`), đặt đúng cờ (`--repo`, `--allow-engine`...), và PATH có `uv`/`git`/`gh`.
Phiên 2026-09-09 (`docs/sessions/2026-09-09-van-hanh-qlkh.md`) đo được 6 lỗi PATH thật khi chạy trực tiếp trong
WSL — nhưng đó là bẫy của **sản phẩm khách** (QLKH: nvm, uv, npm), không phải của hub. Việc này là ADR riêng cho
việc đóng gói **chính hub**, không đụng ADR-0039 (compose là của khách, hub chỉ *gọi* nó).

Đo trực tiếp trước khi quyết định (không đoán):

- `platform/console`: `uv run python -m console` từ `platform/console/`; bind `127.0.0.1:8200` mặc định
  (`server.py:39-40`), đọc `companies/software-company/company.sqlite` + `companies/keeper/keeper.sqlite`
  read-only, ghi `.console-token` (mode 0600) + `.engine/<company>.log`. Frontend static, stdlib `http.server`,
  không build step. Cờ: `--allow-decide --allow-submit --allow-config --allow-engine --deliver-remote <remote>`,
  `--i-know` chỉ cần khi bind ngoài loopback.
- `companies/software-company` orchestrator: `uv run python -m company.orchestrator --repo <repo khách> run
  --watch <giây>`. Tạo git worktree cho ticket khách (`workspace.py`), tự gọi `docker compose` cho deploy khách
  theo ADR-0039 (`deploy.py`, cố ý **ngoài** `Sandbox` vì cần `/var/run/docker.sock`), shell ra `git`/`gh`
  (`NO_HOOKS`, env đã lọc qua `clean_env`).
- Console và orchestrator là **hai tiến trình riêng**, chỉ nói chuyện qua file `company.sqlite` chung — console
  có thể tự spawn orchestrator làm con qua `--allow-engine` (`subprocess`, không phải RPC).
- Root: uv workspace 5 package, `requires-python>=3.11` (CI dùng 3.13 cho static check), `uv sync --locked` dựng
  một `.venv` chung cho cả workspace. Không lib hệ thống lạ ngoài `git`/`gh` phải có trên PATH.

Ba ràng buộc không được phá (kế thừa từ ADR-0039 và `AGENTS.md`):

- Không đổi cách console/orchestrator nói chuyện (vẫn qua file, không thêm RPC).
- `docker compose` cho khách vẫn **ngoài** `Sandbox` (ADR-0039 quyết định 7) — container hoá hub không tự ý
  nhốt lệnh này lại, chỉ đổi *nơi* lệnh đó được gọi từ.
- Không bake trạng thái/bí mật vào image (`AGENTS.md` luật cấm 3: không commit `*.sqlite*`, secret).

## Quyết định

1. **Một image, một container** cho hub — không tách console/orchestrator thành hai service compose. Chúng đã
   giao tiếp qua file `company.sqlite`, và console tự spawn orchestrator qua `--allow-engine` đúng như cách vận
   hành thủ công hiện tại; tách hai container sẽ phải thêm volume chia sẻ phức tạp hơn mà không đổi được gì về
   hành vi.
2. **Base `python:3.13-slim`** (khớp version CI dùng cho static check) + cài `git`, `gh` CLI, `docker-cli`
   (**chỉ client, không chạy `dockerd` trong container**) — orchestrator gọi `docker compose` cho khách qua
   **docker socket passthrough** từ host WSL (mount `/var/run/docker.sock`), đúng tinh thần ADR-0039 quyết định
   7 ("nhốt daemon-client vào container là vô nghĩa, nó gọi ra quyền cao nhất").
3. **`uv sync --locked` chạy ở build time**, bake `.venv` vào image — khớp cách CI đã làm
   (`.github/workflows/ci.yml`), tránh image "sống" phải tải mạng lúc `docker run`.
4. **State không nằm trong image, qua volume mount**: `companies/software-company/company.sqlite`,
   `<db>.artifacts/`, `.console-token`, `.engine/`. Xoá/rebuild container không mất dữ liệu công ty.
5. **Repo khách mount từ ngoài** (bind mount đường dẫn WSL, ví dụ `/mnt/d/khach/qlkh`), không copy vào image —
   orchestrator phải ghi worktree/commit thật lên đó, và nhiều repo khách phải mount được đồng thời khi cần.
6. **Cổng `8200`** expose và publish qua compose `127.0.0.1:8200:8200`. Trong container, console bind
   `0.0.0.0` với `--i-know`; loopback được giữ ở phía host. Đo O3 ngày 2026-10-05 bác bỏ quyết định cũ:
   bind `127.0.0.1` trong container trả 200 từ bên trong nhưng host không nhận được traffic publish.
7. **Git identity + `gh auth` qua env/volume, không bake vào image**: `GH_TOKEN` qua biến môi trường (đọc từ
   `.env` không commit, đúng luật cấm 3), `~/.gitconfig` của host mount read-only để orchestrator có
   `user.name`/`user.email` khi commit lên repo khách.
   Không ghi `git config --global` vào mount chỉ đọc: author đi qua env, committer dùng cùng identity nếu chưa
   được khai riêng. Image cài cả `docker-ce-cli` và `docker-compose-plugin` để đường deploy có lệnh compose.
8. **File cấu hình thuần, không TDD**: Dockerfile/compose/entrypoint là "file cấu hình thuần" — một trong các
   ngoại lệ luật bắt buộc 4 (`AGENTS.md`) cần hỏi người trước khi áp dụng; đã hỏi phạm vi tổng thể (chọn
   "hub-only"), coi đây là xác nhận đủ cho việc miễn TDD ở các file thuần cấu hình này. Thay test đơn vị bằng
   đo hai chiều thật dưới đây.

## Việc KHÔNG làm (cố ý)

- Không dựng `dockerd`-in-container — dùng socket passthrough, đơn giản hơn và nhất quán với cách ADR-0039 đã
  chọn khi orchestrator chạy trần.
- Không đóng gói `companies/keeper` thành service riêng trong PR này — console đọc `keeper.sqlite` qua volume
  là đủ; keeper hiện chưa có tiến trình dài hạn của riêng nó (canary vẫn chạy tay, xem sổ treo
  `docs/TASK-PACK.md`). Cần ADR riêng nếu sau này keeper có `watch` daemon.
- Không rolling update / nhiều máy / registry riêng — cùng khuôn "chưa làm, cố ý" mà ADR-0039 đã ghi cho phần
  deploy khách; đây là ADR đầu tiên cho container hoá hub, các ADR sau mở rộng nếu cần.

## Hệ quả

- `docs/TRUC-VA-DUNG-KHAN.md` cần thêm lệnh dừng khẩn cho **container hub** (`docker compose down`, ở gốc repo),
  phân biệt rõ với lệnh dừng khẩn container *khách* đã có từ ADR-0039 (khác project-name, khác thư mục).
- Người vận hành chạy `docker compose up -d` một lần ở gốc repo thay vì nhớ `cd` hai lớp thư mục + đặt cờ tay.
- Máy trực (WSL) nay cần Docker Engine cài sẵn và socket `/var/run/docker.sock` khả dụng cho container hub —
  đây là điều kiện hạ tầng mới, ghi vào tài liệu vận hành.
- Container hub cần thấy được `/var/run/docker.sock` của host để tự gọi `docker compose` cho khách — nghĩa là
  bất kỳ ai truy cập được container hub cũng có quyền tương đương root trên host qua Docker. Không đổi khác so
  với việc orchestrator chạy trần đã có quyền `docker` sẵn trên máy — không phải rủi ro mới do ADR này tạo ra,
  nhưng đáng ghi vì bề mặt tấn công nay đi qua một cổng duy nhất.

## Đo hai chiều (ghi trong commit khi cài, thay cho test đơn vị)

- Thiếu volume `company.sqlite`/`.artifacts` → container phải báo lỗi rõ lúc khởi động (đường dẫn không tồn
  tại), không âm thầm tạo file rỗng rồi coi như "đã chạy" — đúng khuôn ADR-0039 "không tụt hạng bảo vệ".
- Thiếu `GH_TOKEN` mà orchestrator cần mở PR khách → lỗi rõ từ `gh`, không nuốt lỗi.
- `docker build` + `docker compose up -d` + `curl 127.0.0.1:8200` phải trả đúng mã (200 hoặc mã route console
  thật) — build thật, không suy từ Dockerfile "trông đúng".
- `docker compose down` phải dừng sạch, không còn tiến trình con nào sống (`docker ps -a` rỗng cho project này).
