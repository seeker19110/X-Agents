# Điều phối model theo gói tài khoản (subscription)

Các công ty trong X-Agents **không mua token qua API**. Chúng dùng những gói đăng ký đang có trên máy và tự chia việc
cho đúng model theo mức độ khó của từng agent, ưu tiên gói nào đang còn hạn mức. Tài liệu này là nguồn sự thật cho
ba câu hỏi: gói nào dùng được, agent nào cần model mức nào, và code điều phối ra sao.
Quyết định kiến trúc: `software-company/docs/adr/0019-subscription-routing.md`, `Studio-creators/docs/adr/0006-subscription-routing.md`.

## 1. Các gói tài khoản (backend)

| Backend | Cách nối | Model có | Đặc điểm |
|---|---|---|---|
| **Claude Pro/Max** | provider `claude-code`: CLI `claude -p` đã `claude login` trên máy | Opus / Sonnet / Haiku theo gói | Suy luận và code tốt nhất; hạn mức theo cửa sổ 5 giờ + tuần; **không tool-use** cho lớp ngoài (khối kỹ thuật cần tool phải đi backend khác) |
| **Google Antigravity** | provider `openai` → `../gateway` (`http://127.0.0.1:8100/v1`), xoay vòng nhiều tài khoản Google | `gemini-3.7-flash` (+`-medium`/`-low`), `gemini-3.1-pro`, `claude-sonnet-4-6` | Miễn phí theo quota từng tài khoản; gateway tự đổi tài khoản, hết cả pool thì trả 429 kèm "thử lại sau Ns"; có tool-use |
| **Model local** | provider `openai` → Ollama / vLLM / LM Studio | qwen3, llama, gemma... | Không bao giờ hết quota; chất lượng thấp hơn — lưới đỡ cuối cho việc nhẹ |
| (API trả phí) | provider `anthropic` / `openai` với key | tuỳ | Vẫn hỗ trợ, nhưng không phải mặc định của hub |

Khai báo trong `llm.yaml` của từng công ty dưới khoá `backends:` (mẫu trong `llm.example.yaml`). Thứ tự khai báo là
thứ tự ưu tiên; `routing.prefer` ghi đè theo tier.

## 2. Ba tier

| Tier | Dùng cho | Model gợi ý (Claude sub / Antigravity / local) |
|---|---|---|
| `strong` | Suy luận nhiều bước, viết/sửa code, review có hậu quả, sáng tác cần chất lượng | Opus 5 / claude-sonnet-4-6 / qwen3:32b |
| `standard` | Việc có cấu trúc rõ, đầu vào đã được chuẩn hoá, sai thì có gate hoặc code kiểm lại | Sonnet 5 / gemini-3.7-flash / qwen3:8b |
| `light` | Việc cơ học, ngắn: phân loại, gom, tóm tắt, điền mẫu; sai thì rẻ để sửa | Haiku 4.5 / gemini-3.7-flash-low / qwen3:8b |

Backend thiếu model cho một tier thì dùng `standard`, rồi `strong` (không bao giờ hạ tier của yêu cầu, chỉ nâng khi
không còn lựa chọn).

## 3. Agent → tier

Tiêu chí xếp: (a) độ sâu suy luận cần thiết; (b) hậu quả nếu sai và có lớp nào bắt lỗi phía sau không (gate người,
code kiểm định, agent review khác); (c) độ dài/độ phức tạp đầu ra; (d) tần suất chạy (agent chạy nhiều lượt kéo chi phí).

### software-company (20 agent)

| Agent | Tier | Vì sao |
|---|---|---|
| delivery-lead | strong | Kiến trúc, ước lượng, chia ticket có `depends_on`; sai kế hoạch kéo cả dự án |
| backend, frontend, mobile, database, platform, data | strong | Viết code thật trong worktree, tool-use nhiều lượt, PR phải qua lint/test thật |
| reviewer | strong | Đọc diff, bắt lỗi bảo mật/logic; là lớp bắt lỗi cho khối kỹ thuật nên không được yếu hơn |
| qa-debugger | strong | Phân tích nguyên nhân gốc khi test fail; suy luận nhiều bước |
| security-engineer | strong | Threat model STRIDE, DAST; hậu quả sai cao, chạy ít lượt |
| synthesizer, spec-writer | strong | Khử mâu thuẫn yêu cầu, viết PRD + Gherkin làm chuẩn nghiệm thu cho cả vòng đời |
| risk | strong | Rà khả thi/pháp lý/bảo mật sơ bộ; đầu vào cho `risk_tags` → quyết định có cần security review |
| researcher | standard *(trước: strong)* | Gom 4 góc nhìn nghiên cứu theo mẫu có sẵn, đầu ra được synthesizer (strong) đọc lại và khử mâu thuẫn; chạy sớm, hay lặp khi có clarification |
| release-engineer | standard *(trước: strong)* | Quy trình cố định gộp → build → staging → gate; phần nguy hiểm (merge, deploy) là code, gate 3 người duyệt |
| account-manager | standard *(trước: strong)* | SOW, UAT, change request theo mẫu; Gherkin dùng nguyên văn từ spec-writer; khách ký nghiệm thu là gate |
| support-docs | standard | Tài liệu Diátaxis, changelog, phân loại incident theo `root_cause_class` |
| intake | light *(trước: standard)* | Tách yêu cầu thô thành mục tiêu/ràng buộc/câu hỏi theo mẫu; researcher + synthesizer làm sâu phía sau |
| clarifier | light *(trước: standard)* | Gom chỗ mơ hồ thành câu hỏi có lựa chọn; con người trả lời là lớp kiểm |
| supervisor | light *(trước: standard)* | Phần xác định (ngân sách, watchdog) là code; model chỉ diễn giải và ghi bài học; chạy nhiều lượt nhất |

