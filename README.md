# X-Agents — hub các "công ty AI" đa agent

X-Agents là kho chứa nhiều **công ty AI độc lập**, mỗi công ty là một hệ đa agent event-driven mô phỏng một phòng ban
thật: agent trao đổi qua topic có JSON Schema, tri thức chung nằm trên blackboard, con người duyệt ở các human gate cố định.
Nguyên tắc chung cho mọi công ty:

- **Trung lập provider**: đổi model/provider bằng cấu hình (`llm.yaml` hoặc biến môi trường), không đổi code hay prompt.
- **Model quyết định – code hành động**: tính toán, kiểm định, render, đăng… đều là code xác định, có thể kiểm thử offline.
- **Guardrail có hạn mức**: ngân sách token, ước lượng trước dispatch, chống prompt injection, audit-log mọi hành động.
- **Prompt là code**: agent và skill có version, golden test, eval ghi/phát lại chạy trong CI mà không gọi model.
- **Self-hosted, resume được**: bus SQLite, dừng và chạy tiếp ở bất kỳ điểm nào.

## Các thành phần

Hai nhóm thư mục, ranh giới theo vai trò (ADR-0011): `platform/` là hạ tầng dùng chung — không thuộc công ty nào;
`companies/` là các công ty, mỗi cái có agent, topic, human gate và khách riêng.

```
platform/     xagents-core/  gateway/  console/
companies/    software-company/  keeper/
```

| Thư mục | Vai trò | Quy mô |
|---|---|---|
| [`companies/software-company/`](companies/software-company/) | Công ty gia công phần mềm: từ ý tưởng thô → PRD → ticket → code trên worktree thật → review/QA/security → release → khách ký nghiệm thu | 7 khối, 6 agent (5 công đoạn + supervisor), 45 skill, 19 topic, 14 template, 3 human gate (+ gate `escalation`; kế hoạch do `_check_plan` chặn bằng code, ADR-0037) có trợ lý kiểm duyệt chỉ đọc (10 subagent + hồ sơ bằng chứng `gate_brief`, `/gate-brief`), giao hàng thật bằng tag + nhánh `company/release` (`--deliver`), ADR 0001–0048, 2058 test |
| [`platform/gateway/`](platform/gateway/) | Proxy OpenAI-compatible cục bộ, xoay vòng nhiều tài khoản Google Antigravity (Gemini / Claude). Mọi công ty trỏ `base_url` vào đây, không đổi code. **Nhiều tài khoản có rủi ro khoá tài khoản Google — đọc [§Rủi ro tài khoản](platform/gateway/README.md#rủi-ro-tài-khoản--đọc-trước-khi-gõ-make-login-lần-thứ-hai) trước** | daemon `127.0.0.1:1123/v1`, CLI `python -m gateway start/stop/status/login/logout/reset/ready/setup/models`, ADR 0001–0004, 312 test |
| [`platform/console/`](platform/console/) | Trực ban hợp nhất: một trang web cục bộ nhìn công ty — hàng đợi human gate, ticket, token và chi phí, gói tài khoản đang xoay — duyệt gate ngay tại chỗ khi bật `--allow-decide`, đổi model/backend khi bật `--allow-config`, giao việc mới (yêu cầu phần mềm kèm nơi lưu dự án) khi bật `--allow-submit`. Cập nhật tức thì bằng SSE, địa chỉ deep-link tới từng gate/ticket, tìm và lọc mọi bảng, cài được thành app (PWA). Đọc bus SQLite ở chế độ chỉ đọc; quyết định đi qua đúng `HumanGate`, việc mới đi qua đúng bus + schema của công ty | `127.0.0.1:8200`, chỉ thư viện chuẩn (`http.server`), 8 màn hình, chỉ đọc mặc định + token mỗi lần chạy, ADR 0001–0004, 744 test |
| [`platform/xagents-core/`](platform/xagents-core/) | Lõi chung của mọi công ty AI: bus, llm, runner, guard, gate, **execution harness kernel** — company import từ đây thay vì tự fork | mypy `strict` + phủ 100% dòng VÀ 100% nhánh từ ngày đầu, 678 test; execution contract/state/journal theo ADR gốc 0017, mở đường để phiên chính làm director thay vì giữ execution state trong context |
| [`companies/keeper/`](companies/keeper/) | Công ty bảo trì: tín hiệu → ticket bảo trì → patch có bằng chứng đo hai chiều → PR; khách hàng số 0 là chính repo này | 6 khối / 10 agent theo ADR-0006; BT1–BT7 đã merge — package có mã thật, chạy được, chưa qua canary (BT8), 841 test — chi tiết ở [`companies/keeper/README.md`](companies/keeper/README.md), lộ trình ở [`companies/keeper/docs/DAC-TA-KEEPER.md`](companies/keeper/docs/DAC-TA-KEEPER.md) |
| [`docs/HUONG-DAN-VAN-HANH.md`](docs/HUONG-DAN-VAN-HANH.md) | Hướng dẫn cài đặt và vận hành từng bước: cấu hình gói tài khoản, chạy thử, đưa yêu cầu, duyệt gate, theo dõi chi phí, bảo trì | |
| [`docs/DIEU-PHOI-MODEL.md`](docs/DIEU-PHOI-MODEL.md) | Điều phối model theo gói tài khoản: backend, 3 tier, bảng agent → tier, cơ chế xoay khi hết quota | |
| [`docs/TRUC-VA-DUNG-KHAN.md`](docs/TRUC-VA-DUNG-KHAN.md) | Trực ban và **dừng khẩn**: ba mức dừng (ticket / dự án / toàn hệ thống) kèm lệnh đã chạy thật, lịch trực luân phiên, cổng phát hành gộp lô, và danh sách thứ CHƯA có để không ai tưởng đã có | |
| [`docs/QUY-TRINH-GIT.md`](docs/QUY-TRINH-GIT.md) | Quy trình Git chung: nhánh, commit, PR, CI, merge squash | |
| [`AGENTS.md`](AGENTS.md) · [`CLAUDE.md`](CLAUDE.md) · [`TRAPS.md`](TRAPS.md) | **Bộ khung cho agent**: luật cấm/bắt buộc, bẫy đã mắc (có ngày, có PR). Bản đồ: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`CODEMAP.md`](CODEMAP.md) (muốn đổi X sửa ở đâu), [`CHANGELOG.md`](CHANGELOG.md). Thực thi: [`docs/TASK-PACK.md`](docs/TASK-PACK.md), [`docs/PROMPT-SHEET.md`](docs/PROMPT-SHEET.md), [`docs/sessions/`](docs/sessions/). Mỗi package con có `CLAUDE.md`/`TRAPS.md`/`CODEMAP.md`/`ARCHITECTURE.md` riêng | |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Cài đặt từng package, cổng chất lượng, checklist bắt buộc khi sửa agent/skill, quy tắc ADR | |
| [`SECURITY.md`](SECURITY.md) | Cách báo lỗi bảo mật, phạm vi, mô hình bí mật, các lớp phòng thủ đang có | |

