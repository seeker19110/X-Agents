# ARCHITECTURE.md — keeper

```
Tín hiệu (dependency-scout, security-auditor, health-monitor, drift-detector)
        │  Signal(kind=..., subject=...)
        ▼
signals.dedupe() ── gộp trùng theo (kind, subject)
        │
        ▼
triager ── Signal → Ticket, khoá chống trùng theo THẾ HỆ (số vòng đời ticket đã đóng)
        │
        ▼
risk_tier() ── bảng RISK_RULES tra theo tên hàng, khớp hàng ĐẦU TIÊN (high trước low)
        │
   ┌────┴────┐
   ▼         ▼
rủi ro thấp  rủi ro cao/không rõ
(tự động vá) (chờ gate người — HumanGate qua PersistentGate của xagents_core)
   │         │
   ▼         ▼
patcher.py (3 thao tác: bump_dependency / regen_derived / fix_docs; FORBIDDEN_PATHS chặn .git/ .github/)
   │
   ▼
evidence.require_two_way() ── BẮT BUỘC: đo trước (đỏ) và đo sau (xanh), không có ca nào bỏ qua; báo cáo gắn
   │                          patch_id (cây nội dung worktree) — sửa patch sau khi đo thì cổng evidence đóng lại
   │
   ▼
release-clerk ── open_pr(): soạn CHANGELOG (PR_PLACEHOLDER), ghi pr.intent vào audit-log — Ý ĐỊNH, chưa PR thật
   │
   ▼
NGƯỜI/script gọi `keeper publish <ticket_id>` ── orchestrator.publish(): push_branch() + create_pr() (publish.py)
   │                                              rồi fill_pr_number() điền số PR thật, ghi audit pr.created
   ▼
NGƯỜI merge PR thật (I1: keeper không có quyền tự merge)
```

`publish()` KHÔNG chạy tự động trong `watch` — vòng lặp mới nối `triage`+`open_pr` (ý định); scout chưa nối
vào `tick()`, patch cần `keeper run`/người commit tay. Đây là ranh giới đã đo được khi thử canary thật lần đầu
(`TRAPS.md`): từng mảnh có mã + test, nhưng chuỗi signal→patch→publish chưa nối thành một vòng tự động.

`orchestrator.py` chạy vòng lặp trên, resume được qua `SQLiteBus` — mở lại tiến trình không làm lại việc đã
xong. `worktree.py` cấp một worktree git riêng mỗi ticket; tuyệt đối không `reset --hard`/`clean` trên checkout
chung của phiên khác.

## Bảy bất biến giữ hình dạng này (I1–I7, `docs/DAC-TA-KEEPER.md` §0)

| Bất biến | Ở đâu | Vì sao |
|---|---|---|
| I1 — không quyền ghi ngoài worktree/PR của chính nó | `github.py` (chỉ hàm đọc) | Keeper vá chính repo chứa nó — quyền ghi rộng là rủi ro tối đa |
| I2 — bằng chứng đo hai chiều bắt buộc | `evidence.require_two_way()`, `orchestrator._check_report()` + danh tính patch (ADR keeper 0001) | "Tests pass" không kèm bằng chứng đỏ→xanh là lời khai, không phải bằng chứng (luật cấm 8) |
| I3 — một PR bảo trì mở tại một thời điểm, hỏi GitHub thật | `budget.can_open_pr()` | Đếm trong RAM mất khi mở lại tiến trình — đúng khuôn lỗi "chống trùng sống trong bộ nhớ" |
| I4 — không hạ `fail_under`, không sửa `.git/`/`.github/` | `patcher.FORBIDDEN_PATHS` | Từng có lỗ chỉ chặn `.github/rulesets/`, cho phép ghi đè `ci.yml` — vô hiệu hoá cổng bằng chính bản vá |
| I5 — không tự xoá dead code | `patcher.py` (3 thao tác, không có xoá) | Xoá sai là mất việc người khác đang làm dở |
| I6 — core không biết tên "keeper" | mọi logic đặc thù ở `src/keeper/`, không đụng `xagents_core` | Giữ lõi dùng chung được cho công ty khác |
| I7 — keeper là khách hàng số 0 | canary BT8, `docs/DAC-TA-KEEPER.md` §10 | Tự tin vào cơ chế của mình trước khi mở cho repo khách |

## Ranh giới với phần còn lại của hub

- **Vào**: `xagents_core` (bus, gate, runner, guard — 15 file trong `src/` import, đo 2026-09-28); không nhận
  việc từ `platform/console` qua đường ghi (console chỉ đọc bus của keeper).
- **Ra**: GitHub API qua `gh` CLI — đọc (`GitHubReader`, mọi nơi khác) và GHI (`publish.py`, chỉ `git push`
  nhánh của ticket + `gh pr create`, không gì khác); model qua `llm.py` (mặc định provider `fake`, offline —
  chạy model thật cần `llm.yaml` riêng, tiền tố env `KEEPER_*`).
- **Đĩa**: `company.sqlite`-kiểu bus SQLite riêng của keeper; worktree riêng mỗi ticket dưới thư mục tạm, không
  đụng checkout chính.
- **Test**: số ca hiện tại ở dòng keeper trong `README.md` gốc (có cổng canh); `branch = true` +
  `fail_under = 100` đã bật — một trong hai package đầu tiên đạt mốc này cùng `xagents-core`.
- **ADR**: quyết định chỉ chạm keeper nằm ở `docs/adr/` của package — `docs/adr/0001-bang-chung-gan-danh-tinh-
  patch-va-thu-hoi-ben.md` (bằng chứng gắn danh tính patch, đo lại hỏng thu hồi bền qua bus). Thiết kế công ty
  chạm cả `xagents-core` nên ở gốc repo: `docs/adr/0006-cong-ty-bao-tri-keeper.md` (gốc). Đặc tả chi tiết (bất biến, lộ trình BT1–BT8) ở `docs/DAC-TA-KEEPER.md`.

Trạng thái: BT1–BT7 đã merge, package có mã thật chạy được; phần console + tài liệu của BT8 đã merge (#223).
Còn lại của BT8 là canary — một chu kỳ thật, người merge PR đầu tiên keeper tự mở (hai lần thử, xem `README.md`
§"Cái gì CHƯA có") — điều kiện cuối trước khi mở cho repo khách ngoài X-Agents.
