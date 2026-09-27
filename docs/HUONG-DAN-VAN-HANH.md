# Hướng dẫn cài đặt và vận hành X-Agents

Tài liệu này dành cho người lần đầu dựng và chạy các "công ty AI" trong hub: từ cài công cụ, cấu hình gói tài khoản,
chạy thử offline, tới vận hành thật hàng ngày (đưa yêu cầu vào, duyệt gate, theo dõi chi phí) và bảo trì.
Kiến trúc và lý do thiết kế nằm ở README của từng thư mục và các ADR; ở đây chỉ là **việc cần làm, theo thứ tự**.

Mục lục
1. [Yêu cầu hệ thống](#1-yêu-cầu-hệ-thống)
2. [Cài đặt](#2-cài-đặt)
3. [Cấu hình model theo gói tài khoản](#3-cấu-hình-model-theo-gói-tài-khoản) — 3.5 nhiều tài khoản cùng gói
4. [Chạy thử offline](#4-chạy-thử-offline-không-tốn-hạn-mức)
5. [Vận hành software-company](#5-vận-hành-software-company)
6. [Vận hành keeper (công ty bảo trì)](#6-vận-hành-keeper-công-ty-bảo-trì)
7. [Vận hành gateway](#7-vận-hành-gateway)
8. [Trực ban hợp nhất (console)](#8-trực-ban-hợp-nhất-console)
9. [Theo dõi, chi phí, sự cố](#9-theo-dõi-chi-phí-sự-cố)
10. [Bảo trì: sửa agent, skill, model](#10-bảo-trì-sửa-agent-skill-model)
11. [Checklist hàng ngày](#11-checklist-hàng-ngày)

---

## 0. Ngày đầu của người thứ hai — 30 phút, không tốn một đồng nào

Mục này dành cho người **chưa từng mở repo này**. Nó không giải thích kiến trúc; nó chỉ đưa bạn đi hết một vòng
thật — cài, chạy, thấy công ty làm việc, rồi **tự tay ký một quyết định** — bằng provider giả, không API key,
không tốn hạn mức. Mọi lệnh dưới đây đã được chạy thật trên Windows 11 + PowerShell trước khi viết vào đây; nếu
một lệnh không ra như mô tả thì đó là lỗi của tài liệu, hãy ghi lại chỗ vấp (xem cuối mục).

Cần trước: `git`, [`uv`](https://docs.astral.sh/uv/), và một terminal. Không cần Docker, không cần API key.

### Bước 1 — cài (≈ 2 phút)

```bash
git clone <URL repo> x-agents && cd x-agents
uv sync
```

Cả repo là **một** uv workspace: một lệnh cài cả năm package vào một `.venv` ở gốc. Không cần `PYTHONPATH`.

### Bước 2 — xem cả công ty chạy một vòng (≈ 1 phút)

```bash
cd companies/software-company
uv run python -m company.demo
```

Đây là toàn bộ vòng đời với client giả: yêu cầu → kế hoạch → ticket → PR → review → release → khách nghiệm thu.
Dòng cuối in ra `sprint report` và `events: 20`. Đọc từ dưới lên, ba dòng đáng chú ý:

```
REL-001: staging deployed, QA pass → gate release pending: True | TCK-1: merged
REL-001: production + khách nghiệm thu → TCK-1: closed
releases: ['REL-001', 'REL-002'] | gate pending: []
```

Điều cần rút ra: **công ty tự đi tới khi gặp một human gate, rồi dừng**. Demo tự duyệt hộ để chạy tiếp; ở đời
thật, chỗ đó là bạn.

### Bước 3 — tự tay đưa một yêu cầu vào (≈ 3 phút)

```bash
cd companies/software-company
```

Tạo `req.json` (dùng file tạm, đừng commit):

```json
{"project_id": "THU-1", "description": "Trang ghi chú một người dùng: thêm, sửa, xoá ghi chú; lưu cục bộ."}
```

```bash
uv run python -m company.orchestrator --db thu.sqlite publish research-requests req.json --actor human:po --key THU-1
```

Ra:

```
published research-requests key=THU-1 event=245ecda8...
```

`--actor` **phải** là `human:<tên>`: CLI là cửa của người, giả danh agent từ đây là vượt quyền (và bị chặn).

### Bước 4 — chạy orchestrator offline và gặp một bế tắc thật (≈ 2 phút)

```bash
COMPANY_LLM_PROVIDER=fake uv run python -m company.orchestrator --db thu.sqlite run --max-steps 40
```

PowerShell: `$env:COMPANY_LLM_PROVIDER="fake"` trên một dòng riêng trước lệnh.

Ra:

```
research-requests      THU-1           error:product:FakeClient hết câu trả lời; stalled:THU-1:product
{... "paused": ["THU-1"], "gates_pending": {"THU-1": "escalation"}, "stats": {"errors": 1} ...}
```

**Đây là kết quả ĐÚNG, không phải bạn làm sai.** Provider `fake` chỉ có sẵn kịch bản cho demo, không có cho một
yêu cầu bất kỳ. Cái đáng học nằm ở chỗ hệ **phản ứng** thế nào: nó không im lặng bỏ qua, không tự đoán tiếp —
nó dừng dự án (`paused`) và **mở một gate `escalation` để hỏi người**. Toàn bộ triết lý vận hành nằm trong một
dòng đó: máy làm được thì làm, không làm được thì hỏi, không bao giờ đoán.

### Bước 5 — ký quyết định đầu tiên của bạn (≈ 5 phút)

```bash
uv run python -m company.gate_cli --db thu.sqlite list
```

```
THU-1        escalation by=supervisor       checklist=agent_error,decision:retry|close
```

`checklist` là thứ bạn phải trả lời. Duyệt:

```bash
uv run python -m company.gate_cli --db thu.sqlite approve THU-1 --by human:<tên bạn> \
  --reason "agent_error: FakeClient hết câu trả lời vì demo không có kịch bản cho lượt product[intake]; decision: close; hint: chạy lại bằng model thật sau khi make llm"
```

```
THU-1: approve by human:<tên bạn>
```

`--reason` **bắt buộc ≥ 20 ký tự** và nên có ba phần: `root_cause` (vì sao kẹt) + `decision` (chọn gì) +
`hint` (agent làm gì tiếp). Không phải thủ tục: `hint` đi thẳng vào lượt sau của agent, nên `--reason "ok"` là
bạn gửi cho nó một chỉ dẫn rỗng. Kiểm lại:

```bash
uv run python -m company.gate_cli --db thu.sqlite list
```

```
(không có gate chờ)
```

Xong. Bạn vừa đi hết vòng mà một người trực làm mỗi ngày.

### Bước 6 — nhìn cả hai công ty trên một màn hình (≈ 2 phút)

```bash
cd ../../platform/console
uv run python -m console
```

Terminal in địa chỉ kèm token phiên; mở nó. Mặc định **chỉ đọc** — mọi nút quyết định bị khoá cho tới khi bạn
chạy lại với `--allow-decide`. Đóng bằng Ctrl-C.

### Dọn

```bash
cd ../../companies/software-company && rm thu.sqlite req.json     # PowerShell: Remove-Item thu.sqlite, req.json
```

Không commit `*.sqlite`, `llm.yaml`, `output/` — `.gitignore` đã chặn, nhưng biết vì sao thì hơn.

### Bốn điều cần nhớ sau 30 phút này

1. **Máy làm được thì làm, không làm được thì hỏi.** Mọi bế tắc đều thành một gate, không thành sự im lặng.
2. **Lý do duyệt gate là dữ liệu, không phải thủ tục** — nó đi vào lượt tiếp theo của agent.
3. **Không tin lời khai.** "Đã deploy" phải có bằng chứng máy sinh (`verified_by`), không phải model tự nói.
4. **Chưa chạy thì chưa được nói là xong.** Áp dụng cho agent, và cho cả bạn.

### Bạn vấp ở đâu?

Chỗ nào trong mục này khiến bạn phải đoán, phải mở file khác, hay ra kết quả khác mô tả — **ghi lại ngay lúc
vấp**, đừng để tới cuối. Mỗi chỗ vấp phải thành một mục trong `TRAPS.md` hoặc một sửa đổi ở đây **trong cùng
tuần** (đó là nghiệm thu K9.3 của `docs/DAC-TA-KICH-BAN-B.md`). Người thứ ba không nên vấp lại chỗ bạn đã vấp.

### Đi tiếp

- Muốn chạy bằng model thật: §3 (cấu hình theo gói tài khoản) rồi §5.
- Muốn hiểu vì sao hệ được dựng như vậy: `ARCHITECTURE.md` ở gốc, rồi `docs/adr/` của từng công ty.
- Luật bắt buộc khi sửa code: `AGENTS.md` ở gốc — đọc trước khi chạm file đầu tiên.

## 1. Yêu cầu hệ thống

| Thành phần | Bắt buộc? | Ghi chú |
|---|---|---|
| Python ≥ 3.11 | Có | CI chạy 3.11 và 3.13 |
| [`uv`](https://docs.astral.sh/uv/) | Có | quản lý `.venv` và `uv.lock`; không dùng `pip` trực tiếp |
| Git | Có | software-company tạo git worktree theo ticket khi làm code thật |
| Claude Code CLI (`claude`) đã `claude login` | Nếu dùng gói Claude Pro/Max | provider `claude-code`; không cần API key |
| Codex CLI (`codex`) đã `codex login` | Nếu dùng gói ChatGPT Plus/Pro | provider `codex`; app Codex Windows đi kèm CLI |
| Tài khoản Google (Antigravity) | Nếu dùng gateway | miễn phí theo quota; nhiều tài khoản thì xoay vòng |
| `make` | Không | Windows thường không có; mọi lệnh `make x` đều có dạng `uv run` tương đương ghi trong `Makefile` |

Windows: dùng Git Bash hoặc PowerShell đều được. Khi lệnh in tiếng Việt lỗi mã hoá, đặt `PYTHONIOENCODING=utf-8`.

## 2. Cài đặt

```bash
git clone https://github.com/seeker19110/X-Agents.git
cd X-Agents

# cả repo là một uv workspace: một lệnh cài cả năm package vào một .venv ở gốc
uv sync
```

`uv sync` tạo `.venv` ở gốc theo `uv.lock` duy nhất; `uv run` trong bất kỳ thư mục con nào cũng dùng `.venv` đó.
Cần SDK Anthropic (chỉ khi dùng provider `anthropic` có key): `uv sync --extra anthropic`.

Kiểm tra cài đặt bằng test offline (không gọi model, không cần key):

```bash
make test        # cả năm package; hoặc từng cái: cd companies/software-company && uv run pytest -q
```

## 3. Cấu hình model theo gói tài khoản

Các công ty **không mua token qua API**; chúng dùng gói đăng ký đang có trên máy. Mỗi công ty đọc `llm.yaml` trong
thư mục của mình (bị gitignore, không bao giờ commit). Bảng agent → tier, chiến lược ưu tiên và cơ chế xoay:
[`DIEU-PHOI-MODEL.md`](DIEU-PHOI-MODEL.md).

### 3.1 Đăng nhập các gói

Mỗi gói đăng nhập một lần, sau đó token tự làm mới:

```bash
# Claude Pro/Max — CLI `claude` dùng đăng nhập sẵn có của máy
claude auth status                                # "loggedIn": true là đủ; chưa thì: claude login

# ChatGPT Plus/Pro — Codex CLI (app Codex trên Windows đi kèm CLI; adapter tự tìm trong %LOCALAPPDATA%/OpenAI/Codex/bin
# khi không có `codex` trên PATH, hoặc đặt `binary:` cho backend)
codex login status                                # "Logged in using ChatGPT"; chưa thì: codex login

# Google Antigravity — thêm tài khoản vào pool của gateway rồi bật daemon
cd platform/gateway
uv run python -m gateway login     # mở trình duyệt; chạy lại để thêm tài khoản 2, 3...
uv run python -m gateway start     # daemon tại http://127.0.0.1:1123/v1
uv run python -m gateway status    # từng tài khoản: sẵn sàng / cooldown / hạn token
```

Nhiều tài khoản cho cùng một gói: xem 3.5.

### 3.2 Viết `llm.yaml`

Mẫu đầy đủ có chú thích: `companies/software-company/llm.example.yaml`. Cấu hình khuyến nghị khi có cả Claude
và Antigravity:

```yaml
provider: claude-code          # chỉ là mặc định; có `backends:` thì các backend bên dưới mới được dùng
max_tokens: 16000
backends:
  - name: claude-sub           # Claude Pro/Max qua CLI `claude -p`; KHÔNG hỗ trợ tool-use
    provider: claude-code
    models: {strong: claude-opus-5, standard: claude-sonnet-5, light: claude-haiku-4-5}
  - name: claude-sub-2         # tài khoản Claude thứ hai, đăng nhập bằng CLAUDE_CONFIG_DIR=~/.claude-acc2 claude login
    provider: claude-code
    config_dir: ~/.claude-acc2
    models: {strong: claude-opus-5, standard: claude-sonnet-5, light: claude-haiku-4-5}
  - name: chatgpt-sub          # ChatGPT Plus/Pro qua Codex CLI; KHÔNG hỗ trợ tool-use
    provider: codex
    models: {strong: gpt-5.6-terra, standard: gpt-5.6-terra, light: gpt-5.6-terra}
    # config_dir: ~/.codex-acc2   # tài khoản ChatGPT thứ hai
  - name: antigravity          # gateway xoay vòng tài khoản Google; có tool-use
    provider: openai
    base_url: http://127.0.0.1:1123/v1
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
  gpt-5.6: {input: 0.0, output: 0.0}
```

Quy tắc cần nhớ:

- Khối kỹ thuật của software-company (backend, frontend, mobile, database, platform, data) dùng tool-use, nên **tự bỏ
  qua backend `claude-code` và `codex`** và đi antigravity. Muốn code bằng Claude thì để `claude-sonnet-4-6` ở antigravity như trên.
- Thiếu model cho một tier thì backend đó dùng `standard`, rồi `strong`.
- Chỉ muốn một gói tạm thời: `COMPANY_LLM_BACKENDS=claude-sub` (hoặc `STUDIO_LLM_BACKENDS`) lọc và sắp lại thứ tự.
- Đặt `COMPANY_LLM_PROVIDER` / `STUDIO_LLM_PROVIDER` bằng biến môi trường thì **bỏ qua `backends:`** (biến môi trường
  thắng file). Test và CI dùng cách này với `fake`.
- Khoá backend ít dùng: `api_key_env` (tên biến chứa key thay vì ghi key vào file), `binary` (đường dẫn CLI `claude`/`codex`),
  `mcp_tools` + `mcp_max_turns` (ADR-0024) hoặc `cli_tools` + `cli_bash` (ADR-0023) cho backend `claude-code` — bật một trong hai thì khối kỹ thuật chạy được bằng gói Claude; `supports_tools` ép router coi backend CLI là có/không có tool-use (mặc định theo hai cờ trên), `max_tokens`,
  `effort` (theo tier: low|medium|high|xhigh|max), `extra` (tham số riêng của provider, vd. temperature). Retry lỗi mạng:
  `retries` / `retry_base` trong llm.yaml hoặc `COMPANY_LLM_RETRIES`.
- `gateway setup` ghi `llm.yaml` dạng một provider (không `backends:`); đã có `backends:` thì đừng chạy `setup`, khai backend
  `antigravity` như mẫu trên.

### 3.3b Đường tắt: hồ sơ gói Claude + gateway có sẵn

Không muốn tự viết `backends:` thì mỗi công ty có sẵn một hồ sơ chạy thật, đã kiểm trong CI:

```bash
claude login                                   # gói Claude Pro/Max trên máy
cd platform/gateway && make login && make start         # thêm tài khoản Google, bật daemon 127.0.0.1:1123
cd ../../companies/software-company && make llm             # chép llm.claude-gateway.yaml → llm.yaml (không ghi đè file đang có)
cd ../../platform/gateway && make models                   # đối chiếu tên model, exit 1 nếu lệch
```

Hồ sơ đó: tier `strong` đi gói Claude (`claude-opus-5`, bật `mcp_tools` nên khối kỹ thuật có tool), `standard`/`light` đi
gateway (Gemini Flash) cho rẻ, gói nào cạn thì tự rơi sang gói kia. Thêm tài khoản Claude thứ hai: bỏ chú thích khối
`claude-2` ở cuối file (xem 3.5).

### 3.3c Máy này chạy được chế độ tool nào (chỉ software-company)

Khối kỹ thuật chạy bằng gói Claude cần CLI `claude` làm được một trong hai việc, mà chỉ gọi thật mới biết:

```bash
cd companies/software-company && make probe          # hoặc: make probe BACKEND=claude-1
```

Kết luận in ra cho từng backend `claude-code` trong `llm.yaml`:

| | Nghĩa | Việc cần làm |
|---|---|---|
| `mcp` | CLI gọi ngược được tool của công ty | Dùng `mcp_tools: true` — tool chạy trong sandbox `tools.py`, audit đầy đủ |
| `cli` | CLI chạy nhưng không hiểu `--mcp-config` (bản cũ), hoặc model bỏ qua tool | Chỉ còn `cli_tools: true` — hàng rào yếu hơn một bậc; nâng cấp `claude` rồi dò lại |
| `none` | Không gọi được CLI | Kiểm `claude login`, hạn mức còn không, đường dẫn binary |

Lệnh này gọi model thật một lượt rất ngắn (tier `light`, một tool không chạm file, không chạy lệnh), nên tốn hạn mức
không đáng kể. Exit code 1 nếu có backend nào chưa đạt `mcp`, dùng được trong script.

Sau khi chạy vài ticket, đọc lại audit để biết lượt nào đã đi chế độ nào — trường `mode` trong `tools_used`
(`loop` = vòng lặp của runner với provider API, `mcp`, `cli`).

### 3.4 Kiểm tra cấu hình bằng một lượt gọi thật

```bash
cd companies/software-company
PYTHONIOENCODING=utf-8 uv run python -c "
from company.llm import make_client
c = make_client()
for tier in ('light','standard','strong'):
    r = c.complete(system='Trả lời JSON.', user='answer=ok', schema={'type':'object','properties':{'answer':{'type':'string'}}}, model_tier=tier)
    print(tier, r.model, r.tokens)
    print('\n'.join(c.drain_retries()))
"
```

Mỗi tier in ra model thật đã trả lời; dòng "backend ... nghỉ Ns" cho biết gói nào đang hết quota hoặc chưa đăng nhập.

### 3.5 Nhiều tài khoản cùng một gói (Claude, ChatGPT, Google)

Router coi **mỗi tài khoản là một backend**. Muốn cộng dồn hạn mức của 5, 10 hay 20 tài khoản thì đăng nhập từng tài
khoản vào một "chỗ" riêng, rồi khai mỗi chỗ là một backend. Tài khoản nào báo hết hạn mức thì nghỉ, lượt đó đi tài
khoản kế; không cần can thiệp tay.

| Gói | Chỗ đăng nhập riêng cho từng tài khoản | Lệnh đăng nhập (trình duyệt mở, bạn tự đăng nhập) | Khoá trong backend |
|---|---|---|---|
| Claude Pro/Max | thư mục cấu hình `CLAUDE_CONFIG_DIR` | `CLAUDE_CONFIG_DIR=~/.claude-acc2 claude login` | `provider: claude-code`, `config_dir: ~/.claude-acc2` |
| ChatGPT Plus/Pro | thư mục `CODEX_HOME` | `CODEX_HOME=~/.codex-acc2 codex login` | `provider: codex`, `config_dir: ~/.codex-acc2` |
| Google Antigravity | pool của gateway (một file token chung) | `cd platform/gateway && uv run python -m gateway login` (lặp lại N lần) | một backend `antigravity` duy nhất; gateway tự xoay tài khoản bên trong |

Tài khoản mặc định (đã đăng nhập sẵn, không đặt biến) vẫn dùng được: backend không có `config_dir`.

Kiểm tra từng chỗ đã đăng nhập chưa:

```bash
CLAUDE_CONFIG_DIR=~/.claude-acc2 claude auth status     # "loggedIn": true
CODEX_HOME=~/.codex-acc2 codex login status             # "Logged in using ChatGPT"
curl http://127.0.0.1:1123/auth/status                  # pool Google: total / available
```

Ví dụ `llm.yaml` đầy đủ với 3 tài khoản Claude, 2 tài khoản ChatGPT và pool Google (thêm `prices:` giá 0 như 3.2):

```yaml
provider: claude-code
max_tokens: 16000
backends:
  - name: claude-1                       # tài khoản Claude mặc định của máy
    provider: claude-code
    models: {strong: claude-opus-5, standard: claude-sonnet-5, light: claude-haiku-4-5}
  - name: claude-2
    provider: claude-code
    config_dir: ~/.claude-acc2
    models: {strong: claude-opus-5, standard: claude-sonnet-5, light: claude-haiku-4-5}
  - name: claude-3
    provider: claude-code
    config_dir: ~/.claude-acc3
    models: {strong: claude-opus-5, standard: claude-sonnet-5, light: claude-haiku-4-5}
  - name: chatgpt-1                      # tài khoản ChatGPT mặc định (app Codex đã đăng nhập)
    provider: codex
    models: {strong: gpt-5.6-terra, standard: gpt-5.6-terra, light: gpt-5.6-terra}
    effort: {strong: high, standard: medium, light: low}   # → model_reasoning_effort của Codex
  - name: chatgpt-2
    provider: codex
    config_dir: ~/.codex-acc2
    models: {strong: gpt-5.6-terra, standard: gpt-5.6-terra, light: gpt-5.6-terra}
  - name: antigravity                    # N tài khoản Google nằm trong gateway
    provider: openai
    base_url: http://127.0.0.1:1123/v1
    api_key: gateway-local
    models: {strong: claude-sonnet-4-6, standard: gemini-3.7-flash, light: gemini-3.7-flash-low}
routing:
  cooldown_s: 3600
  transient_cooldown_s: 60
  prefer: {strong: claude-1, standard: antigravity, light: antigravity}
```

Cách router chọn với cấu hình trên:

- Tier `strong` đi `claude-1`; khi `claude-1` cạn thì theo thứ tự khai báo: `claude-2` → `claude-3` → `chatgpt-1` → ...
  Tức là **thứ tự trong `backends:` là thứ tự dự phòng**; xếp các tài khoản cùng gói cạnh nhau.
- Tier `standard` và `light` đi Antigravity trước (miễn phí); gateway cạn cả pool thì mới chạm tới Claude/ChatGPT.
- Khối kỹ thuật của software-company (cần tool-use) bỏ qua backend `codex`; `claude-code` thì dùng được khi bật
  `mcp_tools: true` (ADR-0024) hoặc `cli_tools: true` (ADR-0023), cạnh `antigravity` hoặc provider `anthropic`/`openai` có key.
- Muốn ChatGPT gánh việc tầm trung thay vì Google: `prefer: {standard: chatgpt-1}`.

Kiểm tra sau khi cấu hình: chạy đoạn ở 3.4. Muốn thử riêng một tài khoản, lọc bằng biến môi trường:

```bash
STUDIO_LLM_BACKENDS=claude-2 uv run python -c "..."     # software-company: COMPANY_LLM_BACKENDS
```

Lưu ý:

- Đăng nhập là thao tác trình duyệt, mỗi tài khoản một lần; sau đó token tự làm mới, không phải đăng nhập lại.
- Trạng thái "đang nghỉ" của backend nằm trong bộ nhớ tiến trình orchestrator; khởi động lại thì mọi backend được thử
  lại từ đầu. Tài khoản còn cạn sẽ báo lại ngay và nghỉ tiếp.
- Ghi chú `llm_retry` trong audit-log cho biết lượt nào đã đổi tài khoản và vì sao; `report` cho thấy tài khoản nào
  đang gánh việc.
- Điều khoản gói cá nhân của Anthropic và OpenAI không cho dùng nhiều tài khoản để vượt hạn mức; Google có thể hạn chế
  nhiều tài khoản cùng máy/IP. Kỹ thuật chạy được, rủi ro khoá tài khoản là của người vận hành.

## 4. Chạy thử offline (không tốn hạn mức)

```bash
cd companies/software-company
uv run python -m company.demo        # cả công ty với client giả, dừng ở human gate rồi tự duyệt
```

Demo dùng `COMPANY_LLM_PROVIDER=fake` nội bộ, không đọc `llm.yaml`. Đây là cách nhanh nhất để thấy luồng topic, gate và
audit-log trước khi tiêu hạn mức thật.

## 5. Vận hành software-company

Mọi lệnh chạy trong `companies/software-company/` (không cần `PYTHONPATH`: cả repo là một uv workspace, `uv run` tự thấy
package). Trạng thái nằm trong `company.sqlite` (mặc định, đổi bằng
`--db`). Nhiều tiến trình dùng chung file này được.

### 5.1 Đưa yêu cầu vào

Tạo `req.json` (đúng `payload` của topic `research-requests`; bắt buộc `project_id`, `description`):

```json
{
  "project_id": "P1",
  "description": "Web bán khoá học tiếng Nhật: catalog, giỏ hàng, thanh toán VNPay, admin quản lý khoá. Mobile-first.",
  "attachments": [],
  "repo": "D:/khach/web-khoa-hoc",
  "base": "main"
}
```

`repo`/`base` là tuỳ chọn (ADR-0025): **nơi lưu dự án** — repo git của khách cho riêng dự án này, trên máy chạy
orchestrator (nên dùng đường dẫn tuyệt đối). Bỏ trống thì dự án dùng `--repo`/`--base` của tiến trình `run`; không có
cả hai thì dự án chạy không repo (PR ghi `local_checks.unverified`). Repo khai sai không dừng dự án: audit
`project.repo_invalid` một lần, publish lại `research-requests` với đường dẫn đúng là orchestrator cập nhật, không cần
khởi động lại. Một tiến trình phục vụ được nhiều khách, mỗi khách một repo.

```bash
uv run python -m company.orchestrator publish research-requests req.json --actor human:sales
```

Mẫu đầy đủ hơn (một web app quản lý trung tâm, có đủ tám phần mà `product` pha `intake` cần để đặt câu hỏi cho cả bốn mảng
domain/ux/codebase/tech): `companies/software-company/examples/yeu-cau-mau-web-app.json` — chép rồi sửa cho khách của bạn.
Mô tả càng nêu rõ **ngoài phạm vi** và **yêu cầu phi chức năng có số đo** thì spec càng ít phải hỏi lại ở gate.

Không muốn viết JSON tay: chạy console với `--allow-submit` (`cd platform/console && uv run python -m console --allow-submit`),
vào màn **Xưởng phần mềm** → khối *Giao việc* ở đầu màn → form *Yêu cầu phần mềm* (có ô *Nơi lưu dự án* = `repo`).
Cùng một event, cùng schema — chỉ khác là điền vào ô. Câu hỏi làm rõ của `product` (pha `intake`) cũng trả lời được ở form
*Trả lời câu hỏi làm rõ* ngay đó, thay cho `publish clarification-answers`.

### 5.2 Chạy vòng lặp

```bash
uv run python -m company.orchestrator run --watch 5      # chạy liên tục, 5 giây một nhịp (Ctrl+C dừng, resume được)
uv run python -m company.orchestrator run                # một lượt rồi thoát
uv run python -m company.orchestrator run --workers 4 --web   # ticket khác key chạy song song; pha research được đọc web
```

Làm **code thật** trên repo khách: thêm `--repo ../khach --base main`. `builder` sửa trong worktree `ticket/<id>`,
PR mang lint/test thật; `--integration` để ticket rẽ từ và gộp vào nhánh `company/integration`; `--batch-release` gom
ticket approved của dự án vào một RC (một staging, một gate release, một UAT). Thêm `--deliver` để khi gate release được duyệt và
`ops` (pha `deploy`) báo production đã deploy, công ty đặt tag `v<version>` và fast-forward nhánh `company/release` trong repo
khách (ADR-0027; `--push-remote origin` để đẩy lên remote, `--release-branch` đổi tên nhánh). `main` của khách vẫn không bị
chạm — khách tự merge `company/release` (hoặc tag) vào `main` theo quy trình của họ.

Muốn khách **review bản giao ngay trên GitHub trước khi ký UAT** thì thêm `--deliver-pr` (ADR-0038): sau khi push
xong, công ty mở PR thật `company/release → <nhánh --base>` trên repo GitHub mà `--push-remote` trỏ tới — mở, **không
merge**; PR đang mở cùng head/base thì dùng lại. Cần `gh` (GitHub CLI) đã `gh auth login` trên máy trực: env chạy lệnh
con đã lọc `GH_*`/`GITHUB_*`, nên token trong biến môi trường không có tác dụng. Kết quả ở `status → delivery → pr`
và audit `delivery.pr_opened | pr_reused | pr_skipped | pr_failed`; `gh` lỗi hay remote không phải GitHub thì bản giao
vẫn xong, chỉ thiếu PR (mở tay). Hồ sơ `gate_brief UAT-<rid>` có mục "PR giao hàng" để người duyệt đối chiếu số PR.

#### Deploy thật bằng `docker compose` (ADR-0039)

Trước ADR-0039, `status=deployed` chỉ là lời khai của `ops`: không tiến trình nào của sản phẩm còn sống sau lượt
ấy (smoke ADR-0029 khởi động — probe — **giết**). Nay orchestrator dựng compose file **của khách** rồi tự kết
luận, và `deployed` nghĩa là *container đang chạy*.

Ba biến/khoá người vận hành cần biết:

| Đặt ở đâu | Tên | Giá trị | Nghĩa |
|---|---|---|---|
| env máy trực | `COMPANY_DEPLOY` | `auto` (mặc định) \| `compose` \| `off` | `auto`: có runtime trên PATH thì deploy, không có thì **bỏ qua kèm lý do**. `compose`: khai đích danh — thiếu binary là **lỗi**, không tụt về "coi như xong". `off`: giữ hành vi trước ADR-0039. |
| env máy trực | `COMPANY_DEPLOY_RUNTIME` | mặc định `docker` | Đổi khi runtime tên khác (`podman`). Chỉ bốn lệnh con được chạy: `up -d`, `ps`, `logs --tail`, `down`. |
| spec (`approved-specs.runtime.deploy`) | đường dẫn compose file trong repo khách | vd. `deploy/compose.yaml` | Không khai thì dò `docker-compose.yml`, `compose.yaml`. Khai một file **không tồn tại** → bỏ qua kèm lý do, **không** lặng lẽ rơi về file dò được. |

Kết luận của orchestrator, đọc ở `release-events.evidence.deploy` (và audit `release.deploy` /
`release.deploy_failed` / `release.deploy_skipped`):

- **`status=deployed`** — `up -d` thoát 0 **và** mọi service `running` **và** smoke vào cổng đã map trả đúng
  `expect_status`. Bằng chứng kèm `container_ids`, `port`, `started_at`, `smoke`, `verified_by: orchestrator`.
  Container **không** bị giết sau lượt: sản phẩm phải còn sống.
- **`status=deploy_failed`** — thiếu bất kỳ phần nào. Evidence nói phần nào hỏng + `logs_tail`; container đã được
  `compose down` tự động. RC dừng lại, gate escalation mở cho người quyết. **Khác `failed`**: ticket của RC không
  bị trả về làm lại — đây thường là chuyện hạ tầng máy trực (thiếu docker, cổng bận, compose sai), không phải code.
- **bỏ qua (`evidence.deploy.skipped`)** — chưa bật, không có compose file, spec không khai `runtime`, không có
  worktree. Hành vi y như trước ADR-0039; nhưng "bỏ qua" **không phải** "đã deploy", và evidence nói rõ lý do.

Mỗi môi trường là một compose project riêng do code đặt tên: `company-<project_id>-<env>`. Production vẫn **chỉ**
tới được qua đường cũ — `PROD_ROUTE` sau khi người ký gate release; ADR-0039 không thêm cổng nào. Cổng là của
compose file khách; lệnh dừng khẩn container và cảnh báo tranh cổng ở `TRUC-VA-DUNG-KHAN.md` §1 mức 4.

**Chạy thật một lần rồi ghi báo cáo (nghiệm thu D1).** CI không dựng container thật được (ma trận còn
`windows-latest`), nên D1 **chưa đóng** cho tới khi có `docs/reports/2026-09-xx-deploy-that.md`. Người vận hành làm
đúng các bước sau trên máy trực rồi dán kết quả vào báo cáo đó:

```bash
docker info | head -3                       # 1. có daemon thật (không chỉ có CLI); không có thì dừng ở đây
export COMPANY_DEPLOY=compose               # 2. khai đích danh: thiếu binary phải LỖI, không im lặng bỏ qua
cd companies/software-company
# 3. repo khách có compose file, và spec của dự án khai runtime.deploy trỏ đúng file đó
uv run python -m company.orchestrator --repo ../khach --integration company/integration --deliver run --watch 5
# 4. duyệt gate release khi tới:
uv run python -m company.gate_cli approve REL-00x --by human:<tên> --reason "<root_cause — decision — hint>"
# 5. bằng chứng máy sinh:
uv run python -m company.orchestrator trace REL-00x          # dòng thời gian: release.deploy / release.deploy_failed
sqlite3 company.sqlite "select body from events where topic='release-events' order by seq desc limit 1;"
docker ps --filter "name=company-" --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"
curl -i http://127.0.0.1:<port đã map>/<health>
# 6. dọn khi xong đo:
docker compose -p company-<project_id>-production down
```

Báo cáo phải có: output bước 5 (dán nguyên văn), tên project, id container, cổng, `smoke.http_status`, thời gian
`up -d`, và **một ca hỏng cố ý** (sửa compose cho service chết) để chứng minh `deploy_failed` + `down` tự động chạy
thật chứ không chỉ chạy trong test.

Thêm `--test-author` để **bộ test do một lượt khác viết** (ADR-0028): `qa` chạy pha `author`, đọc `acceptance` của
ticket (không thấy code, không thấy diff, không thấy `hint` của vòng trước), ghi **chỉ** file test và commit vào nhánh
ticket; rồi `builder` viết code cho tới khi bộ test đó xanh mà **không ghi và không xoá được** file test — ranh giới
cưỡng chế ở `tools.py`, không phải lời dặn trong prompt. Hai lượt là hai PHA của cùng một agent, nhưng pha `author`
không được nạp skill review và không thấy diff (`BLIND_STRIP`), nên tính độc lập vẫn do code cưỡng chế.

- Test **đỏ ngay sau lượt `qa[author]` là đúng**: nó chứng minh bộ test ràng buộc một hành vi chưa tồn tại. Xanh ngay
  mới là dấu hiệu đáng ngờ (test rỗng, assert vô nghĩa) → audit `tests_green_before_code`.
- `builder` cho rằng test sai đặc tả thì ghi `test_dispute` vào PR; việc quay về `qa[author]` (lượt này được xem
  diff). Đó là đường **duy nhất** bộ test được đổi sau khi đã viết.
- Repo mà công ty không nhận ra vùng test (stack `unknown`) thì **không** chạy lượt `qa[author]` — không cưỡng chế được
  ranh giới thì không giả vờ có nó. Ticket đi đường cũ và PR mang `tests_authored_by: assignee`, để lượt `qa[review]`
  biết bộ test này không độc lập và tự chấm kỹ hơn.
- Giá: thêm một lượt model (tier `standard`) mỗi ticket, và ticket chạy tuần tự hơn một nhịp.

### 5.3 Duyệt human gate

Vòng lặp dừng ở ba điểm: spec, release, và khách ký nghiệm thu (`GateKind` còn bốn giá trị — thêm `escalation` khi
kẹt). Kế hoạch KHÔNG còn gate từ ADR-0037: `_check_plan` kiểm bằng code rồi giao ticket ngay; sai thì orchestrator
trả kế hoạch về `product[plan]` sửa **`PLAN_REWORKS` lần** (mặc định 1, audit `plan.rework`, lượt sửa mang `hint` là
đúng danh sách lỗi) — vẫn sai thì `plan_rejected` + gate `escalation`; duyệt retry là cho thêm đúng chừng đó lượt tự
sửa. Xem và quyết định:

```bash
uv run python -m company.gate_cli list
uv run python -m company.gate_cli approve SPEC-P1 --by human:po
uv run python -m company.gate_cli reject  REL-001 --by human:po --reason "smoke production chưa có bằng chứng; decision: request_changes; hint: chạy lại staging"
```

Năm quyết định: `approve`, `request_changes`, `reject`, `hold`, `rollback` (cùng cú pháp `SUBJECT --by --reason`). Gate có hạn
24 giờ, nhắc ở 12 giờ; quá hạn thì supervisor escalate. Ticket blocked hoặc dự án kẹt mở thêm gate `escalation` (approve = mở
lại với hint, reject = đóng).

`gate_cli list` chỉ hiện nửa "Code gửi kèm" của checklist. Nửa "Người tự kiểm thêm" có trợ lý chuẩn bị bằng chứng, chỉ đọc,
không ký thay:

```bash
uv run python -m company.gate_brief REL-001 --repo ../khach   # hoặc: make gate-brief SUBJECT=REL-001 REPO=../khach
uv run python -m company.gate_brief --all                      # mọi gate đang chờ
```

Hồ sơ in ra màn hình và ghi `company.artifacts/<project>/gate-brief/<subject>.{md,json}`: mỗi mục tự kiểm là `ok` / `gap` /
`unknown` kèm sự việc và nguồn (namespace@version, topic, worktree) — không có mục nào là "nên duyệt". Với gate `escalation`
hồ sơ gom lịch sử thất bại, hint đã dùng (và hint lặp lại y hệt), ngân sách còn, worktree để hint mới cụ thể hơn "thử lại".
Trong Claude Code, `/gate-brief REL-001` chạy lệnh trên rồi gọi subagent `sc-gate-release` + trợ lý chuyên môn (`sc-qa`,
`sc-security`, `sc-ops`; chỉ Read/Grep/Glob) đọc hồ sơ và in một bản tóm; câu cuối luôn là lệnh
`gate_cli` để bạn tự ký.

Con người trả lời câu hỏi làm rõ (`product` pha `intake`), quyết định change request, nhận xét ticket đang chạy, hoặc
tiếp quản worktree:

```bash
uv run python -m company.orchestrator publish clarification-answers ans.json --actor human:po
uv run python -m company.orchestrator decide-change CR-1 accepted --by human:po
uv run python -m company.orchestrator comment  T-12 --by human:lead --text "dùng idempotency key cho webhook"
uv run python -m company.orchestrator takeover T-12 --by human:lead      # đã sửa tay trong worktree: chạy lint/test, thay PR của agent
```

Sau khi `ops` (pha `deploy`) deploy staging và `qa` (pha `review`) hồi quy pass, gate `release` mở; approve xong mới
lên production. Khách ký nghiệm thu bằng `acceptance-results` qua `ops` (pha `account`) — gate `acceptance`, ADR-0017.

#### Người im lặng thì sao — hai hạn tự đi tiếp (2026-09-23)

Sau khi đưa yêu cầu vào, người có thể không quay lại trả lời câu hỏi làm rõ; backend có thể chập chờn hàng giờ. Hai
biến môi trường đặt trần, đọc lại mỗi nhịp, không cần restart:

| Biến | Mặc định | Quá trần thì |
|---|---|---|
| `COMPANY_CLARIFY_TIMEOUT_H` | `24` | orchestrator lấy `default` của từng câu hỏi chưa trả lời làm câu trả lời (audit `clarification.assumed`, `status.clarifications_pending` hết chờ) và chạy pha `spec` từ draft. Người vẫn ký gate `spec` — giả định chỉ đi xa tới một PRD chờ người đọc |
| `COMPANY_TRANSIENT_MAX_H` | `2` | event hoãn `transient:` (mạng, quota) không thử lại nữa: gate `escalation` mở cho người (audit `agent_error_unhandled`); duyệt = chạy lại event đó |

Cùng đợt: `product[plan]` lỗi và threat model `block` cũng mở gate `escalation` thay vì chỉ ghi audit — không còn
trường hợp nào dự án chết mà `status` xanh.

#### Công ty tự duyệt release và nghiệm thu theo sàn chất lượng (ADR-0043, mặc định TẮT)

`COMPANY_GATE_AUTOAPPROVE=1` bật đường code tự đóng gate. Từ ADR-0043 bảng `company/gate_risk.py:RISK_RULES` có
hai hàng: `release-quality-floor` và `acceptance-quality-floor`. Bật cờ nghĩa là: **sau khi người ký spec**,
gate `release` (= lệnh deploy production) và gate nghiệm thu `UAT-*` được `code` tự `approve` khi — và chỉ khi —
bằng chứng DO MÁY SINH đạt sàn cứng trong `company/quality_floor.py`:

| Mã | Sàn (thiếu bất kỳ ⇒ chờ người) |
|---|---|
| R1 | mọi PR ticket của RC: lint + test xanh, `verified_by=workspace` |
| R2 | sản phẩm chạy được ở đúng sha đã staged (hồi quy `evidence.run` hoặc deploy staging, `verified_by=orchestrator`) |
| R3 | review QA trên release `pass`; security `pass` nếu RC có `risk_tags` hoặc dự án nâng `security_review` |
| R4 | không finding nào được người miễn |
| R5 | release chưa từng có escalation / quyết định khác approve |
| A1–A2 | (nghiệm thu) gate release đã duyệt + deploy production do orchestrator chứng ở đúng sha |

`spec` luôn cần người; `escalation` **không bao giờ** tự duyệt. Gate không đạt sàn vẫn chờ người như cũ, kèm một
dòng `audit-log` `gate.auto_skipped` liệt kê khoảng trống — người ký đọc đó để biết vì sao máy không ký.

**Nâng mức theo dự án lúc ký spec** (chỉ siết, không nới):

```bash
uv run python -m company.gate_cli approve SPEC-<dự án> --by human:<tên> --reason "<root_cause — decision — hint>" \
    --quality-bar release=human,acceptance=human,security_review=required
```

`release=human` — dự án này release/production luôn do người ký; `acceptance=human` — khách phải tự ký nghiệm thu;
`security_review=required` — mọi RC phải có review security `pass`. Khoá lạ ⇒ CLI từ chối và spec **chưa** được ký.

**Nghiệm thu do máy không phải chữ ký khách**: máy không ghi `acceptance-results`; gate `UAT-*` đóng dưới actor
`code` (audit `acceptance.auto`). Khách ký `rejected`/`conditional` sau đó thì chữ ký khách thắng: orchestrator
ghi `acceptance.overridden` và mở gate `escalation` trên release cho người quyết.

Bật cờ là quyết định có chủ ý của người vận hành. Không đặt biến ⇒ hành vi y hệt trước ADR-0011 giai đoạn 3.

### 5.4 Nhìn vào bên trong

```bash
uv run python -m company.orchestrator status            # hàng đợi, event hoãn, ticket, gate chờ, blackboard, chi phí
uv run python -m company.orchestrator show architecture # toàn văn artifact mới nhất của một namespace blackboard
uv run python -m company.orchestrator report            # estimate vs actual, USD theo agent/model, hành động supervisor
uv run python -m company.orchestrator metrics [--prometheus]
```

## 6. Vận hành keeper (công ty bảo trì)

Mọi lệnh chạy trong `companies/keeper/`. Trạng thái trong `keeper.sqlite`. Khách hàng số 0 của nó là **chính repo này**:
nó đọc tín hiệu (dependabot, CI, trôi tài liệu), gom thành ticket bảo trì có bậc rủi ro, và chỉ được mở PR khi
có bằng chứng đo hai chiều. Nó **không có quyền ghi** ngoài nhánh/commit/PR của chính nó (bất biến I1,
`companies/keeper/docs/DAC-TA-KEEPER.md` §0).

### 7.1 Chạy một vòng

```bash
cd companies/keeper
uv run python -m keeper.cli run --tickets tickets.json --root ../Claude-Agents-wt-keeper --dry-run
uv run python -m keeper.cli watch --db keeper.sqlite --repo .. --interval 300 --max-ticks 1
```

- `run --dry-run` in **kế hoạch** (ticket → thao tác → file sẽ đụng) và không chạm một byte nào. Bỏ `--dry-run`
  là thi hành thật; `--root` **bắt buộc** và phải là một worktree PHỤ — `patcher` từ chối ghi vào checkout chung.
- `watch` là vòng `watch → triage → patch → verify → gate? → release`. `--max-ticks 1` chạy đúng một nhịp rồi
  thoát (dùng khi muốn xem nó làm gì trước khi thả chạy dài). Bỏ `--max-ticks` là chạy mãi.
- `--repo` là repo để hỏi `gh` (**chỉ đọc**; `companies/keeper/src/keeper/github.py` chặn mọi argv ghi bằng mã).

### 7.2 Xem hàng đợi

```bash
uv run python -m keeper.cli gate --db keeper.sqlite list      # gate đang chờ người
```

Hàng đợi ticket, ngân sách còn lại, sổ nợ quá hạn và gate chờ đọc gọn hơn ở tab **Công ty bảo trì** của console
(§8). Ô nào ghi *"chưa chạy lần nào"* thì đúng nghĩa đen là chưa chạy — nó **không** hiện số 0.

### 7.3 Duyệt gate

```bash
uv run python -m keeper.cli gate --db keeper.sqlite approve KT-12 --by human:truc-ban --reason "bằng chứng hai chiều đủ"
uv run python -m keeper.cli gate --db keeper.sqlite reject  KT-12 --by human:truc-ban --reason "thiếu rà họ lỗi"
```

Quyết định nhận được: `approve`, `request_changes`, `reject`, `hold`, `rollback`. **Cả năm đều ĐÓNG gate** —
không giá trị nào "mở lại" ticket; muốn `keeper` làm lại một việc thì phải phát `supervisor-actions`
`resume` tường minh. `--by` bắt buộc là NGƯỜI (`human:<tên>`); `--by patcher` bị từ chối ngay tại CLI.

Duyệt trên console cũng đi đúng đường này (cùng `PersistentGate`, cùng four-eyes, cùng `audit-log`).

### 7.4 Hai biến môi trường

| Biến | Mặc định | Nghĩa |
|---|---|---|
| `KEEPER_MAX_PR_PER_WEEK` | `5` | trần PR bảo trì merge trong 7 ngày. Đọc **mỗi lần** hỏi ngân sách, nên hạ giữa đêm có hiệu lực ngay. Gõ sai kiểu (không phải số) → quay về mặc định, không nổ và cũng không thành "không giới hạn". |
| `KEEPER_GATE_APPROVERS` | **rỗng** | danh sách người được duyệt gate `keeper`, ngăn cách bằng dấu phẩy. |

```bash
export KEEPER_MAX_PR_PER_WEEK=2
export KEEPER_GATE_APPROVERS="human:truc-ban,human:cto"
```

> **Không đặt `KEEPER_GATE_APPROVERS` KHÔNG có nghĩa là "không ai duyệt được".** Tập rỗng ở lớp gate nghĩa là
> **allowlist tắt**: four-eyes vẫn còn (người duyệt phải khác người tạo gate), nhưng *bất kỳ ai khác người tạo*
> cũng ký được. Đây là hành vi mặc định của lõi (`xagents_core.gates.approvers`), giống hệt
> `COMPANY_GATE_APPROVERS` / `STUDIO_GATE_APPROVERS` — nhưng người vận hành phải biết, vì "chưa cấu hình" đọc
> như "chặt hơn" trong khi thực tế là "lỏng hơn". Muốn siết thì đặt biến.

### 7.5 Chưa có gì ở đây

- `companies/keeper/evals/` chưa dựng: `make eval-record` cần model thật, nên bước đó **chờ người**.
- Canary (một chu kỳ thật trên chính X-Agents, tự mở đúng một PR bảo trì có bằng chứng) **chưa chạy**.
- `keeper` chưa có `llm.yaml` nào, nên nó không xuất hiện ở màn *Cài đặt model* của console.

## 7. Vận hành gateway

```bash
cd platform/gateway
uv run python -m gateway start            # daemon; --foreground/-f chạy tiền cảnh; --host/--port
uv run python -m gateway stop
uv run python -m gateway status           # exit 1 nếu server tắt hoặc không còn tài khoản sẵn sàng
uv run python -m gateway login            # thêm tài khoản (--no-browser: chỉ in URL, không mở trình duyệt); loopback cổng 51121
uv run python -m gateway logout EMAIL
uv run python -m gateway reset [EMAIL]    # xoá cooldown
uv run python -m gateway setup            # ghi llm.yaml dạng MỘT provider (--target, --strong, --standard); không dùng khi đã có backends:
curl http://127.0.0.1:1123/auth/status                    # JSON: từng tài khoản, cooldown còn lại
curl http://127.0.0.1:1123/v1/models
```

- Token OAuth ở `~/.x-agents/auth/antigravity_tokens.json` (quyền 600); log ở `~/.x-agents/logs/gateway.log`.
- Pool trống hoặc mọi tài khoản đều cooldown: gateway trả lỗi kèm "thử lại sau khoảng Ns"; router của công ty cho backend
  antigravity nghỉ đúng chừng đó rồi đi gói khác. Không cần can thiệp. Cooldown mặc định: 401 → 5 phút; 402/403/429 → 1 giờ;
  mã khác → 60 giây; `Retry-After` ghi đè. Gateway không tự retry, chỉ xoay tài khoản.
- Bearer `gateway-local` (và `dummy`, `none`, `token`, `default`, `antigravity`, `sk-gateway`) là chuỗi giữ chỗ; muốn ghim một
  tài khoản thì gửi email của tài khoản đó làm bearer.
- Chạy trên VPS: copy file token lên, `start`; refresh token tự làm mới.

## 8. Trực ban hợp nhất (console)

Một trang web cục bộ nhìn cả hai công ty (software-company, keeper) trên một màn hình, thay cho việc mở nhiều
cửa sổ `status` / `report` / `gate_cli`.

```bash
cd platform/console
uv sync
uv run python -m console                 # 127.0.0.1:8200, CHỈ ĐỌC; terminal in địa chỉ kèm token phiên
uv run python -m console --allow-decide  # mở khoá các nút quyết định gate ngay trên trang
uv run python -m console --allow-decide --allow-submit --allow-engine   # điều khiển trọn vòng trên một trang
```

**Điều khiển trọn vòng trên trang (ADR-0004 của console).** Với ba cờ trên, người trực không cần terminal thứ hai:
ô *Động cơ* ở đầu màn Trực ban bật/tắt `orchestrator run --watch` của từng xưởng (chạy trong đúng thư mục công ty,
model vẫn là gói thuê bao khai trong `llm.yaml`), form *Yêu cầu phần mềm* giao việc, ngăn kéo gate ký quyết định.
Thứ tự một ngày: **bật động cơ → giao việc → ký gate → xem phễu → tắt động cơ**.

Ba điều phải biết trước khi dựa vào nó:

- Động cơ do console bật **chết khi tắt console** (Ctrl-C, đóng terminal). Chạy dài ngày, qua nhiều phiên console,
  thì vẫn bật ở terminal riêng như §5 — ô Động cơ chỉ thấy tiến trình do chính nó tạo, và nói rõ điều đó.
- Ô này hiện trạng thái **đo được**, không phải "đã bấm Bật": động cơ chết vì thiếu `llm.yaml` hiện `đã dừng` kèm
  mã thoát và đuôi log (`platform/console/.engine/<xưởng>.log`), không hiện `đang chạy`.
- `--allow-engine` là cờ **riêng**, `--allow-decide` không mở nó: ký gate và đốt hạn mức model là hai quyền khác nhau.
- **Động cơ bật từ console KHÔNG giao hàng, trừ khi console chạy kèm `--deliver-remote <remote>`.** Không có cờ
  đó thì `orchestrator` chạy không `--deliver --push-remote`, nên release được duyệt vẫn **không** được tag và
  đẩy lên repo khách — đúng sự cố 2026-09-10 (QA pass, gate ký, khách nghiệm thu, sản phẩm nằm lại máy). Ô Động
  cơ nói rõ trạng thái này (`delivers`); thấy *không giao hàng* mà đang chạy release thật thì tắt, bật lại kèm cờ:
  ```bash
  uv run python -m console --allow-decide --allow-engine --deliver-remote origin
  ```
  `--deliver-remote` cần `--allow-engine`; nêu một mình thì console dừng ngay với mã 2 thay vì hứa suông.

Mở đúng địa chỉ terminal in ra (có token phiên trong đó). Đường dẫn DB khác mặc định thì chỉ ra bằng
`--company-db` / `--keeper-db`.

Năm màn hình chính: **Trực ban** (hàng đợi gate của cả hai công ty xếp theo mức quá hạn, ô số event/token/PR chưa
kiểm, chi phí 14 ngày theo tier, bảng gói tài khoản đang xoay), **Xưởng phần mềm** (bảng ticket, PR chờ review,
kết quả review), **Công ty bảo trì** (hàng đợi ticket bảo trì, ngân sách còn lại, sổ nợ quá hạn, gate chờ — xem
§6), **Chi phí & hạn mức** (trần dự án, ngân sách token từng ticket, chi phí theo agent, can thiệp của
supervisor), **Nhật ký** (audit-log có bộ lọc). Trang tự làm mới 10 giây một lần, có nút tạm dừng, và ngưng làm
mới khi ngăn kéo chi tiết đang mở.

Cần biết khi vận hành:

- **Chỉ đọc là mặc định.** Không có `--allow-decide` thì mọi nút quyết định bị khoá — console là cửa sổ, không phải
  nút bấm, cho tới khi bạn cố ý bật. Bốn quyền ghi tách riêng: `--allow-decide` (ký gate) · `--allow-submit`
  (giao việc) · `--allow-config` (đổi model) · `--allow-engine` (bật/tắt động cơ).
- **Token sinh mỗi lần chạy**, ghi `platform/console/.console-token` (quyền 600, đã gitignore). Tắt server là token hết hiệu
  lực. Server chỉ bind loopback; `--host` khác bị từ chối khởi động.
- **Quyết định đi qua đúng `HumanGate` của công ty**: four-eyes (người duyệt phải khác người tạo), allowlist
  (`COMPANY_GATE_APPROVERS` / `STUDIO_GATE_APPROVERS` / `KEEPER_GATE_APPROVERS`) và `audit-log` vẫn áp như khi
  dùng `gate_cli` hay `keeper gate`. Ô "Bạn là" trên ngăn kéo chính là `--by`.
- **Công ty chưa chạy bao giờ** (chưa có file DB) không phải lỗi: trang hiện trạng thái rỗng kèm lý do, không hiện
  số 0 giả. Tab *Công ty bảo trì* ghi thẳng **"chưa chạy lần nào"** vào mọi ô — kể cả ô "nợ quá hạn", vì một số 0
  màu xanh và một hệ thống chưa từng chạy nhìn giống hệt nhau. Mất liên lạc với server thì có dải cảnh báo trên
  cùng và số liệu giữ nguyên lần đọc cuối.
- Console **đọc** SQLite trong lúc orchestrator đang ghi, không khoá gì; số liệu trễ tối đa một nhịp làm mới.

Chi tiết: [`../../platform/console/README.md`](../../platform/console/README.md), quyết định thiết kế ở `platform/console/docs/adr/0001-console-hop-nhat.md`.

## 9. Theo dõi, chi phí, sự cố

**Audit-log là nguồn sự thật.** Mọi lời gọi model, tool, gate, hành động supervisor đều là bản ghi `audit-log` trong
SQLite; `status` / `report` / `metrics` đọc từ đó.

| Dấu hiệu | Ý nghĩa | Làm gì |
|---|---|---|
| `llm_retry` có ghi chú "backend X hết quota → nghỉ 3600s" | gói X cạn hạn mức, việc đã chuyển gói kế | không cần làm gì; muốn quay lại sớm thì restart tiến trình (trạng thái nghỉ nằm trong bộ nhớ) |
| "backend antigravity thiếu: Chưa có tài khoản" | gateway chưa có tài khoản Google | `gateway login`; backend đã nghỉ trọn `cooldown_s` (1 giờ) nên restart tiến trình để dùng ngay |
| "mọi backend đều đang nghỉ, thử lại sau Ns" | mọi gói cùng cạn | software-company hoãn event và tự thử lại ở nhịp sau; Studio ghi lỗi, chạy lại `run` sau |
| `unpriced_calls` > 0 trong report | model không có dòng giá | thêm vào `prices:` (gói subscription: giá 0) |
| supervisor `warn` 80% / `budget_cut` 100% | ticket hoặc dự án chạm ngân sách token/USD | xem `status`, tăng `budget_tokens` trong ticket hoặc `budget_usd`, rồi `resume` |
| event `deferred: paused:...` | ticket bị supervisor pause hoặc chờ gate | duyệt gate hoặc resume qua `supervisor-actions` |
| output `invalid_output` lặp | model yếu cho tier đó | nâng model của tier trong backend, hoặc đổi `prefer` |

Ngân sách: mỗi brief/ticket phải có `estimate_tokens`; code từ chối kế hoạch nếu `budget_tokens < estimate × 1.5`.
software-company còn có trần `budget_usd` theo dự án: 80% warn, 100% pause cho tới khi người `resume`.

## 10. Bảo trì: sửa agent, skill, model

| Việc | Cần làm |
|---|---|
| Đổi model / gói / thứ tự ưu tiên | sửa `llm.yaml`; không chạm code hay prompt |
| Đổi tier của một agent | sửa `model_tier` trong front matter `agents/<khối>/<agent>.md` → `make golden` (registry golden ghi tier). Không cần tăng `version`, không cần ghi lại eval. Cập nhật bảng ở `DIEU-PHOI-MODEL.md` |
| Sửa prompt agent hoặc skill | tăng `version` trong front matter → `make golden` → `make eval-record AGENT=<id>` bằng model thật → commit `evals/recordings/<id>.json`. CI phát lại bản ghi và đỏ nếu lệch |
| Thêm provider mới | thêm một class client trong `llm.py` + nhánh trong `_single_client` (hiện: anthropic, openai, claude-code, codex, fake); khai báo trong `backends:` |
| Thêm agent / topic / đổi schema | viết ADR ở `<công ty>/docs/adr/` trước; cập nhật `topics/`, `registry`, golden |
| Đổi tool web | `COMPANY_SEARCH_URL` (SearXNG...) |

Lệnh kiểm tra chuẩn trước khi mở PR (mỗi thư mục):

```bash
uv run ruff check src tests
uv run mypy src/company --ignore-missing-imports      # software-company
uv run pytest -q --cov                                # fail_under=100 ở cả năm package (AGENTS.md luật cấm 6)
uv run python -m company.evals all --replay --strict
```

Quy trình Git: [`QUY-TRINH-GIT.md`](QUY-TRINH-GIT.md). Không commit `llm.yaml`, `media.yaml`, `*.sqlite`, `output/`,
token gateway.

## 11. Checklist hàng ngày

1. `gateway status`: còn tài khoản sẵn sàng không; `claude auth status` còn đăng nhập không.
2. `orchestrator status` từng công ty: có gate nào chờ người, event nào hoãn lâu, ticket nào pause.
   Hoặc mở console (`cd platform/console && uv run python -m console`) để thấy cả hai xưởng trên một màn hình.
3. Duyệt gate; trả lời clarification / change request nếu có.
4. `report`: chi phí và hành động supervisor bất thường; `llm_retry` cho biết gói nào đang gánh việc.
5. Sao lưu `company.sqlite` / `keeper.sqlite` nếu có nội dung quan trọng.