Cả repo là **một project** ([uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)): `pyproject.toml` + `uv.lock`
ở gốc, năm thư mục là năm package thành viên dùng chung một `.venv`. Mỗi công ty tự chứa: `pyproject.toml`, `Makefile`, `agents/`,
`skills/`, `topics/`, `gates/`, `templates/`, `evals/`, `tests/`, `docs/` (kiến trúc + ADR), `llm.example.yaml`; software-company thêm
`examples/` (mô phỏng cả công ty, relay client). Không có `[project.scripts]`: mọi lệnh đều là
`python -m <package>.<module>` (package `company`). Đọc README trong từng thư mục để biết luồng và lệnh chi tiết. Repo khách
nằm ngoài repo này, chỉ ra bằng `--repo <đường dẫn>` khi chạy orchestrator.

## Chất lượng sản phẩm theo mục tiêu

`/product-goal` nối vào `/thi-hanh` với profile, Design Brief và bằng chứng theo dự án/ngành.
`company.quality_execution` dùng lại execution kernel để ghim contract và thêm task nghiệm thu cuối;
không thay sàn tự duyệt ADR-0043, không tự tạo daemon hoặc quyền phát hành. Chi tiết và giới hạn:
[`docs/PRODUCT-EXCELLENCE.md`](docs/PRODUCT-EXCELLENCE.md), ADR gốc 0018.

## Bắt đầu nhanh

Hướng dẫn đầy đủ từng bước: [`docs/HUONG-DAN-VAN-HANH.md`](docs/HUONG-DAN-VAN-HANH.md).

