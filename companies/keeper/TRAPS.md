# TRAPS.md — bẫy riêng của keeper

Bốn khuôn chung ở `../../TRAPS.md` §1 áp nguyên vẹn (cùng kiến trúc bus/gate/runner với `xagents_core`). Dưới
đây là bẫy riêng của việc "công ty tự vá chính repo đang chứa nó" — mỗi dòng có test hoặc đoạn code chốt chặn.

## Bẫy đã vá

| Bẫy | Đã xảy ra | Chốt chặn / lần sau |
|---|---|---|
| `FORBIDDEN_ARGS` gốc có lỗ ghi ẩn | `gh api ... -f x=y` là POST ẩn, không cần `-X` — không nằm trong danh sách cờ ghi ban đầu (BT2) | Thêm 5 cờ ghi vào `github.py`: `-f`, `-F`, `--field`, `--raw-field`, `--input` |
| `FORBIDDEN_PATHS` chỉ chặn `.github/rulesets/` | Lỗ hổng cho phép patch ghi đè `.github/workflows/ci.yml` — vô hiệu hoá cổng CI bằng chính "bản vá tự động" (BT5) | Chặn cả `.git/` và `.github/` (`patcher.py:FORBIDDEN_PATHS`) |
| Đặc tả cũ nói `ledger.py` "dùng lại `debt_due` của company" | Sai địa chỉ (nợ kiến trúc thật nằm ở lõi `xagents_core/supervisor.py`) và sai bản chất (đếm streak lỗi lặp, không phải hạn theo ngày) (BT4) | `DebtEntry(due_at=...)` là cơ chế MỚI của keeper, không tái dùng khái niệm khác tên giống nhau |
| Đặc tả BT7 sai ba câu về gate | `SqliteBus` (sai tên, đúng là `SQLiteBus`); tưởng `HumanGate` có `approve()/reject()` (chỉ có `decide()`); tưởng "approve là reopen" | Đo lại mã thật trước khi viết đặc tả — ba câu sai đã sửa trong `gates.py` |
| Khoá chống trùng không mang "thế hệ" | K1.7: `once="no-test-author:{tid}"` không phân biệt lần ticket này SỐNG LẠI sau khi đã đóng — nuốt mất lần hợp lệ thứ hai | `triage.py` khoá theo "thế hệ" = số vòng đời ticket đã ĐÓNG, không chỉ theo `tid` |
| Phép đo drift báo giả cho PR merge cũ | (c) trong `drift.py` báo giả cho PR đã merge TRƯỚC KHI luật `AGENTS.md` §10 có hiệu lực — luật mới áp ngược cho lịch sử cũ | Chặn bằng mốc ngày HẰNG SỐ, không lọc theo danh sách PR (danh sách sẽ phình vô hạn) |
| Một đường dẫn repo, hai việc lệch nhau | 2026-09-28: `drift --repo`, `run --root`, `publish --repo` đưa cùng một đường dẫn cho `git` (tự dò lên gốc) và cho phép ghép đường dẫn file (không dò). Trỏ vào thư mục con thì `drift` báo 199 tín hiệu giả trên chính repo (`CHANGELOG.md` đọc rỗng, `git log` vẫn thấy mọi PR), `run` ghi `CHANGELOG.md` vào thư mục con, còn `publish` dựng worktree ở `<thư mục con>.parent` — ngay TRONG checkout chung khi nhánh ticket chưa có (câu hỏi I1 ở cuối file: có) | `worktree.repo_root()` quy về `git rev-parse --show-toplevel` một lần ở cửa vào CLI; lệnh mới nhận đường dẫn repo đi qua nó. An toàn hôm nay: `watch` (chỉ làm cwd cho `gh`, tự dò) — nối `publish` vào `watch` thì `_watch` phải quy về gốc trước. Tiềm ẩn, chưa có chỗ gọi: `scout.scan` ghép `repo / "uv.lock"`, `health.scan` `rglob("coverage.xml")` dưới `repo` — nối vào `tick()` thì truyền gốc |

## Bẫy vận hành riêng của keeper

| Bẫy | Vì sao | Chốt chặn |
|---|---|---|
| `open_pr()` và `publish()` tưởng là một | `orchestrator.open_pr()` (BT7) chỉ soạn `release-notes` + ghi `pr.intent` — Ý ĐỊNH. `orchestrator.publish()` (BT8, `publish.py`) mới thật sự `git push` + `gh pr create`, và phải gọi RIÊNG (CLI `keeper publish <ticket_id>`) sau khi patch đã commit vào worktree. Đọc `pr.intent` trong audit-log rồi tưởng PR đã lên GitHub là sai — kiểm `pr.created` hoặc `gh pr list` | Đọc action `pr.created` (không phải `pr.intent`) để biết PR đã thật; `publish()` không tự chạy trong `watch` — chưa nối scout→patch→publish thành một chuỗi tự động |
| Tưởng canary BT8 đã qua vì code chạy được | Điều kiện qua canary (I7, `docs/DAC-TA-KEEPER.md` §10) là MỘT CHU KỲ THẬT: keeper tự mở đúng một PR bảo trì có bằng chứng đo hai chiều, và PR đó **merge bởi người** (I1 cấm keeper tự merge). Code chạy được ≠ canary đã qua | Cần `gh auth login` trên máy thật + một PR merge thật trước khi coi BT8 xong |
| `blackboard.py` của keeper tưởng đang chạy trong sản xuất | Lớp chỉ subclass 2 dòng `xagents_core.blackboard.Blackboard` — nhưng KHÔNG agent nào của keeper khai `context_namespace_write` (cả 10 đều null), nên đường ghi blackboard không chạy thật. Lớp tồn tại vì `EvalSuite.run_eval` cần một blackboard cho mọi ca | Đừng debug "vì sao blackboard keeper không có dữ liệu" — nó chưa từng được thiết kế để có |

## Cách rà khi có lỗi mới

Cùng khuôn 4 ở `../../TRAPS.md` §1, thêm câu riêng: *"lỗi này có làm keeper ghi/xoá ngoài worktree riêng của
chính nó không?"* (I1) — nếu có, đây là lỗ hổng nghiêm trọng nhất có thể có ở một công ty tự vá chính repo chứa
nó, ưu tiên vá trước mọi thứ khác.
