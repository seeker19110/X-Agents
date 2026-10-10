# Human gate — checklist

Nguyên tắc: separation of duties, four-eyes cho production, timeout 24h (supervisor nhắc 12h), quá hạn KHÔNG tự đi tiếp.

Mỗi gate dưới đây tách làm hai phần:
- **Code gửi kèm** — đúng các khoá trong `GateRequest(...).checklist` mà `src/company/orchestrator.py` và
  `src/company/delivery.py` sinh ra; đây là thứ hiện lên trong `gate_cli list`. Code dựng danh sách và điều kiện
  mở gate, còn việc từng mục có đạt hay không thì người duyệt xác nhận.
- **Người tự kiểm thêm** — không có trong payload, không có tên khoá; người duyệt phải tự đọc và trả lời. Có trợ lý
  chỉ đọc cho nửa này: `make gate-brief SUBJECT=<subject>` (hồ sơ bằng chứng `ok|gap|unknown`, `src/company/gate_brief.py`)
  và subagent `.claude/agents/sc-gate-<kind>.md` sinh từ chính file này (`make subagents`). Sửa một mục "Người tự kiểm thêm"
  thì phải khai nguồn bằng chứng cho nó trong `src/company/gate_checklists.py` rồi `make subagents` — parser gãy nếu thiếu.

**Khi phải chọn giữa nhiều phương án kỹ thuật hợp lệ** (stack, thư viện, version, kiến trúc) mà bằng chứng không
chỉ rõ một hướng duy nhất — trong bất kỳ mục nào ở trên, "Code gửi kèm" hay "Người tự kiểm thêm" — người duyệt
nghiêng về phương án **chất lượng/độ bền cao nhất** (đúng chuẩn ngành, ít nợ kỹ thuật nhất) và **phiên bản/nền
tảng mới nhất đang có tại thời điểm duyệt, với điều kiện đã phát hành ≥ 3 tháng** (đủ ổn định, không phải bản
vừa ra chưa kiểm chứng). Đây là tiêu chí phá thế bế tắc khi bằng chứng mơ hồ, không thay cho việc đọc bằng
chứng — mục nào có bằng chứng rõ vẫn quyết theo bằng chứng đó. Quyết định vẫn phải ghi root_cause/decision/hint
đầy đủ như mọi lượt duyệt khác.

`GateKind` hiện có đúng bốn giá trị: `spec`, `release`, `acceptance`, `escalation` (`src/company/gates.py`).
Hai gate CÔNG ĐOẠN là `spec` và `release`; `acceptance` là chữ ký của khách, `escalation` là đường bất thường.
ADR-0037 bỏ gate `plan`: mọi khoá của nó nay là `problems` của `_check_plan` (code chặn trước khi giao ticket),
hai mục người-tự-kiểm của nó dời xuống Gate 2.
Số gate vì thế đổi: **Gate 3 cũ (release) = Gate 2 nay**, **Gate 4 cũ = gate nghiệm thu (bỏ số)**. Chú thích
trong mã và system prompt của agent còn dùng số cũ cho tới khi PR-5x của ADR-0037 viết lại prompt — `kind`
(`spec`/`release`/`acceptance`/`escalation`) mới là thứ code dùng, số thứ tự chỉ để người đọc.

## Gate 1 — Duyệt spec (kind `spec`, subject `SPEC-<project>`)
Code gửi kèm: `prd`, `acceptance-criteria`, `ux-flow`, `risks`
- [ ] `prd` — PRD tồn tại, mọi yêu cầu truy vết được về nguồn
- [ ] `acceptance-criteria` — 100% Must có Gherkin
- [ ] `ux-flow` — 100% story Must có UX flow trong `design`, đủ 4 trạng thái
- [ ] `risks` — rủi ro High có mitigation và owner

Người tự kiểm thêm:
- [ ] NFR có số đo
- [ ] Out-of-scope rõ
- [ ] PII đã phân loại; DPIA có nếu cần
- [ ] Câu hỏi mở chỉ còn assumption đã ghi nhận
- [ ] Có runtime chạy được: `kind` khai rõ; ứng dụng có lệnh khởi động, cổng, đường health và phụ thuộc ngoài

