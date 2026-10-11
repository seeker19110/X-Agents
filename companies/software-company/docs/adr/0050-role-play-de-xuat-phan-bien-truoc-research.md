# ADR-0050: Một phiên role-play đề xuất/phản biện có hạn mức chạy TRƯỚC pha `research`, kết quả là dữ liệu `debate`

Ngày: 2026-10-11 · Trạng thái: được chấp nhận · Nguồn ý tưởng: `RolePlayingWorker` của CAMEL-AI (đối chiếu ở
`docs/thi-hanh/cm1.md`) · Giữ nguyên ADR-0006 (bốn mảng research), ADR-0037 (một `product` bốn pha), ADR-0010
(ranh giới tool), luật "model quyết định – code hành động".

## Bối cảnh

Đo trên `main@db96a3a` (#425):

| # | Hiện trạng | Chỗ |
|---|---|---|
| 1 | Pha `research` là **một** lượt model: một prompt, bốn mục đầu ra, không có góc nhìn thứ hai nào trước khi PRD được viết | `orch/routes.py:164-165` (một `Route`), `agents/research/product.md` §"Pha research" |
| 2 | Phản biện duy nhất trong chuỗi nghiên cứu là mục `risks` do CHÍNH pha `spec` tự rà trên draft của mình (lượt `risk` riêng đã bỏ ở PR-5e) | `orch/routes.py:157-162` chú thích PR-5e; `product.md` §"Pha spec" |
| 3 | Câu hỏi cho khách sinh ở pha `intake` TRƯỚC khi có hướng giải nào — hỏi về đề bài, không hỏi về chỗ một hướng sẽ gãy | `product.md` §"Pha intake" ("CHỈ hỏi thứ đang chặn") |
| 4 | Sự cố: PRD cắt mất tiêu chí nghiệm thu (ADR-0049) và ticket quay 7–8 vòng vì thiếu quyết định sớm (`TRAPS.md`, QLKH-004/010) — phần lớn là chỗ "không ai hỏi ngược" trước khi viết spec | `docs/sessions/2026-09-22.md`, `TRAPS.md:49` |
| 5 | CAMEL `RolePlayingWorker`: hai agent `assistant`/`user` thay phiên, `chat_turn_limit`, chỉ vai `user` kết thúc (`TASK_DONE`); tài liệu Workforce **không** có trần token hay chi phí | `docs.camel-ai.org/key_modules/workforce` (đọc 2026-10-11) |

## Quyết định

1. **`company/roleplay.py`**: `RolePlay(client, turn_limit, token_budget, model_tier="standard")` chạy hai vai thay
   phiên — `proposer` đưa hướng giải, `critic` tìm điều kiện gãy theo đúng bốn mảng ADR-0006 — cho tới khi **vai
   phản biện** đặt `done` (vai đề xuất đặt `done` bị bỏ qua, như `TASK_DONE` chỉ của `user` bên CAMEL), hết
   `turn_limit` lượt, hoặc chạm `token_budget`. Hai hàng rào là **hạn mức cứng của code**, không phải lời dặn trong
   prompt — đúng chỗ Workforce của CAMEL để trống.
2. **Hai vai là tài sản prompt**: `roleplay/proposer.md`, `roleplay/critic.md` có front matter `version`; thư mục vào
   `assetscan.ASSET_DIRS` (quét injection/ký tự vô hình như `agents/`). Chúng KHÔNG phải agent: không `reads/writes`,
   không namespace, không route, không `sc-*`; không đi bảy bước `CONTRIBUTING.md` §3 vì không có bản ghi eval nào
   phụ thuộc vào chúng (phiên không chạy trong eval của `product`).
3. **Nối một chỗ**: route research (`routes.py`) nhận `enrich=_with_debate`. Enrich chạy phiên, ghi **một audit
   `research.debate`** (transcript đầy đủ, token, tiền, `source_event`) rồi đưa `debate` = {proposals, objections,
   open_questions, turns, stopped_by, tokens} vào payload của lượt research. Xử lý lại cùng event (restart, `_recall`)
   đọc audit cũ từ bus, không tốn lượt model (khuôn 2 `TRAPS.md`: trạng thái dựng lại từ bus).
4. **Lỗi của phiên không chặn research**: `LLMError` → audit `research.debate_failed` + `debate_error` trong payload;
   `TransientError` lan ra để `_call` hoãn event như mọi lượt.
5. **Mặc định TẮT** (`Orchestrator(roleplay=None)`), bật bằng `--debate N` hoặc `COMPANY_DEBATE_TURNS=N`
   (`COMPANY_DEBATE_BUDGET` đổi trần token, mặc định 60 000) — cùng lý do với `--test-author` (ADR-0028): thêm lượt
   model phải là lựa chọn của người vận hành.
6. **Cố ý không làm trong PR này**: không sửa `agents/research/product.md` để dặn pha research đọc `debate` (đổi
   prompt là `make eval-record` model thật — chờ người, ghi ở `docs/thi-hanh/cm1.md`); không ghi `debate` lên
   blackboard (chưa có vai nào ngoài research cần); không cho vai phản biện tool đọc repo (phiên là brainstorm,
   bằng chứng là việc của pha research có tool).

## Phương án đã loại

- **Thêm một pha `debate` cho `product`** (route + `phases:` trong front matter). Đúng khuôn ADR-0037 nhưng đổi
  front matter là đổi prompt → bảy bước + eval-record, và một pha chỉ có một vai thì không phải role-play. Để lại
  nếu sau khi đo thấy `debate` đáng thành pha chính thức.
- **Chạy role-play BÊN TRONG lượt research bằng tool** (`debate` như một tool của research toolbox). Model research
  tự quyết có gọi hay không → không đo được chi phí trước, và vòng tool của research đã có 25 lượt trần
  (`max_turns`); lồng thêm là hai hạn mức chồng nhau.
- **Dùng `camel-ai` làm thư viện**. Kéo 17 nhóm phụ thuộc, client model riêng (mất `RoutingClient`, pricing, span
  ADR gốc 0009), và API 0.2.x chưa ổn định; cái cần mượn là ~80 dòng vòng lặp hai vai.

## Hệ quả

- Mỗi dự án bật `--debate N` tốn thêm ≤ N lượt tier `standard` một lần (pha research chạy một lần/dự án); `report`
  thấy ở actor `roleplay`, action `research.debate`.
- `Orchestrator.__init__` thêm `roleplay`; `orch/cli.py` thêm `--debate`; `assetscan` quét thêm thư mục `roleplay/`.
- Chờ người: dặn pha research dùng `debate` trong `product.md` (+ eval-record); đo một dự án thật với `--debate 4`
  so với không bật (số câu hỏi làm rõ, số vòng ticket) trước khi cân nhắc bật mặc định.
- Nhận biết nếu sai: audit `research.debate` có `stopped_by=turn_limit` ở hầu hết dự án (hai vai không hội tụ) hoặc
  `objections` trùng `risks` của pha spec ≥ 80 % → bỏ, đừng giữ một lượt model không thêm thông tin.
