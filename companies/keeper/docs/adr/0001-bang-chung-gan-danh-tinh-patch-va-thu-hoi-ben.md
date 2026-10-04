# ADR-0001: Bằng chứng hai chiều gắn vào danh tính patch (cây nội dung worktree); đo lại hỏng thì thu hồi bền qua bus

Ngày: 2026-10-04 · Trạng thái: được chấp nhận · Phạm vi: `companies/keeper` (bất biến I2, `DAC-TA-KEEPER.md` §0,
§8). ADR đầu tiên của dãy `companies/keeper/docs/adr/`: quyết định chỉ chạm một package nên nằm trong package
(`docs/adr/README.md` gốc). ADR thiết kế công ty, `docs/adr/0006-cong-ty-bao-tri-keeper.md`, ở gốc vì nó chạm
cả keeper lẫn `xagents-core`. Trong mã keeper, ADR này được gọi là "ADR keeper 0001".

## Bối cảnh

Sau #379, I2 còn hai nợ cố ý. Đo trên `main@c9b6a4d`:

| # | Hiện trạng | Chỗ |
|---|---|---|
| 1 | `record_verification()` gọi `verification_report()`. Hàm này ném `EvidenceError` **trước** khi có gì lên bus. Ticket đã `verified` từ báo cáo trước giữ nguyên `verified`. Mở lại bus thì replay dựng lại `verified` từ báo cáo cũ. Marker `no-ky-thuat` ghi nợ này. | `orchestrator.py:252-259` (marker ở :256) |
| 1' | Thu hồi chỉ chạy qua `_reject_report`, tức chỉ khi một báo cáo hỏng **đã nằm trên bus** đi qua `_apply` (`VERIFY_ON_APPLY`). | `orchestrator.py:178-192`, `:206-219` |
| 1'' | Đường nạp chỉ chạy `require_two_way`. Đường dựng còn chạy thêm `_require_family_from_report`. Báo cáo ghi thẳng lên bus với `family_hits` có mà `family_safe` rỗng vẫn được nạp. | `orchestrator.py:184-189`, `evidence.py:262-265` |
| 2 | `VerificationReport` không có trường nào nói nó đo **nội dung nào**. | `events.py:96-103` |
| 2' | `collect_two_way()` stash toàn bộ worktree, chạy lệnh (`before`), pop, rồi chạy lại (`after`). Không ghi lại nội dung đã đo. | `evidence.py:190-234` |
| 2'' | Cổng `evidence` chỉ hỏi `ticket_id in self.verified`. Sửa patch sau khi `verified` thì cổng vẫn mở, và PR mang code chưa đo. | `orchestrator.py:299-300` |

Số người gọi: chỉ đếm lời gọi thật, không đếm docstring. `record_verification(` và `collect_two_way(` có **0**
lời gọi trong `companies/keeper/src`, `platform/` và `companies/software-company/src`. Test cũ có 5 chỗ gọi
`record_verification(` và 9 chỗ gọi `collect_two_way(`. Thiết kế lại vì thế không có bus sản xuất nào cần di cư.

Đo ứng viên danh tính trên chính repo này (825 file track; script đo dùng index tạm, không chạm index thật):

| Phép đo | Kết quả |
|---|---|
| `GIT_INDEX_FILE=<tmp> git read-tree HEAD && git add -A && git write-tree`, lần 1 | 0,052 s → `daa0412d…` |
| Cùng lệnh, lần 2 | 0,049 s → `daa0412d…` (xác định) |
| `git rev-parse HEAD^{tree}` trên worktree sạch | `daa0412d…`: bằng cây của commit, nên không phụ thuộc commit |
| `git status --porcelain` sau khi đo | rỗng: index thật không đổi |

## Quyết định

### (a) Danh tính patch = id cây git của **nội dung worktree** lúc đo, do code đo

- **Hàm đo.** `worktree.content_tree(path)` chạy `read-tree HEAD` → `add -A` → `write-tree` trên một index tạm
  (`GIT_INDEX_FILE` trong `tempfile.TemporaryDirectory`). Mọi lệnh đi qua `_git`, tức `git_env()` (bỏ mọi `GIT_*`
  của tiến trình cha) và `NO_HOOKS`.
- **Tính chất.** Kết quả xác định, không phụ thuộc thời gian hay locale. Nó gồm file chưa track: stash
  `--include-untracked` cũng cất chúng, nên chúng là một phần của thứ được đo. Nó bỏ file bị `.gitignore`. Index
  thật không đổi.
