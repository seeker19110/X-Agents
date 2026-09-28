# Ngôn ngữ của repo — thuật ngữ, nghĩa ở đây, và cách gọi phải tránh

Một phiên agent mới đọc "gate", "guard", "lời khai", "K3.4" và đoán — đoán sai im lặng. File này tồn tại vì
nhật ký phiên 2026-09-07 ghi **hai** lần nhầm trong một ngày do cùng một chữ mang hai nghĩa (K1.x của hai file đặc
tả; một bảng đối chiếu ghi tên hàm và cờ không tồn tại). Khuôn mượn từ `CONTEXT.md` của `neo4j-labs/agent-memory`
(ADR-0004): mỗi thuật ngữ một nghĩa, và **một cách gọi phải tránh** vì nó đã gây nhầm hoặc sẽ gây nhầm.

Thêm mục mới khi một chữ vừa gây nhầm thật (có dòng nhật ký phiên chỉ vào), không thêm để cho đủ.

| Thuật ngữ | Nghĩa ở repo này | Tránh |
|---|---|---|
| **Lời khai** / **bằng chứng** | Lời khai = trường do model điền ("đã test", "đã deploy"). Bằng chứng = trường do **code** điền: `local_checks.verified_by=workspace`, `release-events.smoke.verified_by=orchestrator` (`ARCHITECTURE.md` §"Ranh giới tin cậy"). Gate chỉ ký trên bằng chứng. | "Tests pass" mà không có output lệnh vừa chạy trong chính lượt này (`AGENTS.md` luật cấm 8). |
| **Gate** (human gate) | Điểm dừng để **người** ký: company `spec` → `release` → `acceptance` (+ `escalation`); keeper `patch` (orchestrator tự xin; `release`/`escalation` chỉ mở tay qua `keeper.cli gate`). Hạn 24 h, nhắc 12 h, four-eyes. | Gọi kiểm tra bằng code là "gate" — đó là **guard** hoặc kiểm FSM (`_check_plan`). |
| **Guard** | Code chặn trước khi model chạy: injection + ACL topic (`guard.py`, ADR-0012). Không có người trong vòng. | Dùng "guard" cho việc người duyệt. |
| **Blackboard** / **namespace** / `shared-context` | Tri thức chung đi qua topic `shared-context`; mỗi namespace **một chủ** (`namespace_owners`), giữ **bản mới nhất** theo `(project_id, namespace)`, toàn văn (ADR-0012), phân vùng dự án (ADR-0018). `knowledge` là namespace toàn công ty duy nhất. | "Ghi tay blackboard" để đổi hành vi agent — phải đi qua đúng vai (`CLAUDE.md` §"Khi vận hành"). Gọi `knowledge` là "bộ nhớ agent" — nó chỉ giữ **một** bản mới nhất (ADR-0004). |
| **Chân trời** 1 / 2 / 3 | Ba mốc của `docs/archive/DANH-GIA-VA-TAM-NHIN-2026-09.md` §6: 1 = một tháng (chứng minh Q1/Q2 bằng một dự án và một video thật); 2 = ba tháng (lõi chung + sandbox); 3 = sau đó (xoá shim `company.X → xagents_core.X`). | "Sprint", "phase" — repo không dùng hai chữ đó cho lộ trình. |
| **K1–K9** và **K3.x** | Chín epic của kịch bản B (`docs/DAC-TA-KICH-BAN-B.md`). **Hai file đánh số K<n>.x khác nhau**: `DAC-TA-KICH-BAN-B.md` đánh theo *tiêu chí nghiệm thu*, `DAC-TA-TRIEN-KHAI-KICH-BAN-B.md` và tiêu đề PR đánh theo *PR-theo-PR*. K3.0–K3.7 của ADR-0001: khung → context → tools → llm+routing → guard → events+bus → registry+blackboard+runner+evals → gates+supervisor. | Viết "K1.4 xong" mà không nói theo file nào (nhật ký 2026-09-07 mắc đúng lỗi này). Nói "bước 7" khi ý là blackboard — blackboard là **K3.6**. |
| **Bản dẫn xuất** | File sinh từ nguồn khác: `.claude/agents/sc-*.md` (từ `agents/`, `skills/`, `gates/checklists.md` qua `make subagents`), `tests/golden/` (`make golden`). | Sửa tay bản dẫn xuất (luật cấm 5). Diff tay rồi commit — CI `golden-check`/`subagents-check` đỏ. |
| **Bảy bước** (`CONTRIBUTING.md` §3) | Checklist bắt buộc khi sửa `agents/`/`skills/`: tăng `version` → `make golden` → `make eval-record` (model thật) → `make assetscan` → `make assetbudget` → `make subagents` → commit cả golden + recordings + `.claude/agents/`. | "Chỉ sửa một chữ trong prompt nên bỏ eval-record" — bỏ một bước là CI đỏ có chủ đích. Nhầm với **bảy bước K3.x** ở trên. |
| **Đo hai chiều** | Tắt bản sửa → test đỏ; bật lại → xanh; ghi cả hai vào commit message (luật bắt buộc 4). | Test chỉ xanh một chiều ("tôi thêm test và nó pass"). |
| **`once`** + **thế hệ** | Khoá chống làm lại (`o.once`, `_remember`). Khoá phải mang **giai đoạn/thế hệ** (`no-test-author:{tid}` theo retry), không chỉ danh tính — `TRAPS.md` §1 khuôn 3. | Khoá theo danh tính (`lesson:{tid}`) cho việc **có thể** lặp hợp lệ. Danh sách miễn ở `test_orch_khuon_loi.py::KHOA_MIEN` có lý do từng mục; đừng kế thừa mà không đọc. |
| **Worktree mỗi phiên** | Mỗi phiên agent một `git worktree`, không dùng chung clone (`docs/QUY-TRINH-GIT.md` §2b). Thấy nhánh mình không tạo → dừng. | "Cùng thư mục nhưng khác nhánh" — vẫn là một clone. |
| **Takeover** | Lệnh `orchestrator takeover` (`orch/cli.py:93`): người đã sửa tay trong worktree của ticket → chạy lint/test, commit, publish PR **dưới tên người**. Thứ tự: **commit + takeover trước, duyệt gate sau** — duyệt trước là bị reset (`CLAUDE.md` §"Khi vận hành"). | Duyệt gate rồi mới sửa tay. |
| **Gói việc** (task pack) | Tờ giấy 7 mục đặt lên bàn một phiên agent (`docs/TASK-PACK.md`). Mục để trống là mục agent tự đoán. | Dán yêu cầu một dòng rồi gọi đó là gói việc. |
| **Khuôn lỗi** | Năm họ lỗi lặp lại của `TRAPS.md` §1 (lỗi im lặng, state không sống sót restart, khoá không có thế hệ, …). Sửa một lỗi thì rà cả họ (luật bắt buộc 5). | Gọi một lỗi thuộc khuôn đã có tên là "bug lẻ" và sửa đúng một chỗ. |
| **Provider `fake`** | Provider LLM giả để test chạy offline; cùng bản ghi eval (`evals/recordings`) đủ chạy toàn bộ CI không tốn tiền (luật cấm 4). | "Test nhanh với model thật" trong `tests/`. |
| **Scope PR** | Một từ chữ thường trong ngoặc của tiêu đề PR: `fix(company)`. | `fix(company,console)` — bị chặn. |
| **Tự kiểm** | Nghi thức đo lại mọi con số trong tài liệu gốc trên gói đã cài, kết quả `docs/reports/<ngày>-tu-kiem.md` (ADR-0003, `docs/TASK-PACK.md` §"Gói việc thường trực"). Số lệch → sửa tài liệu, không sửa phép đo. | "README nói vậy nên là vậy." |
| **Xong** | Có output lệnh vừa chạy **trong chính lượt này** (`CLAUDE.md` mục 5). | "Đã xong, chỉ cần chạy test là được." |
