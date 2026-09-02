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
| [`software-company/`](software-company/) | Công ty gia công phần mềm: từ ý tưởng thô → PRD → ticket → code trên worktree thật → review/QA/security → release → khách ký nghiệm thu | 7 khối, 20 agent, 45 skill, 18 topic, 4 human gate, ADR 0001–0018 |
| [`Studio-creators/`](Studio-creators/) | Phòng ban sáng tạo video (YouTube): kế hoạch → kịch bản → fact-check → render (TTS + ảnh + ghép) → sửa từng cảnh → review → đăng → số liệu thật nuôi chiến lược. Approval-first, media trung lập provider | 7 khối, 14 agent, 24 skill, 19 topic, 4 human gate, ADR 0001–0005 |
| [`gateway/`](gateway/) | Proxy OpenAI-compatible cục bộ, xoay vòng nhiều tài khoản Google Antigravity (Gemini / Claude). Mọi công ty trỏ `base_url` vào đây, không đổi code | daemon `127.0.0.1:8100/v1` |
| [`docs/QUY-TRINH-GIT.md`](docs/QUY-TRINH-GIT.md) | Quy trình Git chung: nhánh, commit, PR, CI, merge squash | |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md) | Đóng góp và báo lỗi bảo mật | |

Mỗi công ty tự chứa: `pyproject.toml` + `uv.lock`, `Makefile`, `agents/`, `skills/`, `topics/`, `gates/`, `templates/`,
`evals/`, `tests/`, `docs/` (kiến trúc + ADR). Đọc README trong từng thư mục để biết luồng và lệnh chi tiết.

## Bắt đầu nhanh

Yêu cầu: Python 3.11+, [`uv`](https://docs.astral.sh/uv/). `ffmpeg` nếu muốn render video thật ở `Studio-creators`.

```bash
# Chạy offline (client giả), không cần key
cd software-company && uv sync && make test && make demo
cd ../Studio-creators && uv sync && make test && make demo
```

Chạy model thật: sao chép `llm.example.yaml` → `llm.yaml` trong công ty tương ứng (bị gitignore), hoặc đặt biến môi trường
`COMPANY_LLM_*` / `STUDIO_LLM_*`. Provider hỗ trợ: `anthropic`, `openai` (mọi server OpenAI-compatible: OpenAI, OpenRouter,
Ollama, Groq, vLLM, Gemini OpenAI-compat…), `claude-code` (CLI `claude -p` đã đăng nhập trên máy, không cần key — Studio-creators), `fake`.

Dùng gateway xoay vòng tài khoản Google (miễn phí theo quota Antigravity):

```bash
cd gateway && uv sync
make login      # đăng nhập Google; chạy lại để thêm tài khoản
make start      # daemon tại 127.0.0.1:8100
make setup      # ghi ../software-company/llm.yaml trỏ vào gateway
```

## Kiến trúc chung của một công ty

```
topic (JSON Schema, có key) ──► registry: agent nào nhận topic nào
        │                              │
        ▼                              ▼
   sqlite_bus ◄──── orchestrator ──► runner (vòng lặp tool, guard, cắt ngữ cảnh) ──► llm (adapter provider)
        │                 │
        │                 ├── human gate: chờ con người duyệt (gate_cli approve/reject)
        │                 └── supervisor: watchdog, ngân sách token, bài học
        ▼
   blackboard (artifact store, namespace theo owner) + audit-log (token thật, chi phí USD)
```

## Phát triển

- CI (`.github/workflows/ci.yml`): lint (ruff + mypy), pytest kèm ngưỡng coverage, eval phát lại bản ghi cho từng công ty;
  `pr-policy.yml` kiểm tra quy ước PR.
- Sửa `agents/` hoặc `skills/` → tăng `version`, `make golden`, `make eval-record AGENT=<id>` bằng model thật, commit bản ghi.
- Thay đổi lớn (kiến trúc, agent mới, schema topic) → viết ADR trong `<công ty>/docs/adr/` trước.
- Không commit secret, `llm.yaml`, dữ liệu thật; không gọi provider trả phí trong test; mọi thay đổi vào `main` qua PR.

## Giấy phép

Apache License 2.0 — xem [`LICENSE`](LICENSE).