Ghi chú: `spec_runtime_gap` trong `src/company/orchestrator.py` đã chặn trước khi gate mở — spec `kind=application`
không có `runtime` hợp lệ thì KHÔNG có gate này, spec-writer nhận lại spec với lý do (ADR-0031). Mục tự kiểm ở trên là
lớp thứ hai: lệnh có đúng là lệnh của sản phẩm này không, phụ thuộc ngoài có ghi đủ không.

Kết quả: approve / request_changes(lý do) / reject

## Gate 2 — Duyệt release production (kind `release`, subject `<release_id>`)
Điều kiện mở: delivery-lead chỉ xin gate khi đã có review `qa` pass (cộng `security` pass nếu release chứa
ticket có `risk_tags`). Threat model (`review-results` key `SPEC-<project>`, không `block`) và `architecture` trên
blackboard đã được `_threat_model` và `_check_plan` bảo đảm từ trước khi ticket được giao (ADR-0037) — hai khoá
dưới đây là lớp thứ hai để người ký NHÌN THẤY chúng, không phải lớp duy nhất.

Code gửi kèm: `tests`, `scan`, `regression-staging`, `smoke`, `perf`, `a11y`, `runbook`, `rollback`, `threat-model`, `architecture`
- [ ] `tests` — mọi test pass
- [ ] `scan` — SAST, SCA, DAST, license pass; SBOM có; artifact ký
- [ ] `regression-staging` — QA hồi quy trên staging pass (`review-results` ticket_id=release_id); `evidence.run` do orchestrator tự chạy trên worktree RC (ADR-0029): `ok=true` kèm mã HTTP, hoặc `unverified` kèm lý do — verdict pass mà smoke fail đã bị code hạ fail
- [ ] `smoke` — `release-events{staging}.smoke.ok=true` do orchestrator tự chạy (ADR-0029); `unverified` nghĩa là spec chưa khai `runtime` — hỏi "chạy cho tôi xem" trước khi ký
- [ ] `perf` — perf so NFR trên staging pass
- [ ] `a11y` — a11y (axe + thủ công) trên staging pass
- [ ] `runbook` — runbook đã thử
- [ ] `rollback` — rollback đã thử; mỗi PR trong release có rollback plan
- [ ] `threat-model` — threat model v1 có; High/Critical có mitigation hoặc ADR có người ký
- [ ] `architecture` — C4 L1–L2 và ADR trên blackboard

Người tự kiểm thêm:
- [ ] Tiến trình đang chạy giao hàng được (`--deliver`)
- [ ] Dashboard + alert (có runbook) cho dịch vụ/tính năng mới
- [ ] Changelog, docs, NOTICE cập nhật
- [ ] Error budget không âm
- [ ] Người duyệt ≠ người tạo release
- [ ] Ước lượng có cơ sở (tham chiếu `knowledge` hoặc PERT)
- [ ] Ngân sách token cho dự án được đặt; tổng estimate ≤ ngân sách

Kết quả: approve / hold / rollback

## Gate nghiệm thu của khách (kind `acceptance`, subject = `UAT-<release_id>`)
Khi `release-events` báo đã deploy production, orchestrator mở gate `acceptance`. Đây là gate thật: có trong
`gate_cli`, có hạn 24h, nhắc ở 12h, quá hạn thì supervisor escalate. `ops` (pha `account`) tổ chức UAT; khách ký và
kết quả vào topic `acceptance-results` (key = `release_id`), chính chữ ký đó đóng gate — `signed_by` phải khác
`ops` (four-eyes), nên công ty không tự ký thay khách. `verdict = conditional` đóng gate ở dạng
`request_changes` và phần còn lại đi qua `change-requests`; ticket chỉ `closed` khi khách accepted.