### Studio-creators (14 agent)

| Agent | Tier | Vì sao |
|---|---|---|
| channel-strategist | strong | Kế hoạch biên tập có ước lượng/ưu tiên/rủi ro; gate `plan` duyệt nhưng chất lượng kế hoạch quyết định cả kênh |
| script-writer | strong | Sáng tác: hook, giữ chân, CTA, sổ claim có nguồn; chất lượng nội dung là sản phẩm |
| fact-checker, rights-checker, quality-reviewer | strong | Ba cổng review độc lập trước gate publish; sai ở đây là đăng nội dung sai/vi phạm bản quyền |
| trend-researcher | standard | Gom nguồn, bằng chứng, đối thủ theo mẫu dossier; script-writer và fact-checker (strong) dùng lại |
| production-manager | standard | Chia kịch bản thành scene manifest có cấu trúc; renderer là code, editor xem lại |
| editor | standard | Quyết định cut-list sửa/khoá cảnh; tối đa 3 vòng, quality-reviewer kiểm sau |
| seo-optimizer | standard | Metadata theo kho từ khoá; preflight là code kiểm lại |
| analytics-analyst | standard | Diễn giải số liệu đã được code tính (retention map, A/B đã kiểm định) |
| thumbnail-designer | light *(trước: standard)* | Đặc tả prompt + chữ phủ cho 2–3 biến thể; CTR đo thật, A/B chọn |
| publisher | light *(trước: standard)* | Chỉ mô tả hành động đăng sau khi gate đã duyệt; mọi thứ đã được chốt |
| community-manager | light *(trước: standard)* | Phân loại bình luận, nháp trả lời theo giọng kênh; gate `replies` duyệt từng câu |
| supervisor | light *(trước: standard)* | Như software-company |

Đổi tier của agent = sửa `model_tier` trong front matter + `make golden` (registry golden ghi tier); không cần tăng
`version` hay ghi lại bản ghi eval vì system prompt không đổi.

## 4. Chiến lược ưu tiên theo tier (gợi ý `routing.prefer`)

| Tình huống | prefer |
|---|---|
| Có Claude Max + Antigravity | `strong: claude-sub`, `standard: antigravity`, `light: antigravity` — việc nặng dùng gói mạnh, việc nhẹ dùng gói miễn phí để giữ hạn mức Claude cho code |
| Chỉ Claude Pro (hạn mức thấp) + Antigravity | `strong: antigravity` (claude-sonnet-4-6 qua gateway), `standard/light: antigravity`; Claude Pro làm dự phòng |
| Chỉ Antigravity | một backend; gateway tự xoay tài khoản |
| Có thêm Ollama | để cuối danh sách, không `prefer`; chỉ nhận việc khi mọi gói khác nghỉ |

Khối kỹ thuật của software-company (tool-use) luôn bỏ qua backend `claude-code`; nếu muốn code bằng Claude thì cho
`claude-sonnet-4-6` qua Antigravity hoặc dùng provider `anthropic` có key.

## 5. Cơ chế xoay (code)

`RoutingClient` (`src/<company>/routing.py`) bọc mọi backend thành một `ModelClient`:

- Chọn backend: `prefer[tier]` trước, rồi theo thứ tự khai báo; bỏ backend không hỗ trợ tool khi request có tool.
- Hết quota (429/402, `RESOURCE_EXHAUSTED`, "usage limit", "thử lại sau Ns"...) → backend nghỉ `cooldown_s` (mặc định
  1 giờ) hoặc đúng số giây provider bảo; lượt đó đi backend kế.
- Lỗi mạng / 5xx / timeout → nghỉ `transient_cooldown_s` (mặc định 60 s).
- Lỗi nội dung (JSON hỏng, model từ chối) → ném ra ngay, không xoay: đó là việc của agent/supervisor.
- Mọi backend đều nghỉ → lỗi "thử lại sau Ns"; software-company hoãn event (TransientError), Studio ghi audit và
  supervisor thấy.
- Mỗi lần xoay được ghi vào audit `llm_retry` (qua `drain_retries()`), nên `report` cho thấy gói nào đang gánh việc.
- `Completion.model` vẫn là tên model thật để bảng giá `prices` khớp; gói subscription thì giá 0 nhưng vẫn phải có
  dòng giá để không bị đếm là `unpriced`.

Kiểm nhanh trạng thái gateway: `cd gateway && make status`. Trạng thái backend trong tiến trình orchestrator: ghi chú
`llm_retry` trong audit-log.
