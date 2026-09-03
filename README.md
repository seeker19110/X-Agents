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

| Thư mục | Vai trò | Quy mô |
|---|---|---|
| [`software-company/`](software-company/) | Công ty gia công phần mềm: từ ý tưởng thô → PRD → ticket → code trên worktree thật → review/QA/security → release → khách ký nghiệm thu | 7 khối, 20 agent, 45 skill, 18 topic, 14 template, 4 human gate (+ gate `escalation`), ADR 0001–0022, 395 test |
| [`Studio-creators/`](Studio-creators/) | Phòng ban sáng tạo video (YouTube): kế hoạch → kịch bản → fact-check → render (TTS + ảnh + ghép) → sửa từng cảnh → review → đăng → số liệu thật nuôi chiến lược. Approval-first, media trung lập provider | 7 khối, 14 agent, 24 skill, 19 topic, 7 template, 4 human gate, ADR 0001–0008 (0007 tool web, 0008 adapter YouTube thật), 191 test |
| [`gateway/`](gateway/) | Proxy OpenAI-compatible cục bộ, xoay vòng nhiều tài khoản Google Antigravity (Gemini / Claude). Mọi công ty trỏ `base_url` vào đây, không đổi code | daemon `127.0.0.1:8100/v1`, CLI `python -m gateway start/stop/status/login/logout/reset/setup`, 79 test |
| [`console/`](console/) | Trực ban hợp nhất: một trang web cục bộ nhìn cả hai công ty — hàng đợi human gate, ticket, dây chuyền video, token và chi phí, gói tài khoản đang xoay — và duyệt gate ngay tại chỗ khi bật `--allow-decide`. Đọc bus SQLite ở chế độ chỉ đọc, quyết định đi qua đúng `HumanGate` của từng công ty | `127.0.0.1:8200`, chỉ thư viện chuẩn (`http.server`), 5 màn hình, chỉ đọc mặc định + token mỗi lần chạy, ADR 0001 |
| [`docs/HUONG-DAN-VAN-HANH.md`](docs/HUONG-DAN-VAN-HANH.md) | Hướng dẫn cài đặt và vận hành từng bước: cấu hình gói tài khoản, chạy thử, đưa yêu cầu, duyệt gate, theo dõi chi phí, bảo trì | |
| [`docs/DIEU-PHOI-MODEL.md`](docs/DIEU-PHOI-MODEL.md) | Điều phối model theo gói tài khoản: backend, 3 tier, bảng agent → tier, cơ chế xoay khi hết quota | |
| [`docs/QUY-TRINH-GIT.md`](docs/QUY-TRINH-GIT.md) | Quy trình Git chung: nhánh, commit, PR, CI, merge squash | |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Cài đặt từng package, cổng chất lượng, checklist bắt buộc khi sửa agent/skill, quy tắc ADR | |
| [`SECURITY.md`](SECURITY.md) | Cách báo lỗi bảo mật, phạm vi, mô hình bí mật, các lớp phòng thủ đang có | |

Mỗi công ty tự chứa: `pyproject.toml` + `uv.lock`, `Makefile`, `agents/`, `skills/`, `topics/`, `gates/`, `templates/`,
`evals/`, `tests/`, `docs/` (kiến trúc + ADR), `llm.example.yaml`; software-company thêm `examples/` (mô phỏng cả công ty,
relay client), Studio-creators thêm `media.example.yaml`. Không có `[project.scripts]`: mọi lệnh đều là `python -m <package>.<module>`
(package `company` và `studio`). Đọc README trong từng thư mục để biết luồng và lệnh chi tiết. Thư mục `projects/` ở gốc
để trống, dành cho repo khách khi chạy `--repo`.

## Bắt đầu nhanh

Hướng dẫn đầy đủ từng bước: [`docs/HUONG-DAN-VAN-HANH.md`](docs/HUONG-DAN-VAN-HANH.md).