Code gửi kèm: `uat-script`, `acceptance-criteria`, `known-issues`, `signed_by`
- [ ] `uat-script` — kịch bản UAT map 1-1 với Must requirement trong PRD đã duyệt; không tiêu chí mới
- [ ] `acceptance-criteria` — tiêu chí nghiệm thu trong SOW đã được đối chiếu từng mục
- [ ] `known-issues` — lỗi đã biết được nêu trước khi ký, không giấu
- [ ] `signed_by` — người ký là người của khách (code từ chối nếu trùng `ops`)

Người tự kiểm thêm:
- [ ] Chạy trên bản production (hoặc staging nếu hợp đồng quy định) với dữ liệu khách chấp thuận
- [ ] Finding truy vết về requirement_id; yêu cầu ngoài spec đi vào `change-requests`, không vào biên bản
- [ ] Sản phẩm khởi động được và trả lời một request thật — `gate_brief` tự chạy theo `runtime` của spec (ADR-0029), khách ký trên thứ đã chạy chứ không trên lời khai `deployed`
- [ ] Khách đã xem bản giao trong PR thật trên GitHub (`--deliver-pr`, ADR-0038): PR nhánh release → nhánh của khách do orchestrator mở, không merge — review bằng UI quen thuộc rồi mới ký
- [ ] Mỗi file/khoá cấu hình/trường mới mà bản giao sinh ra có ít nhất một nơi đọc trong mã — trỏ dòng (sự cố QLKH: `runtime.yaml` sinh ra mà không ai đọc)
- [ ] Không khả năng nào README/spec đã hứa đứng sau stub (hàm trả giá trị cố định, thân `TODO`/`NotImplementedError`, module không ai gọi)

Kết quả (ghi vào `acceptance-results`): accepted / conditional(danh sách còn lại + hạn) / rejected(lý do)

## Gate bất thường (kind `escalation`, subject = ticket_id)
Orchestrator mở gate khi ticket `blocked` (hết retry) hoặc supervisor `escalate` (cùng lỗi lặp, im lặng quá timeout).

Code gửi kèm: `root_cause`, `decision:reopen|close`, `hint`
- [ ] `root_cause` — nguyên nhân đã rõ
- [ ] `decision:reopen|close` — chọn mở lại hay đóng
- [ ] `hint` — đủ cụ thể để agent làm khác lần trước

Người tự kiểm thêm:
- [ ] Ngân sách còn

`gate_cli approve <ticket> --reason "<hint>"` = mở lại ticket với hint, retry về 0, resume; `reject` = đóng ticket.

### Escalation cấp dự án (subject = project_id)
Agent của chuỗi nghiên cứu (intake, researcher, synthesizer, risk, clarifier, spec-writer) lỗi thì dự án không có bước
kế tiếp và không có ticket nào để retry. Orchestrator ghi `project.stalled`, supervisor `escalate` (mọi event của dự án
bị hoãn), `status.stalled` nêu agent + lỗi, và mở gate này với checklist `agent_error`, `decision:retry|close`.
`approve` = chạy lại đúng event đã lỗi (resume dự án); `reject` = đóng dự án (`project.closed`). Lỗi lần nữa → gate mới.

### Escalation nợ kiến trúc treo (subject = project_id, ADR-0032)
Cùng mã nợ (`DEF-xx`, `SD-xx`, `debt:<mã>`) trong finding của review-results nhắc ≥ N review liên tiếp của cùng nguồn
(N = `llm.yaml debt_reviews`, mặc định 3) → supervisor đếm từ bus, orchestrator mở gate này với checklist
`debt:<mã>×<n> liên tiếp (<nguồn>; <ticket…>)` cho từng mã, `decision:adr|waive`, `hint:cần ticket ADR + người ký`;
audit `debt.escalated` mang cả bảng (`status.architecture_debt`). Dự án KHÔNG bị pause. `approve` = đã có ticket ADR
và người ký; `reject` = chấp nhận treo — cả hai chỉ ghi `debt.decided`. Nợ nhắc tiếp tới bội số kế của N → gate mới.

## Chỉ người được ký
- Chấp nhận rủi ro bảo mật (threat accepted)
- Ngoại lệ license (copyleft)
- Chuyển dữ liệu cá nhân ra nước ngoài
- Bật A/B test chạm PII
