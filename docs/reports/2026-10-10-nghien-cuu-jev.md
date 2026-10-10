# Nghiên cứu Jev (TypeSafe AI) — có giúp gì cho X-Agents không

Ngày: 2026-10-10 · Nhánh `claude/clever-darwin-dazxkh` từ `main@433faa3` · Câu hỏi: *"nghiên cứu sâu về jev, nó
giúp ích gì cho dự án"*. Báo cáo chỉ đọc: không đổi code, không gọi Jev thật (phiên cloud không có khoá; `grep -ri
jev` trên repo = 0 kết quả, tức là chưa ai cân nhắc nó trước đây).

Kết luận một câu: **Jev là một "hàm quyết định có xác suất" rẻ và nhanh, hợp với đúng ba chỗ của hub ở chiều CHẶN /
XẾP ƯU TIÊN, nhưng chưa nên tích hợp lúc này** — nó là API trả phí ngoài, đưa dữ liệu khách ra ngoài, chưa có số
đo nào bằng tiếng Việt, và không có việc nào trong lộ trình hiện tại bị kẹt vì thiếu nó. Việc đáng làm là một thí
nghiệm bóng (shadow) chấm trên dữ liệu đã có trong bus, tốn vài USD, trước khi viết ADR.

---

## 1. Jev là gì (số liệu từ nguồn chính, ghi rõ ai nói)

| Mục | Giá trị | Nguồn |
|---|---|---|
| Nhà làm | TypeSafe AI (Diogo Almeida, cựu OpenAI); ra mắt 2026-09-15; gọi là "System One Model" đầu tiên | blog TypeSafe |
| Làm gì | Nhận `state` (văn bản/JSON) + một bộ **câu hỏi có kiểu**, trả **giá trị có kiểu + phân phối xác suất + confidence**. Không sinh chữ. | docs TypeSafe |
| Ba kiểu câu hỏi | `choice` (2–255 lựa chọn, trả `choice`, `probabilities`, `confidence`) · `score` (2–10 bậc có thứ tự, trả `score` = trung bình có trọng số, `probabilities`, `confidence`) · `noul` (có/không, trả xác suất 0–1, không có `confidence` riêng) | docs TypeSafe |
| `confidence` | `choice`: `(p_max − 1/n)/(1 − 1/n)`; `score`: 1 trừ khoảng cách có trọng số tới đỉnh. Docs gợi ngưỡng 0,5 (đưa người xem) và 0,9 (trước hành động không hoàn tác) — "điểm khởi đầu, không phải khuyến nghị" | docs `/confidence` |
| API | `POST https://api.typesafe.ai/v1/systemone`, Bearer key; body `{model, state, questions}`; SDK `pip install typesafe-sdk` (Py ≥ 3.10), `@typesafe-ai/sdk`; model `jev-latest` → `jev-1.13.0`; cũng có trên OpenRouter `typesafe/jev-1.13` (beta) | docs quickstart, OpenRouter |
| Giới hạn | state + câu hỏi dài nhất ≤ ~32k token; tổng ≤ ~64k; chỉ văn bản; 80 req/s, 100k token/s (10/2026) | docs, flaviocopes |
| Giá | **$0,042 / 1M token input, output miễn phí** (hãng nói có thể đang bù lỗ, kỳ vọng giảm chứ không tăng) | blog TypeSafe |
| Độ trễ | 70–500 ms end-to-end (đo từ bờ Tây Mỹ); bài pentest đo p50 236–276 ms | blog TypeSafe, arXiv 2609.28940 |
| Tình trạng | **Early access, waitlist; dừng nhận đăng ký 2026-09-22** (theo flaviocopes); không mở mã, không có bản tự host, chưa có paper hay benchmark công khai | flaviocopes, DataCamp |

Nhiều câu hỏi độc lập đi chung **một** lời gọi, chấm song song trên cùng state: cookbook của hãng đo 13 câu trong
một lần rẻ 12,2× và nhanh 10× so với 13 lần tuần tự (jev-1.12, tài liệu 53 777 ký tự).

### Bằng chứng hiệu năng — ai đo, đo thế nào