Yêu cầu: Python 3.11+, [`uv`](https://docs.astral.sh/uv/). `ffmpeg` nếu muốn render video thật ở `Studio-creators`.

```bash
# Chạy offline (client giả), không cần key
cd software-company && uv sync && make test && make demo
cd ../Studio-creators && uv sync && make test && make demo
```

Không có `make` (Windows): mỗi target đều có dạng `uv run` tương đương trong `Makefile`, ví dụ `make test` = `uv run pytest -q`,
`make demo` = `PYTHONPATH=src uv run python -m company.demo` (PowerShell: `$env:PYTHONPATH='src'; uv run python -m company.demo`).

Chạy model thật: sao chép `llm.example.yaml` → `llm.yaml` trong công ty tương ứng (bị gitignore), hoặc đặt biến môi trường
`COMPANY_LLM_*` / `STUDIO_LLM_*` (biến môi trường thắng file và bỏ qua `backends:`). Provider hỗ trợ: `anthropic`, `openai`
(mọi server OpenAI-compatible: OpenAI, OpenRouter, Ollama, Groq, vLLM, Gemini OpenAI-compat…), `claude-code` (CLI `claude -p`
đã đăng nhập gói Claude trên máy, không cần key), `codex` (CLI `codex exec --json`, gói ChatGPT Plus/Pro), `fake`.
`claude-code` và `codex` không có tool-use nên khối kỹ thuật của software-company (cần sửa code) tự bỏ qua hai provider này.

**Chạy bằng gói tài khoản, không mua token**: khai nhiều `backends:` trong `llm.yaml` (Claude Pro/Max qua `claude-code`,
ChatGPT qua `codex`, Google Antigravity qua gateway, model local; nhiều tài khoản cùng gói bằng `config_dir` riêng). Mỗi agent có tier `strong` / `standard` / `light`; `routing.prefer` chọn gói
theo tier (việc nặng đi gói mạnh, việc nhẹ đi gói miễn phí); gói nào hết hạn mức thì tự nghỉ và lượt đó đi gói kế.
Bảng agent → tier, lý do và chiến lược ưu tiên: [`docs/DIEU-PHOI-MODEL.md`](docs/DIEU-PHOI-MODEL.md).

Bật gateway xoay vòng tài khoản Google (miễn phí theo quota Antigravity):

```bash
cd gateway && uv sync
make login      # đăng nhập Google; chạy lại để thêm tài khoản   (= PYTHONPATH=src uv run python -m gateway login)
make start      # daemon tại 127.0.0.1:8100
make setup      # ghi ../software-company/llm.yaml dạng một provider trỏ vào gateway (không dùng khi llm.yaml đã có `backends:`)
```

Nhìn cả hai công ty trên một màn hình (và duyệt gate tại chỗ):

```bash
cd console && uv sync
uv run python -m console                 # 127.0.0.1:8200, chỉ đọc; terminal in địa chỉ kèm token phiên
uv run python -m console --allow-decide  # mở khoá các nút quyết định gate
```

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

- CI (`.github/workflows/ci.yml`, Python 3.11 và 3.13): software-company và Studio-creators chạy cùng bộ cổng — ruff + mypy,
  pytest có ngưỡng coverage (`fail_under` 90 và 84, đặt ở mức đang đạt để chặn tụt lùi), và `evals all --replay --strict`;
  gateway chạy ruff + pytest; job `golden-check` chạy `make golden` rồi so `git diff --exit-code`; job `audit` chạy
  `pip-audit --strict` + gitleaks trên cả lịch sử; job `quality` gom kết quả. `pr-policy.yml` kiểm tra quy ước PR.
- Sửa `agents/` hoặc `skills/` → tăng `version`, `make golden`, `make eval-record AGENT=<id>` bằng model thật, commit bản ghi.
  Agent có tên trong `evals/recordings/REQUIRED.txt` mà thiếu bản ghi hoặc bản ghi lệch phiên bản prompt thì CI đỏ.
  Checklist đầy đủ: [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Thay đổi lớn (kiến trúc, agent mới, schema topic) → viết ADR trong `<công ty>/docs/adr/` trước.
- Không commit secret, `llm.yaml`, dữ liệu thật; không gọi provider trả phí trong test; mọi thay đổi vào `main` qua PR.

## Giấy phép

Apache License 2.0 — xem [`LICENSE`](LICENSE).