- **Không phụ thuộc commit.** Commit đúng nội dung đã đo thì danh tính không đổi, vì nó bằng `HEAD^{tree}`.
  Danh tính bám nội dung, không bám lịch sử.
- **Nơi đo.** `collect_two_way(..., identify=content_tree)` là nơi duy nhất đặt `verified_by`, và giờ cũng là
  nơi duy nhất đặt `patch_id`. Nó đo trước khi stash. Sau lần chạy `after` nó đo lại. Hai số khác nhau (pop trả
  sai, hoặc lệnh CI tự ghi file không bị ignore) thì ném `EvidenceError("nội dung worktree đổi trong lúc đo")`,
  vì không có nội dung nào để gắn báo cáo vào.
- **Chặn lời khai.** `patch_id` vào `SELF_CLAIM_FIELDS` và vào `_measured()`. Hai tập này đã có test khoá bằng
  nhau. Thứ tự hợp nhất `{**clean, **measured}` giữ nguyên, nên số đo thắng lời khai cả khi bộ lọc bị tắt.
- **Cổng.** `pr_blockers()` mở `evidence` chỉ khi `ticket ∈ verified` **và**
  `patch_identity(ticket_id) == reports[ticket_id].patch_id`. `patch_identity` tiêm được (khuôn
  `runner: CommandRunner`). Mặc định nó là `content_tree(KeeperWorktree(repo, ticket_id).path)`. Không đo được
  (worktree đã dọn, git lỗi) thì trả `None`, và `None` không bao giờ bằng một danh tính đã đo, nên cổng đóng.

### (b) Báo cáo trên bus không có `patch_id` (hình dạng trước ADR này): từ chối khi nạp

`VerificationReport.patch_id: str | None = None`. Payload cũ vẫn parse được, nên replay không sập. Phép kiểm báo
cáo (`check_report`, cùng một hàm cho cả hai đường) coi `patch_id is None` là không đạt. Báo cáo cũ vì thế
đi vào `_reject_report`:

- không thành `verified`;
- thu hồi `verified` của báo cáo trước nếu có;
- ghi đúng một `verification.rejected`, dù mở lại bus bao nhiêu lần.

Lý do: chấp nhận báo cáo thiếu trường thì ai ghi được `verification-reports` cũng mở được cổng chỉ bằng cách
**bỏ** trường đó. Chi phí bằng 0 vì chưa có báo cáo sản xuất nào (bảng trên).

### (c) Đo lại hỏng ⇒ thu hồi BỀN trên bus, caller vẫn nhận `EvidenceError`

`verification_report()` tách thành hai bước, `build_report()` rồi `check_report()`; hàm cũ giữ nguyên, bằng hai
bước ghép lại. `record_verification()` làm như sau:

1. Dựng báo cáo bằng `build_report()`.
2. Kiểm bằng **đúng** phép kiểm mà `_apply` dùng.
3. Không đạt: vẫn publish báo cáo đó lên `verification-reports`. `_apply` nhận nó (subscribe đồng bộ), từ chối
   qua `_reject_report` + `_audit_reject` có sẵn (không có đường song song), rồi `record_verification` ném lại
   đúng `EvidenceError` cho caller.

Sau đó báo cáo hỏng là báo cáo **mới nhất** của ticket trên bus. Replay đi theo thứ tự bus nên cho cùng kết quả,
và không hồi sinh `verified` từ báo cáo cũ. Lần đo lại đạt sau đó lại là báo cáo mới nhất, nên cấp lại
`verified`. Vì `_apply` giờ chạy cả `_require_family_from_report`, lỗ 1'' cũng đóng.

Marker `no-ky-thuat` ở `orchestrator.py:256` bị xoá vì nợ đã trả.

## Phương án đã loại

- **HEAD sha + hash của `git diff`.** Ưu điểm: rẻ, dễ hiểu. Loại vì hai lẽ. Commit patch là danh tính đổi dù nội
  dung y nguyên, mà luồng thật luôn commit sau khi đo. Văn bản diff còn phụ thuộc cấu hình (`diff.algorithm`,
  `core.autocrlf`, màu), nên hai máy cho hai hash khác nhau.