| Nguồn | Kết quả | Vì sao phải dè chừng |
|---|---|---|
| TypeSafe (4 workflow tự viết) | Jev 67,8 % · GPT-5.6 Terra 67,9 % · GPT-5.6 Sol 74,1 % · Opus 5 73,1 %; Jev $0,0004/ca, 0,4 s; headline "193,6× nhanh, 444,6× rẻ" | Hãng tự viết workflow, đáp án tham chiếu là trung bình GPT-6 Astra + Fable 5.1, LLM chạy qua adapter của hãng; trang chủ còn tự mâu thuẫn (ca hiển thị chỉ 75× nhanh, 171× rẻ) |
| `vinilana/jev-gateway` (120 phiên, agent code thật) | Sửa bug: giảm 25–57 % token/thời gian trên GPT-6 Astra, GPT-5.6 Sol, Sonnet 5. **Thêm tính năng: Opus 5 tệ hơn** (+22 % output, +61 % input, +83 % thời gian), Sonnet 5 cũng tệ hơn; GPT-5.6 Luna rẻ hơn nhưng chỉ xong 3/5 | 5 lần/ô, tác giả tự nhận mẫu nhỏ; mỗi lượt có tool thêm 0,5–1 s |
| arXiv 2609.28940 (pentest harness) | ECE của Jev **0,246** trên tập đánh giá của hãng (Laya mã mở: 0,081 sau temperature scaling) | ECE ~0,25 nghĩa là ngưỡng cố định không tin được nếu chưa tự hiệu chuẩn; nghiên cứu "thăm dò, không có sức mạnh thống kê" |
| `malevrigns/agent-jev` | Jev 1.13 zero-shot **72,7 %** top-1 trên tập Typed Decisions; AgentJev-0.6B (mã mở, Apache-2.0, Qwen3-0.6B) 79,25 % | Các model mở được fit trên benchmark đó, Jev thì không; "đồng thuận với teacher", không phải PR merge được |
| eesel.ai "review" | Khen primitive, chê "zero hallucination" là nói quá | Đối thủ cạnh tranh viết, **không chạy thử Jev** |

Điểm yếu hãng và người dùng đã nêu: đọc **nghĩa đen**, kém toán/đếm/so sánh ngày, độ chính xác tụt khi state
chứa nhiều thứ không liên quan, không có lý do bằng chữ (khó audit), "chính xác nhất bằng tiếng Anh" (jev-gateway).
Hãng tự liệt kê chỗ KHÔNG hợp: chat, viết code, copilot/coding agent có người ngồi cạnh, bài toán sinh-rồi-kiểm.

---

## 2. Đối chiếu với X-Agents — Jev là "lời khai", không phải "bằng chứng"

Ranh giới tin cậy của hub (`ARCHITECTURE.md`): trường "đã làm được" chỉ **code** điền; verdict của QA/security là lời
khai của model, `quality_floor` chỉ dùng nó theo chiều **chặn** (không `pass` ⇒ khoảng trống), không bao giờ theo
chiều **cho qua** một mình. Jev không thay đổi gì ở điểm này: một `noul = 0,93` vẫn là model nói, không phải
`verified_by=workspace`. Nên câu hỏi đúng không phải "Jev có thay gate/lint/test được không" (không), mà là **"ở đâu
hub đang trả tiền cho một LLM mạnh, hoặc đang dùng regex/hash, chỉ để lấy một quyết định đóng?"**

Rà toàn bộ điểm quyết định trong code, xếp theo độ hợp:

| # | Chỗ trong hub | Hiện tại | Jev làm được gì | Hợp? | Vì sao |
|---|---|---|---|---|---|
| A | **Hàng đợi gate** (`gate_cli list`, console) | Người trực đọc tuần tự, hạn 24 h, nhắc 12 h | `score` mức khẩn + `choice` "chạm auth/payment/migration?" (G6 bảo duyệt riêng) → **sắp thứ tự**, gắn nhãn; không ký | **Cao** | Chỉ đổi thứ tự hiển thị, không chạm quyết định; nhãn `human:*`/four-eyes giữ nguyên (ADR gốc 0024/0025); 1 lời gọi/gate, ~2k token → không đáng kể |
| B | **Phát hiện vòng tool không tiến bộ** (`company/runner.py::_stagnant`, 4L-3) | Đếm bộ ba `(name, args_hash, out_hash)` giống hệt; nhắc ở 3, cắt ở 5 | `noul` "5 lời gọi cuối có tiến bộ thực không?" trên `tools_trace` → bắt vòng lặp **ngữ nghĩa** (đổi args, cùng ý đồ) mà hash bỏ qua; chỉ **nhắc sớm**, cắt vẫn do code | **Trung bình–cao** | Đây là lỗ đã biết (`KIEN-TRUC-4-LOP.md` A1.3: ticket 956k token); Jev chỉ thêm tín hiệu, fail-open; chạy mỗi lượt tool → ~vài trăm lời gọi/ticket, vẫn < $0,01 |
| C | **Guard prompt injection** (`xagents_core/guard.py`) | Regex Anh/Việt, lớp ngoài cùng; nguồn ngoài thì thay bằng `LABEL` | `noul` "đoạn này đang cố điều khiển model?" làm lớp thứ hai cho nguồn NGOÀI (yêu cầu khách, diff repo khách, bình luận) | **Trung bình** | Đúng chiều chặn. Nhưng (1) phần lớn đầu vào là **tiếng Việt**, chưa có số; (2) **gửi nội dung khách ra API bên thứ ba** — xem §3 |
| D | **Tỉa ngữ cảnh** (`_prune`, ADR-0007) | Cắt `role=tool` cũ hơn 3 lượt, không nhìn nội dung | `noul` từng tool result "lượt sau còn cần không?" (kiểu `yoshi`) → tỉa theo liên quan thay vì theo tuổi | **Trung bình** | Audit token hôm nay (`2026-10-10-audit-token.md`) chưa giải thích được hệ số input 2,3–5,9×; **R1 phải làm trước** mới biết tỉa gì. Đổi hành vi agent ⇒ cần `eval-record` model thật |
| E | **Nâng tier theo rủi ro** (`routing.py`, ADR-0037 tier theo agent) | `qa` chạy `standard`, theo dõi `review_catch_rate` | `score` "diff này cần review `strong`?" → code nâng tier cho đúng lượt đó (mẫu "confidence-gated routing" của hãng) | **Trung bình–thấp** | Hợp nguyên tắc trung lập provider nếu làm ở routing; nhưng tier hiện là **của agent, không của lượt** — đổi là ADR |
| F | **Chọn tool thay LLM** (kiểu `jev-gateway`) | `builder` tier `strong`, vòng tool do runner hoặc `claude -p` + cầu MCP (ADR-0024) | Gateway chọn tool, LLM chỉ điền args | **Thấp** | Chính benchmark của jev-gateway cho thấy **Opus 5 tệ hơn 22–83 % ở việc thêm tính năng**; hãng tự nói "không hợp coding agent"; với `claude -p` không chen vào được |
| G | **Keeper triage/risk** (`risk.py::RISK_RULES`) | Bảng luật code tra theo tên hàng, `None` không rơi về `low` | `score` rủi ro → chỉ được phép **nâng** (medium → high), không hạ | **Thấp (lúc này)** | I4/bảng luật là có chủ đích để test từng ô; keeper chưa qua canary BT8 — thêm provider ngoài trước khi vòng tự động chạy được là sai thứ tự |
| H | **Chấm eval** (`evals.py`, `--replay --strict`) | Luật code chấm bản ghi | Rubric scorer | **Không** | Luật cấm 4: test/CI không gọi provider trả phí; Jev không có bản replay |
| I | **Supervisor** (tier `light`, chạy nhiều lượt nhất) | Code lo ngân sách/watchdog; model **viết bài học** | — | **Không** | Việc model ở đây là sinh chữ; Jev không sinh chữ |

Ba dòng đầu (A, B, C) là nơi Jev thật sự hơn thứ đang có: A thay một việc người đang làm bằng mắt, B và C thay
**regex/hash** chứ không thay LLM — tức là tăng độ phủ mà không đổi kiến trúc "model quyết định – code hành động".

---

## 3. Rào cản cứng theo luật repo (phải giải trước khi tích hợp bất kỳ dòng nào)

1. **API trả phí ngoài, ngược mặc định ADR-0019.** Hub "không mua token qua API", mọi backend là gói đăng ký. Jev
   không có bản subscription hay local; rẻ (ước 1 000 quyết định/ngày × 2k token ≈ **$0,08/ngày**) nhưng vẫn là
   khoá + hoá đơn + waitlist đang đóng. Thành backend thứ sáu phải ghi vào `docs/DIEU-PHOI-MODEL.md` §1.