Yêu cầu: Python 3.11+, [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                        # một lần ở gốc repo: một .venv cho cả năm package
make test                      # pytest cả năm, không đo coverage (hoặc make lint / make cov / make build)
scripts/dev-task.sh gate all   # cổng đúng như CI: ruff → mypy → pytest --cov (fail_under = 100); hoặc gate <gói>

# Chạy offline (client giả), không cần key
cd companies/software-company && make test && make demo
```

Không có `make` (Windows): mỗi target đều có dạng `uv run` tương đương trong `Makefile`, ví dụ `make test` = `uv run pytest -q`,
`make demo` = `uv run python -m company.demo` — dùng nguyên văn được cả trong PowerShell.
`uv run` trong bất kỳ thư mục con nào cũng dùng `.venv` chung ở gốc.

Chạy model thật, không API key: mỗi công ty có sẵn hồ sơ **gói Claude + gateway Antigravity** — `make llm` chép
`llm.claude-gateway.yaml` thành `llm.yaml` là chạy được (cần `claude login` và `cd platform/gateway && make login && make start`).
`make llm` **từ chối cài** khi máy chưa đăng nhập tài khoản Antigravity nào (`python -m gateway ready`): hồ sơ trỏ
`base_url` vào daemon, cài lên máy trống là dựng sẵn một cấu hình chắc chắn hỏng ở lượt gọi model đầu tiên.
Muốn tự khai từ đầu thì sao chép `llm.example.yaml` → `llm.yaml` (bị gitignore), hoặc đặt biến môi trường
`COMPANY_LLM_*` (biến môi trường thắng file và bỏ qua `backends:`). Provider hỗ trợ: `anthropic`, `openai`
(mọi server OpenAI-compatible: OpenAI, OpenRouter, Ollama, Groq, vLLM, Gemini OpenAI-compat…), `claude-code` (CLI `claude -p`
đã đăng nhập gói Claude trên máy, không cần key), `codex` (CLI `codex exec --json`, gói ChatGPT Plus/Pro), `fake`.
`codex` không có tool-use nên khối kỹ thuật của software-company (cần sửa code) tự bỏ qua provider này. `claude-code` thì có, qua
một trong hai chế độ khai trong `llm.yaml`: `mcp_tools: true` (ADR-0024 — tool của công ty vào CLI qua cầu MCP, vẫn chạy trong
sandbox `tools.py`; khuyến nghị) hoặc `cli_tools: true` (ADR-0023 — CLI tự cầm tool riêng của nó, hàng rào yếu hơn một bậc).
`make probe` gọi model thật một lượt để biết CLI `claude` trên máy này chạy được chế độ nào (`mcp` | `cli` | `none`).

**Chạy bằng gói tài khoản, không mua token**: khai nhiều `backends:` trong `llm.yaml` (Claude Pro/Max qua `claude-code`,
ChatGPT qua `codex`, Google Antigravity qua gateway, model local; nhiều tài khoản cùng gói bằng `config_dir` riêng). Mỗi agent có tier `strong` / `standard` / `light`; `routing.prefer` chọn gói
theo tier (việc nặng đi gói mạnh, việc nhẹ đi gói miễn phí); gói nào hết hạn mức thì tự nghỉ và lượt đó đi gói kế.
Bảng agent → tier, lý do và chiến lược ưu tiên: [`docs/DIEU-PHOI-MODEL.md`](docs/DIEU-PHOI-MODEL.md).

Bật gateway xoay vòng tài khoản Google (miễn phí theo quota Antigravity):

```bash
cd platform/gateway
make login      # đăng nhập Google; chạy lại để thêm tài khoản   (= uv run python -m gateway login)
make start      # daemon tại 127.0.0.1:1123
make setup      # ghi ../../companies/software-company/llm.yaml dạng một provider trỏ vào gateway (không dùng khi llm.yaml đã có `backends:`)
```

Nhìn công ty trên một màn hình (và duyệt gate tại chỗ):

```bash
cd platform/console
uv run python -m console                 # 127.0.0.1:8200, chỉ đọc; terminal in địa chỉ kèm token phiên
uv run python -m console --allow-decide  # mở khoá các nút quyết định gate
uv run python -m console --allow-config  # mở khoá màn "Cài đặt model" (ghi llm.yaml, giữ bản .bak)
uv run python -m console --with-gateway --allow-decide  # một lệnh: bật gateway rồi console (ADR-0011 §3)
uv run python -m console models          # xem/đổi model từng tier, từng backend bằng CLI
```

**Chạy hub bằng Docker trên WSL** (ADR-0013 — cố định môi trường, tránh bẫy PATH của `uv`/`nvm` trong shell WSL
không tương tác đã đo ở `docs/sessions/2026-09-09-van-hanh-qlkh.md`):

```bash
cp .env.example .env   # điền GH_TOKEN, GIT_AUTHOR_*, CLIENT_REPO=/mnt/.../repo-khach
touch companies/software-company/company.sqlite companies/keeper/keeper.sqlite   # bind mount cần file có sẵn
docker compose up -d --build
docker compose logs -f hub
docker compose down     # dừng khẩn — xem docs/TRUC-VA-DUNG-KHAN.md §1 Mức 0
```

Cần Docker Engine cài sẵn trong WSL và `/var/run/docker.sock` khả dụng (orchestrator tự gọi `docker compose`
cho khách qua socket này, ADR-0039 — container hub không chạy `dockerd` riêng).

## Kiến trúc chung của một công ty

```
topic (JSON Schema, có key) ──► registry: agent nào nhận topic nào
        │                              │
        ▼                              ▼
   sqlite_bus ◄──── orchestrator ──► runner (vòng lặp tool, guard, cắt ngữ cảnh) ──► routing → llm (adapter từng gói tài khoản)
        │                 │
        │                 ├── human gate: chờ con người duyệt (gate_cli approve/reject)
        │                 └── supervisor: watchdog, ngân sách token, bài học
        ▼
   blackboard (artifact store, namespace theo owner) + audit-log (token thật, chi phí USD)
```

## Phát triển

- Trước khi push: `scripts/dev-task.sh gate <gói>` (`company|gateway|console|core|keeper|all`) — một lệnh, khớp
  đúng `ci.yml`. Cả năm package chạy ruff + mypy + pytest với ngưỡng coverage
  `fail_under` 100 / 100 / 100 / 100 / 100 cho companies/software-company / platform/gateway / platform/console / platform/xagents-core / companies/keeper,
  phủ 100% dòng VÀ 100% nhánh (`branch = true` ở cả năm; gateway và console bật sau cùng, #366) — mất một dòng hay
  một nhánh là CI đỏ. Dòng ngưỡng có cổng canh (`companies/software-company/tests/test_review_fixes_2026_09.py` so
  từng số với `pyproject.toml`), nên giữ nó trên một dòng.
- CI có bốn workflow; required check của `main` là `quality` (gom mọi job của `ci.yml`, thêm job con mới thì phải
  nối vào `needs` của nó) và `metadata` (`pr-policy.yml`: tiêu đề PR, có dòng CHANGELOG thêm vào, DoD không còn ô
  mở). Bảng đủ job, mỗi job chạy gì: [`ARCHITECTURE.md`](ARCHITECTURE.md) §CI — có cổng canh nên không lệch được.
- Sửa `agents/` hoặc `skills/` → checklist 7 bước ở [`CONTRIBUTING.md`](CONTRIBUTING.md) §3 (tăng `version` là bước
  đầu, không phải bước duy nhất — agent có tên trong `evals/recordings/REQUIRED.txt` mà thiếu bản ghi hoặc bản ghi
  lệch phiên bản prompt thì CI đỏ). Không liệt lại ở đây để tránh lệch với nguồn khi checklist đổi.
- Thay đổi lớn (kiến trúc, agent mới, schema topic) → viết ADR trong `<công ty>/docs/adr/` trước.
- Không commit secret, `llm.yaml`, dữ liệu thật; không gọi provider trả phí trong test; mọi thay đổi vào `main` qua PR.

## Cầu nối với projects-template

`company.template_handoff` xuất schema/chính sách từ DeliveryContract đang dùng và kiểm bundle spec/plan.
Template xuất dữ liệu theo chính sách này; consumer kiểm hash được ghim độc lập, đủ AC và bytes spec.
Không copy runtime, không tự duyệt hoặc phát hành: [cách dùng và ranh giới](docs/integrations/template-handoff.md).

## Giấy phép

Apache License 2.0 — xem [`LICENSE`](LICENSE).