- **`git stash create`.** Ưu điểm: một lệnh, không ghi gì vào worktree. Loại vì không cất file chưa track (file
  test mới của patch nằm ngoài danh tính). Commit nó tạo ra còn mang dấu thời gian, nên không xác định.
- **Cây của commit stash do chính `collect_two_way` tạo.** Ưu điểm: đúng thứ đã bị tắt và bật. Loại vì lúc hỏi
  cổng không tính lại được mà không stash lần nữa. Stash lúc hỏi cổng là thao tác phá dữ liệu trên đường đọc.
- **Tự đi cây thư mục bằng Python rồi băm.** Ưu điểm: không gọi git. Loại vì phải tự làm lại `.gitignore`, mode
  file, symlink, CRLF. Đó là phát minh lại git, và lệch nó ở đúng các ca biên.
- **Cổng `evidence` chỉ kiểm danh tính lúc `publish()`.** Loại vì `open_pr()` đã phát `release-notes` và
  `pr.intent` trước đó. Ý định PR trên bus đã mang code chưa đo.
- **Đo lại hỏng thì xoá `verified` trong RAM rồi ném, không ghi bus.** Loại vì mở lại tiến trình là replay dựng
  lại `verified` từ báo cáo cũ, đúng nợ 1.
- **Một topic/action "revoke" riêng.** Loại vì nó là đường thu hồi thứ hai, song song với `_reject_report`. Hai
  đường cho một sự thật là chỗ lệch kế tiếp. Báo cáo hỏng tự nó đã là sự kiện thu hồi.
- **Chấp nhận báo cáo cũ không `patch_id` như "chưa biết, cho qua".** Loại theo (b).

## Hệ quả

- **Phải sửa theo:**
  - `events.VerificationReport.patch_id` và `topics/schemas/verification-reports.json`, có test đối chiếu
    model ⊆ schema.
  - `evidence.py`: `TwoWayEvidence.patch_id`, `SELF_CLAIM_FIELDS`, `_measured`, `build_report`/`check_report`,
    tham số `identify` của `collect_two_way`.
  - `worktree.content_tree` và tham số `env` của `_git`.
  - `orchestrator.py`: tham số `patch_identity`, `_check_report`, `_evidence_current`.
  - Test cũ dựng `TwoWayEvidence` tay giờ phải mang `patch_id`. Test đi qua cổng trên repo thật phải mở worktree
    trước khi đo.
- **Khó hơn:**
  - Mỗi lần hỏi cổng của một ticket đã `verified` là một lần băm lại worktree. Index tạm không có stat nên mọi
    file đều bị đọc; đo được ~0,05 s cho 825 file. Có marker `no-ky-thuat` tại chỗ, kèm điều kiện quay lại.
  - Lệnh CI ghi ra file không bị `.gitignore` sẽ làm `collect_two_way` ném "đổi trong lúc đo". Đây là chặt hơn
    có chủ ý; repo khách có `.gitignore` lỏng sẽ thấy nó trước tiên.
- **Cố ý chưa làm:**
  - `publish()` không so danh tính. Dòng CHANGELOG và nhật ký phiên được ghi vào worktree **sau** khi đo, theo
    thiết kế (`release.compose` chạy sau cổng). Khoảng `open_pr → publish` vì thế chưa kiểm. Có marker tại
    `publish()`.
  - Payload của model hỏng ở lớp pydantic (ví dụ `family_safe` thiếu `reason`) thì không dựng được báo cáo nào
    để lên bus, nên báo cáo trước vẫn đứng. Nó chỉ mở cổng cho đúng nội dung nó đã đo, nên đây không phải lỗ
    mang code chưa đo. Có marker tại `record_verification`.
- **Prompt agent.** `agents/` của `regression-guard` không nhắc `patch_id`. Sửa prompt cần đủ bảy bước
  `CONTRIBUTING.md` §3, nên để PR riêng. Lời khai của model về trường này dù sao cũng bị bỏ.
- **Nhận biết nếu sai:**
  - Ticket kẹt `evidence` dù không ai sửa worktree, nghĩa là danh tính không ổn định. Kiểm bằng hai lần
    `content_tree` liên tiếp; `test_content_tree_xac_dinh_va_worktree_sach_bang_cay_head` khoá điều này.
  - `verification.rejected` với lỗi `patch_id` xuất hiện trên bus sản xuất, nghĩa là có producer chưa đi qua
    `collect_two_way`.
