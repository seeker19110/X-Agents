# keeper — luật riêng (bổ sung `../../AGENTS.md`, không thay)

Package `keeper`. Công ty bảo trì tự vận hành: tín hiệu (drift, dependency, health) → ticket → patch có bằng
chứng đo hai chiều → PR; khách hàng số 0 là chính repo X-Agents này. Kế thừa cơ chế của `platform/xagents-core`
(bus, gate, runner) — không tự fork. Đặc tả đầy đủ + bảy bất biến (I1–I7): `docs/DAC-TA-KEEPER.md`.

## Chạy ở đâu

```bash
scripts/dev-task.sh gate keeper             # ở GỐC repo: ruff + mypy + pytest --cov, khớp đúng ci.yml
cd companies/keeper
uv run python -m keeper.cli run --tickets <file.json> --root <worktree phụ> --dry-run   # chỉ in kế hoạch
uv run python -m keeper.cli watch --db <path> --repo <path> --interval N
uv run python -m keeper.cli drift --repo ../..                   # thuần cục bộ, cùng phép kiểm job CI drift-check
uv run python -m keeper.cli publish --db <path> --repo <path> <ticket_id>   # push + gh pr create THẬT (BT8)
```

Package không có `__main__.py`: mọi lệnh đi qua `keeper.cli` (hoặc `keeper.evals` cho eval).

**`watch` chưa tự động gọi `publish`** — vòng lặp mới nối `triage`+ghi ý định PR (`pr.intent`); scout chưa
nối vào `tick()`, patch cần `keeper run`/người commit tay. `publish` là bước NGƯỜI/script gọi sau khi patch đã
commit vào worktree của ticket (`open_worktree(ticket_id, repo)`), biến ý định thành PR thật.

## TDD ở package này

`../../AGENTS.md` luật bắt buộc 4 áp nguyên vẹn. `branch = true` **đã bật** (một trong hai package đầu tiên,
cùng `xagents-core`) — nhánh chưa test là CI đỏ ngay, không phải "để sau". Sửa `agents/` → 7 bước
`../../CONTRIBUTING.md` §3.

## Bảy bất biến (I1–I7, `docs/DAC-TA-KEEPER.md` §0) — không được phá

1. **I1 — không quyền ghi ngoài worktree riêng, commit, và mở PR.** `github.py` chỉ có hàm ĐỌC;
   `GitHubReader._run()` ném `GitHubWriteAttempt` khi argv chứa cờ ghi (`-f`, `-F`, `--field`, `--raw-field`,
   `--input`, và mọi biến thể POST ẩn — bảng gốc từng thiếu 5 cờ này, đã vá). Quyền ghi thứ ba (mở PR) sống
   TÁCH RIÊNG ở `publish.py` — `push_branch()`/`create_pr()` — để không lẫn vào các hàm đọc của `github.py`.
2. **I2 — bằng chứng đo hai chiều bắt buộc trước khi rời pha quality.** `evidence.require_two_way()` ném
   `EvidenceError` nếu `before.exit_code == 0` (chưa từng đỏ) hoặc `after != 0` (chưa xanh).
3. **I3 — đúng một PR bảo trì mở tại một thời điểm.** `budget.can_open_pr()` LUÔN hỏi GitHub thật, không đếm
   trong RAM (RAM mất khi mở lại tiến trình, đúng khuôn "chống trùng sống trong bộ nhớ" đã cắn nơi khác).
4. **I4 — không hạ `fail_under` (so giá trị, không so số dòng), không sửa `.git/`/`.github/`, không push
   `main`.** `patcher.FORBIDDEN_PATHS` từng chỉ chặn `.github/rulesets/` — lỗ đó cho phép ghi đè
   `.github/workflows/ci.yml`, đã vá thành chặn cả hai thư mục.
5. **I5 — không tự xoá dead code, chỉ báo cáo.** `patcher.py` không có thao tác xoá trong danh sách 3 thao tác
   hợp lệ (`bump_dependency`, `regen_derived`, `fix_docs`).
6. **I6 — core (`xagents_core`) không biết tên "keeper".** Mọi thứ đặc thù keeper sống ở `src/keeper/`.
7. **I7 — keeper là khách hàng số 0 của chính nó.** BT8 (canary) phải chạy một chu kỳ thật trên X-Agents —
   keeper tự mở một PR bảo trì có bằng chứng, người merge — trước khi mở keeper cho repo khách.

## Sửa cái gì phải làm gì

| Sửa | Phải |
|---|---|
| Thêm agent bảo trì mới | File `agents/<khối>/<tên>.md`, đăng ký trong registry/ACL topic ở `core.py`, `make golden`, đủ 7 bước `../../CONTRIBUTING.md` §3 (kể cả `eval-record` model thật) |
| Thêm loại tín hiệu mới | `events.py` (thêm `kind`), `topics/schemas/*.json` viết tay + test đối chiếu `set(get_args(Topic)) == set(bus._schemas)`, thêm hàng vào `risk.py:RISK_RULES`, cập nhật nơi phát signal (`scout.py`/`health.py`/`drift.py`) |
| Đổi ngưỡng rủi ro tự động vá | `risk.py:RISK_RULES` — bảng dữ liệu tra theo TÊN HÀNG, khớp hàng đầu tiên, mọi `high` phải đứng trước `low`. Không viết chuỗi `if` (bài học K1.7) |
| Đổi luật ngân sách PR | `budget.py:can_open_pr()` — giữ nguyên tắc hỏi GitHub thật, không cache trong RAM |
| Publish PR thật cho một ticket | `orchestrator.publish()` (`push_branch`+`create_pr` từ `publish.py`, rồi `release.fill_pr_number`) qua CLI `keeper publish <ticket_id>` — không tự vá/tự commit, giả định worktree đã có patch |