2. **Dữ liệu khách ra ngoài.** C và D gửi yêu cầu/diff/tool output của repo khách tới `api.typesafe.ai`. Sandbox vừa
   siết egress (#394); `SECURITY.md` và luật cấm 3 coi dữ liệu khách là thứ không rời máy nếu khách chưa ký. A và B
   chỉ gửi metadata của hub (tên gate, `tools_trace` đã băm) nên nhẹ hơn nhiều — **đó là lý do xếp A, B trên C**.
3. **Luật cấm 4 (test offline).** Mọi adapter phải có provider `fake` + bản ghi phát lại như `llm.py`; nếu không CI
   không chạy được. Khuôn có sẵn: `ModelClient` → thêm `DecisionClient` cùng kiểu trong `xagents_core`, keeper và
   company không biết tên "jev" (I6).
4. **Chiều tin cậy.** Mọi điểm cắm chỉ được dùng Jev để **chặn / nhắc / xếp ưu tiên / nâng tier**; không bao giờ để
   mở gate, hạ tier, bỏ check, hay điền `verified_by`. Viết thành tính chất của kiểu dữ liệu như `QualityBar`
   (ADR-0043 §2), không phải lời dặn trong prompt.
5. **Fail-open bắt buộc.** Jev chết/chậm/sai khoá ⇒ hệ chạy như không có nó (jev-gateway và bài pentest cùng kết
   luận). Timeout ngắn (jev-gateway dùng 4 s), không bao giờ `TransientError` hoãn event vì Jev.
6. **Hiệu chuẩn trước, ngưỡng sau.** ECE 0,246 nghĩa là 0,9 của Jev chưa chắc là 90 %. Hub **có sẵn nhãn**: mọi
   quyết định gate của người, mọi `escalate` của supervisor, mọi lần `_stagnant` cắt đều nằm trong `audit-log`. Đo
   ECE trên chính dữ liệu đó, bằng tiếng Việt, trước khi đặt một con số ngưỡng nào vào config.
7. **Kiến trúc ⇒ ADR trước** (luật bắt buộc 2). Lựa chọn thay thế phải nêu trong ADR: AgentJev-0.6B (Apache-2.0,
   chạy local, hợp "self-hosted" hơn, nhưng cửa sổ chỉ 2 048 token và cần GPU để nhanh) và Laya (mã mở, ECE tốt hơn
   sau hiệu chuẩn).

---

## 4. Đề xuất

**Không tích hợp bây giờ.** Hai việc đang mở (R1 ghi `num_turns`/cache vào bản ghi eval; keeper canary BT8) không
cần Jev, và tích hợp trước khi có số đo tiếng Việt là tin lời quảng cáo (luật cấm 8).

**Làm một thí nghiệm bóng, chỉ đọc, ~2 giờ + vài USD**, khi có khoá (TypeSafe hoặc OpenRouter `typesafe/jev-1.13`):

1. Script ở scratchpad (không vào repo) `bus.replay()` một `company.sqlite` thật: với mỗi `gate.request` đã có
   `gate.decide` của người, hỏi Jev `score` mức khẩn + `noul` "chạm auth/payment/migration"; so với thứ tự người
   đã duyệt và nhãn G6. Đo accuracy và ECE.
2. Với mỗi ticket từng bị `_stagnant` cắt, hỏi `noul` "có tiến bộ" trên từng cửa sổ 5 lời gọi của `tools_trace`;
   đo Jev bắt được **sớm hơn** hash bao nhiêu lượt, và dương tính giả trên ticket không bị cắt.
3. Chạy 23 câu thử của guard (K3.4, nhật ký phiên) + mẫu yêu cầu khách tiếng Việt qua `noul` injection; so với regex.

Ngưỡng đi tiếp: A đúng thứ tự ≥ 80 % và ECE < 0,15 sau hiệu chuẩn; B bắt sớm ≥ 2 lượt với dương tính giả < 5 %.
Đạt thì viết ADR gốc cho `DecisionClient` trong `xagents_core` (fake + recordings, chiều chặn, fail-open), cắm A
trước (console, không chạm dữ liệu khách), B sau. C chỉ sau khi có khách ký cho phép hoặc chuyển sang model local.
Không đạt thì ghi kết quả vào báo cáo này và đóng chủ đề.

---

## Nguồn

- TypeSafe: https://typesafe.ai · https://typesafe.ai/blog/introducing-system-one-models-and-jev ·
  https://docs.typesafe.ai (quickstart, `/confidence`, llms.txt)
- Skill chính thức: https://github.com/jev-ai/jev-agent-skill
- Gateway + benchmark coding agent: https://github.com/vinilana/jev-gateway · https://github.com/vinilana/jev-eval-agent
- Model mở so sánh: https://github.com/malevrigns/agent-jev
- Danh mục công cụ: https://github.com/v-modal/awesome-jev-tools
- Bài học thuật về hiệu chuẩn: https://arxiv.org/html/2609.28940v1
- Phân tích độc lập: https://flaviocopes.com/jev/ · https://www.datacamp.com/blog/system-one-models-jev ·
  https://www.eesel.ai/blog/typesafe-jev-review (đối thủ, không chạy thử)
- Giá/cửa sổ trên OpenRouter: https://openrouter.ai/models/typesafe/jev-1.13
