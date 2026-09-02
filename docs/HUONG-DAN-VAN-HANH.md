# Hướng dẫn cài đặt và vận hành X-Agents

Tài liệu này dành cho người lần đầu dựng và chạy các "công ty AI" trong hub: từ cài công cụ, cấu hình gói tài khoản,
chạy thử offline, tới vận hành thật hàng ngày (đưa yêu cầu vào, duyệt gate, theo dõi chi phí) và bảo trì.
Kiến trúc và lý do thiết kế nằm ở README của từng thư mục và các ADR; ở đây chỉ là **việc cần làm, theo thứ tự**.

Mục lục
1. [Yêu cầu hệ thống](#1-yêu-cầu-hệ-thống)
2. [Cài đặt](#2-cài-đặt)
3. [Cấu hình model theo gói tài khoản](#3-cấu-hình-model-theo-gói-tài-khoản)
4. [Chạy thử offline](#4-chạy-thử-offline-không-tốn-hạn-mức)
5. [Vận hành software-company](#5-vận-hành-software-company)
6. [Vận hành Studio-creators](#6-vận-hành-studio-creators)
7. [Vận hành gateway](#7-vận-hành-gateway)
8. [Theo dõi, chi phí, sự cố](#8-theo-dõi-chi-phí-sự-cố)
9. [Bảo trì: sửa agent, skill, model](#9-bảo-trì-sửa-agent-skill-model)
10. [Checklist hàng ngày](#10-checklist-hàng-ngày)

---

## 1. Yêu cầu hệ thống

| Thành phần | Bắt buộc? | Ghi chú |
|---|---|---|
| Python ≥ 3.11 | Có | CI chạy 3.11 và 3.13 |
| [`uv`](https://docs.astral.sh/uv/) | Có | quản lý `.venv` và `uv.lock`; không dùng `pip` trực tiếp |
| Git | Có | software-company tạo git worktree theo ticket khi làm code thật |
| Claude Code CLI (`claude`) đã `claude login` | Nếu dùng gói Claude Pro/Max | provider `claude-code`; không cần API key |
| Tài khoản Google (Antigravity) | Nếu dùng gateway | miễn phí theo quota; nhiều tài khoản thì xoay vòng |
| `ffmpeg` trên PATH | Studio-creators, khi ghép video thật | thiếu thì test ghép video tự bỏ qua, provider `fake` vẫn chạy |
| `make` | Không | Windows thường không có; mọi lệnh `make x` đều có dạng `uv run` tương đương ghi trong `Makefile` |

Windows: dùng Git Bash hoặc PowerShell đều được. Khi lệnh in tiếng Việt lỗi mã hoá, đặt `PYTHONIOENCODING=utf-8`.

## 2. Cài đặt

```bash
git clone https://github.com/seeker19110/X-Agents.git
cd X-Agents

# mỗi thư mục là một dự án uv độc lập
cd software-company && uv sync && cd ..
cd Studio-creators  && uv sync && cd ..
cd gateway          && uv sync && cd ..
```

`uv sync` tạo `.venv` trong từng thư mục theo `uv.lock`. Cần SDK Anthropic (chỉ khi dùng provider `anthropic` có key):
`uv sync --extra anthropic`.

Kiểm tra cài đặt bằng test offline (không gọi model, không cần key):

```bash
cd software-company && uv run pytest -q && cd ..
cd Studio-creators  && uv run pytest -q && cd ..
cd gateway          && uv run pytest -q && cd ..
```

## 3. Cấu hình model theo gói tài khoản

Các công ty **không mua token qua API**; chúng dùng gói đăng ký đang có trên máy. Mỗi công ty đọc `llm.yaml` trong
thư mục của mình (bị gitignore, không bao giờ commit). Bảng agent → tier, chiến lược ưu tiên và cơ chế xoay:
[`DIEU-PHOI-MODEL.md`](DIEU-PHOI-MODEL.md).

### 3.1 Đăng nhập các gói

```bash
# Gói Claude Pro/Max: CLI dùng đăng nhập sẵn có
claude auth status        # "loggedIn": true là đủ

# Gói Google Antigravity: thêm tài khoản vào pool của gateway (mở trình duyệt; chạy lại để thêm tài khoản 2, 3...)
cd gateway
PYTHONPATH=src uv run python -m gateway login
PYTHONPATH=src uv run python -m gateway start     # daemon tại http://127.0.0.1:8100/v1
PYTHONPATH=src uv run python -m gateway status    # từng tài khoản: sẵn sàng / cooldown / hạn token
```

### 3.2 Viết `llm.yaml`

Mẫu đầy đủ có chú thích: `software-company/llm.example.yaml`, `Studio-creators/llm.example.yaml`. Cấu hình khuyến nghị
khi có cả Claude và Antigravity (giống nhau cho hai công ty, chỉ khác tiền tố biến môi trường):

```yaml
provider: claude-code          # chỉ là mặc định; có `backends:` thì các backend bên dưới mới được dùng
max_tokens: 16000
backends:
  - name: claude-sub           # Claude Pro/Max qua CLI `claude -p`; KHÔNG hỗ trợ tool-use
    provider: claude-code
    models: {strong: claude-opus-5, standard: claude-sonnet-5, light: claude-haiku-4-5}
  - name: antigravity          # gateway xoay vòng tài khoản Google; có tool-use
    provider: openai
    base_url: http://127.0.0.1:8100/v1
    api_key: gateway-local     # chuỗi bất kỳ, gateway tự xác thực Google
    models: {strong: claude-sonnet-4-6, standard: gemini-3.7-flash, light: gemini-3.7-flash-low}
routing:
  cooldown_s: 3600             # gói hết quota nghỉ bao lâu (Retry-After của provider ghi đè)
  transient_cooldown_s: 60     # lỗi mạng / 5xx nghỉ bao lâu
  prefer: {strong: claude-sub, standard: antigravity, light: antigravity}
```

Riêng software-company thêm bảng giá để `report` không đếm model của gói là "chưa có giá" (`unpriced`):

```yaml
prices:
  claude-opus-5: {input: 0.0, output: 0.0}
  claude-sonnet-5: {input: 0.0, output: 0.0}
  claude-haiku-4-5: {input: 0.0, output: 0.0}
  claude-sonnet-4-6: {input: 0.0, output: 0.0}
  gemini-3.7-flash: {input: 0.0, output: 0.0}
```

Quy tắc cần nhớ:

- Khối kỹ thuật của software-company (backend, frontend, mobile, database, platform, data) dùng tool-use, nên **tự bỏ
  qua backend `claude-code`** và đi antigravity. Muốn code bằng Claude thì để `claude-sonnet-4-6` ở antigravity như trên.
- Thiếu model cho một tier thì backend đó dùng `standard`, rồi `strong`.
- Chỉ muốn một gói tạm thời: `COMPANY_LLM_BACKENDS=claude-sub` (hoặc `STUDIO_LLM_BACKENDS`) lọc và sắp lại thứ tự.
- Đặt `COMPANY_LLM_PROVIDER` / `STUDIO_LLM_PROVIDER` bằng biến môi trường thì **bỏ qua `backends:`** (biến môi trường
  thắng file). Test và CI dùng cách này với `fake`.

### 3.3 Media cho Studio-creators (TTS, ảnh, ghép video)

```bash
cd Studio-creators
cp media.example.yaml media.yaml     # rồi sửa provider/model; key đặt qua STUDIO_MEDIA_API_KEY
```

Chưa có nhà cung cấp media thì để `fake` cho cả ba kênh: pipeline vẫn chạy trọn vẹn với file giữ chỗ.

### 3.4 Kiểm tra cấu hình bằng một lượt gọi thật

```bash
cd Studio-creators   # hoặc software-company
PYTHONIOENCODING=utf-8 PYTHONPATH=src uv run python -c "
from studio.llm import make_client   # software-company: from company.llm import make_client
c = make_client()
for tier in ('light','standard','strong'):
    r = c.complete(system='Trả lời JSON.', user='answer=ok', schema={'type':'object','properties':{'answer':{'type':'string'}}}, model_tier=tier)
    print(tier, r.model, r.tokens)
    print('\n'.join(c.drain_retries()))
"
```

Mỗi tier in ra model thật đã trả lời; dòng "backend ... nghỉ Ns" cho biết gói nào đang hết quota hoặc chưa đăng nhập.

## 4. Chạy thử offline (không tốn hạn mức)

```bash
cd software-company
PYTHONPATH=src uv run python -m company.demo        # cả công ty với client giả, dừng ở human gate rồi tự duyệt

cd ../Studio-creators
PYTHONPATH=src uv run python -m studio.demo         # brief → plan → gate → kịch bản → render giả → gate publish → đăng
```

Demo dùng `COMPANY_LLM_PROVIDER=fake` nội bộ, không đọc `llm.yaml`. Đây là cách nhanh nhất để thấy luồng topic, gate và
audit-log trước khi tiêu hạn mức thật.

## 5. Vận hành software-company

Mọi lệnh chạy trong `software-company/` với `PYTHONPATH=src`. Trạng thái nằm trong `company.sqlite` (mặc định, đổi bằng
`--db`). Nhiều tiến trình dùng chung file này được.

### 5.1 Đưa yêu cầu vào

Tạo `req.json` (đúng `payload` của topic `research-requests`; bắt buộc `project_id`, `description`):

```json
{
  "project_id": "P1",
  "description": "Web bán khoá học tiếng Nhật: catalog, giỏ hàng, thanh toán VNPay, admin quản lý khoá. Mobile-first.",
  "attachments": []
}
```

```bash
PYTHONPATH=src uv run python -m company.orchestrator publish research-requests req.json --actor human:sales
```

### 5.2 Chạy vòng lặp

```bash
PYTHONPATH=src uv run python -m company.orchestrator run --watch 5      # chạy liên tục, 5 giây một nhịp (Ctrl+C dừng, resume được)
PYTHONPATH=src uv run python -m company.orchestrator run                # một lượt rồi thoát
PYTHONPATH=src uv run python -m company.orchestrator run --workers 4 --web   # ticket khác key chạy song song; researcher được đọc web
```

Làm **code thật** trên repo khách: thêm `--repo ../khach --base main`. Khối kỹ thuật sửa trong worktree `ticket/<id>`,
PR mang lint/test thật; `--integration` để ticket rẽ từ và gộp vào nhánh `company/integration`; `--batch-release` gom
ticket approved của dự án vào một RC (một staging, một gate 3, một UAT).

### 5.3 Duyệt human gate

Vòng lặp dừng ở bốn điểm: spec, plan, release, và khách ký nghiệm thu. Xem và quyết định:

```bash
PYTHONPATH=src uv run python -m company.gate_cli list
PYTHONPATH=src uv run python -m company.gate_cli approve SPEC-P1 --by human:po
PYTHONPATH=src uv run python -m company.gate_cli reject  PLAN-P1 --by human:po --reason "tách ticket thanh toán nhỏ hơn"
```

Con người trả lời câu hỏi của clarifier, quyết định change request, nhận xét ticket đang chạy, hoặc tiếp quản worktree:

```bash
PYTHONPATH=src uv run python -m company.orchestrator publish clarification-answers ans.json --actor human:po
PYTHONPATH=src uv run python -m company.orchestrator decide-change CR-1 accepted --by human:po
PYTHONPATH=src uv run python -m company.orchestrator comment  T-12 --by human:lead --text "dùng idempotency key cho webhook"
PYTHONPATH=src uv run python -m company.orchestrator takeover T-12 --by human:lead      # đã sửa tay trong worktree: chạy lint/test, thay PR của agent
```

Sau khi release-engineer deploy staging và QA hồi quy pass, gate 3 mở; approve xong mới lên production. Khách ký
nghiệm thu bằng `acceptance-results` qua account-manager (gate 4, ADR-0017).

### 5.4 Nhìn vào bên trong

```bash
PYTHONPATH=src uv run python -m company.orchestrator status            # hàng đợi, event hoãn, ticket, gate chờ, blackboard, chi phí
PYTHONPATH=src uv run python -m company.orchestrator show architecture # toàn văn artifact mới nhất của một namespace blackboard
PYTHONPATH=src uv run python -m company.orchestrator report            # estimate vs actual, USD theo agent/model, hành động supervisor
PYTHONPATH=src uv run python -m company.orchestrator metrics [--prometheus]
```

## 6. Vận hành Studio-creators

Mọi lệnh chạy trong `Studio-creators/`. Trạng thái trong `studio.sqlite`; asset sinh ra ở `output/<video_id>/`.
Nguyên tắc approval-first: **không có gì được lên lịch, đăng hay trả lời công khai trước khi qua gate**.

### 6.1 Đưa brief kênh vào

`brief.json` (payload topic `channel-briefs`; bắt buộc `channel_id`, `goals`, `audience`, `pillars`):

```json
{
  "channel_id": "CH1",
  "goals": ["1000 sub trong 3 tháng"],
  "audience": "người mới làm YouTube",
  "pillars": ["hướng dẫn", "so sánh"],
  "cadence": "2 video/tuần",
  "boundaries": ["không hứa thu nhập", "không dùng nhạc chưa có license"],
  "language": "vi"
}
```

```bash
PYTHONPATH=src uv run python -m studio.orchestrator publish channel-briefs brief.json --actor human:owner
PYTHONPATH=src uv run python -m studio.orchestrator run --watch 5
```

### 6.2 Bốn gate

| Gate | Khi nào | Lệnh |
|---|---|---|
| `plan` | strategist đưa kế hoạch biên tập | `gate_cli approve PLAN-CH1-1 --by human:owner` |
| `publish` | video cuối + metadata + thumbnail + 3 review (fact, rights, quality) đều pass | `gate_cli approve PUB-CH1-V1 --by human:editor --reason "đăng 12:00 thứ 6"` |
| `replies` | community-manager nháp trả lời bình luận | `gate_cli approve REP-CH1-... --by human:owner` |
| `escalation` | supervisor thấy lỗi lặp / vượt ngân sách | `gate_cli approve|reject ...` |

```bash
PYTHONPATH=src uv run python -m studio.gate_cli list
```

### 6.3 Nối với nền tảng thật

Chưa có adapter YouTube: publisher tạo `publish-events` mô tả hành động đăng, con người (hoặc script) thực hiện rồi
báo lại; số liệu và bình luận cũng đưa vào bằng file:

```bash
PYTHONPATH=src uv run python -m studio.orchestrator publish publish-events published.json        # đã công khai
PYTHONPATH=src uv run python -m studio.orchestrator publish performance-snapshots stats.json     # số liệu thật → analytics
PYTHONPATH=src uv run python -m studio.orchestrator publish audience-comments comments.json      # bình luận → nháp trả lời
PYTHONPATH=src uv run python -m studio.orchestrator status | report
```

Schema của từng topic ở `topics/schemas/*.json`; mẫu tài liệu ở `templates/`.

## 7. Vận hành gateway

```bash
cd gateway
PYTHONPATH=src uv run python -m gateway start | stop | status
PYTHONPATH=src uv run python -m gateway login            # thêm tài khoản
PYTHONPATH=src uv run python -m gateway logout EMAIL
PYTHONPATH=src uv run python -m gateway reset [EMAIL]    # xoá cooldown
curl http://127.0.0.1:8100/auth/status                    # JSON: từng tài khoản, cooldown còn lại
curl http://127.0.0.1:8100/v1/models
```

- Token OAuth ở `~/.x-agents/auth/antigravity_tokens.json` (quyền 600); log ở `~/.x-agents/logs/gateway.log`.
- Pool trống hoặc mọi tài khoản đều cooldown: gateway trả lỗi kèm "thử lại sau Ns"; router của công ty cho backend
  antigravity nghỉ đúng chừng đó rồi đi gói khác. Không cần can thiệp.
- Chạy trên VPS: copy file token lên, `start`; refresh token tự làm mới.

## 8. Theo dõi, chi phí, sự cố

**Audit-log là nguồn sự thật.** Mọi lời gọi model, tool, gate, hành động supervisor đều là bản ghi `audit-log` trong
SQLite; `status` / `report` / `metrics` đọc từ đó.

| Dấu hiệu | Ý nghĩa | Làm gì |
|---|---|---|
| `llm_retry` có ghi chú "backend X hết quota → nghỉ 3600s" | gói X cạn hạn mức, việc đã chuyển gói kế | không cần làm gì; muốn quay lại sớm thì restart tiến trình (trạng thái nghỉ nằm trong bộ nhớ) |
| "backend antigravity thiếu: Chưa có tài khoản" | gateway chưa có tài khoản Google | `gateway login` |
| "mọi backend đều đang nghỉ, thử lại sau Ns" | mọi gói cùng cạn | software-company hoãn event và tự thử lại ở nhịp sau; Studio ghi lỗi, chạy lại `run` sau |
| `unpriced_calls` > 0 trong report | model không có dòng giá | thêm vào `prices:` (gói subscription: giá 0) |
| supervisor `warn` 80% / `budget_cut` 100% | ticket hoặc dự án chạm ngân sách token/USD | xem `status`, tăng `budget_tokens` trong ticket hoặc `budget_usd`, rồi `resume` |
| event `deferred: paused:...` | ticket bị supervisor pause hoặc chờ gate | duyệt gate hoặc resume qua `supervisor-actions` |
| output `invalid_output` lặp | model yếu cho tier đó | nâng model của tier trong backend, hoặc đổi `prefer` |

Ngân sách: mỗi brief/ticket phải có `estimate_tokens`; code từ chối kế hoạch nếu `budget_tokens < estimate × 1.5`.
software-company còn có trần `budget_usd` theo dự án: 80% warn, 100% pause cho tới khi người `resume`.

## 9. Bảo trì: sửa agent, skill, model

| Việc | Cần làm |
|---|---|
| Đổi model / gói / thứ tự ưu tiên | sửa `llm.yaml`; không chạm code hay prompt |
| Đổi tier của một agent | sửa `model_tier` trong front matter `agents/<khối>/<agent>.md` → `make golden` (registry golden ghi tier). Không cần tăng `version`, không cần ghi lại eval. Cập nhật bảng ở `DIEU-PHOI-MODEL.md` |
| Sửa prompt agent hoặc skill | tăng `version` trong front matter → `make golden` → `make eval-record AGENT=<id>` bằng model thật → commit `evals/recordings/<id>.json`. CI phát lại bản ghi và đỏ nếu lệch |
| Thêm provider mới | thêm một class client trong `llm.py` + nhánh trong `_single_client`; khai báo trong `backends:` |
| Thêm agent / topic / đổi schema | viết ADR ở `<công ty>/docs/adr/` trước; cập nhật `topics/`, `registry`, golden |
| Đổi tool web | `COMPANY_SEARCH_URL` / `STUDIO_SEARCH_URL` (SearXNG...) |

Lệnh kiểm tra chuẩn trước khi mở PR (mỗi thư mục):

```bash
uv run ruff check src tests
uv run mypy src/company --ignore-missing-imports      # software-company
uv run pytest -q
PYTHONPATH=src uv run python -m company.evals all --replay --strict   # studio: python -m studio.evals all --replay
```

Quy trình Git: [`QUY-TRINH-GIT.md`](QUY-TRINH-GIT.md). Không commit `llm.yaml`, `media.yaml`, `*.sqlite`, `output/`,
token gateway.

## 10. Checklist hàng ngày

1. `gateway status`: còn tài khoản sẵn sàng không; `claude auth status` còn đăng nhập không.
2. `orchestrator status` từng công ty: có gate nào chờ người, event nào hoãn lâu, ticket nào pause.
3. Duyệt gate; trả lời clarification / change request nếu có.
4. `report`: chi phí và hành động supervisor bất thường; `llm_retry` cho biết gói nào đang gánh việc.
5. Với Studio: đưa `publish-events`, `performance-snapshots`, `audience-comments` từ nền tảng vào để số liệu thật nuôi
   chiến lược.
6. Sao lưu `company.sqlite` / `studio.sqlite` và `output/` nếu có nội dung quan trọng.
