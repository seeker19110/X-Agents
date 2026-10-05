# ADR-0002: `publish()` so thứ sắp push với nội dung đã đo; sau lần đo chỉ được THÊM đúng dòng release của note

Ngày: 2026-10-05 · Trạng thái: được chấp nhận · Phạm vi: `companies/keeper` (bất biến I2 ở bước ra ngoài máy,
`DAC-TA-KEEPER.md` §0). Bổ sung ADR keeper 0001: định nghĩa `patch_id` giữ nguyên; ADR này lấp mục "Cố ý chưa
làm" đầu tiên của nó (`publish()` không so danh tính).

## Bối cảnh

ADR keeper 0001 gắn bằng chứng hai chiều vào `patch_id` = cây git nội dung worktree lúc đo, và cổng `evidence`
so danh tính lúc `open_pr()`. Bước push thật thì không so. Đo trên `main@9baa7df`:

| # | Hiện trạng | Chỗ |
|---|---|---|
| 1 | `publish()` gọi `push_branch` rồi `gh pr create` mà không hỏi `reports`/`patch_id`. Marker `no-ky-thuat` ghi nợ này. | `orchestrator.py:369-399` (marker ở :378, push ở :386) |
| 2 | Sau lần đo, keeper ghi đúng **2** đường dẫn vào worktree: `CHANGELOG.md` và `docs/sessions/<ngày>.md`, qua `release.record` → `patcher.fix_docs`, rồi `release.fill_pr_number` thay `(#PR)` bằng `(#n)`. | `release.py:52-96`, `patcher.py:217-239` |
| 3 | Lần push thứ hai mang commit điền số, mà commit đó là `git commit -a`: mọi file đã track bị sửa chưa commit đi theo. | `orchestrator.py:398-399`, `worktree.py:181-188` |
| 4 | `push_branch` đẩy **ref nhánh** `wt.branch`, không đẩy thư mục làm việc; cổng `evidence` đo thư mục làm việc của `KeeperWorktree(repo, ticket_id)`, có thể khác `wt` được truyền vào `publish`. | `publish.py:51`, `orchestrator.py:284-298` |
| 5 | Ticket duy nhất CLI `run` thi hành được là `fix_docs` — patch nằm TRỌN trong các file `.md`, có thể đúng `CHANGELOG.md`. | `cli.py:79-84` |

Tái hiện trước khi sửa (`tests/test_publish_so_danh_tinh.py`, git thật, `gh` giả): 13/15 ca đỏ. Sửa `app.py`
sau `open_pr` rồi `publish` → nhánh lên remote, `gh pr create` được gọi, PR mang code chưa đo. Xoá `CHANGELOG.md`
→ push + `gh` chạy rồi mới nổ `ValueError` ở `fill_pr_number`. Worktree đã dọn → `SharedCheckoutRefused` (CLI
không bắt, in traceback).

Số người gọi `record_verification(`/`collect_two_way(` ngoài test: **0** trong `companies/` và `platform/` (đếm lại
2026-10-05; dòng duy nhất khớp là sơ đồ trong docstring `evidence.py:20`). Không có `keeper.sqlite` nào trên máy
đo. Khẳng định "chưa có bus sản xuất" của ADR 0001 vẫn đúng — và ADR này không đổi định nghĩa `patch_id`, nên
không có báo cáo nào phải di cư.

Chi phí đo trên chính repo (830 file track): `content_tree` + `tree_of` + `tree_changes` = 0,092 s rồi 0,085 s.
`publish()` gọi hai lần.

## Quyết định

### (a) Danh tính không đổi; `publish()` so cây NHÁNH sắp push với cây đã đo

`patch_id` vẫn là `worktree.content_tree` của ADR 0001, và `collect_two_way`, `_evidence_current`, `publish()` cùng
dùng đúng hàm đó. `publish()` gọi `_require_measured(ticket_id, wt, note)` **trước mỗi lần** `push_branch`, cả lần
thứ hai sau commit điền số. Hàm ném `EvidenceError`, không push, không gọi `gh`, khi:

1. Không còn báo cáo đạt I2 mang `patch_id` trong `reports`: báo cáo mới hơn đã thu hồi (ADR 0001 mục b), hoặc
   chưa từng có. Kiểm cả khi tắt phép kiểm ở đường nạp, để chốt này tự đứng được.
2. `content_tree(wt.path) != tree_of(wt.path, sha)`: worktree còn thay đổi chưa commit. Nếu không chặn, `commit -a`
   của bước điền số đưa chúng lên PR.
3. `release.unmeasured_changes(wt.path, patch_id, cây của sha, note)` khác rỗng (mục b).
4. Bất kỳ `WorktreeError` nào: worktree mất, `patch_id` không còn trong kho object (gc), git lỗi. Fail closed.

Đo đúng `wt`, không qua `patch_identity(ticket_id)`. Lý do: thứ bị push là nhánh của `wt`, và chốt phải nhìn đúng
thứ nó thả đi. `patch_identity` tiêm được vẫn phục vụ cổng `evidence` như cũ.

**Push đúng sha đã kiểm** (bổ sung 2026-10-05, trả nợ mục "Cố ý chưa làm" đầu tiên). `sha` ở trên là
`worktree.commit_of(wt.path, "refs/heads/<nhánh>")`, phân giải MỘT lần; cây được kiểm là cây của chính sha đó, và
`_require_measured` trả sha ấy. `push_branch(wt, sha=sha)` đẩy `git push <remote> <sha>:refs/heads/<nhánh>`: đích
vẫn chỉ là nhánh của worktree (I1), nguồn là commit đã kiểm chứ không phải tên nhánh được phân giải lại lúc push.
Một commit chen vào nhánh ticket giữa kiểm và push không lên remote; lần publish sau (nếu còn) kiểm lại từ đầu. Ca
`test_publish_day_dung_sha_da_kiem_khi_commit_chen_truoc_lan_push_dau` / `…_thu_hai` đỏ khi refspec quay về tên
nhánh (remote nhận commit chen). Bỏ `-u`: nguồn là sha thì git không có nhánh cục bộ để gắn upstream (đo git 2.43:
`push -u` trả 0, `branch.*` vẫn rỗng), và không chỗ nào trong keeper đọc upstream — `create_pr` nhận `--head`.
Không thêm `--force-with-lease`: mọi lần push của `publish()` là fast-forward (commit điền số là hậu duệ của commit
đầu), còn sha lùi so với remote thì git tự từ chối non-fast-forward như trước (đo git 2.43).

CLI `keeper publish` bắt `EvidenceError` → in lý do, thoát **4** (2 = chưa có note, 3 = push/`gh` lỗi).

### (b) Sau lần đo chỉ được THÊM đúng dòng release của note, ở đúng hai chỗ

`release.py` giữ hằng số `CHANGELOG_PATH = "CHANGELOG.md"` và mẫu `docs/sessions/<YYYY-MM-DD>.md`. Đó cũng là
mặc định của `record`/`fill_pr_number`, nên tập được phép không lệch khỏi thứ hai hàm ấy ghi. Hai thứ này nằm
trong mã, không lấy từ payload model hay từ note. `unmeasured_changes` đọc `diff-tree -r -z --no-renames
--name-status` giữa hai cây và cho qua một file chỉ khi đủ cả bốn điều:

- đường dẫn thuộc tập trên (thư mục con của `docs/sessions/` hay tên không phải ngày đều là đường dẫn lạ);
- trạng thái `A` hoặc `M` (`D`/`T` bị chặn — `T` tự nó là lý do: file thành symlink có đích đúng bằng dòng của note
  thì mọi "dòng" của nó đều được phép, nên phép dòng không thấy gì; ca `test_unmeasured_changes_tu_choi_doi_kieu_file_du_noi_dung_y_het`);
- các dòng của bản đã đo là **dãy con** của bản mới, tức không sửa và không xoá dòng nào;
- mỗi dòng thêm là dòng trống, dòng của chính note (`changelog_line` cho CHANGELOG, `session_line` cho nhật ký;
  chỗ số PR khớp `(#PR)` hoặc `(#<số>)`), hoặc tiêu đề `# Phiên <ngày>` mà `fix_docs` đặt cho nhật ký mới.

Nội dung đọc thẳng từ kho object (`cat-file blob`), không qua văn bản diff, vì văn bản diff lệ thuộc cấu hình
(lý do loại của ADR 0001).

**Patch chỉ sửa đúng các file được phép** (ticket `fix_docs` sửa `CHANGELOG.md`): vẫn bị gắn trọn. Dòng nó đã đo
nằm trong `patch_id`, nên sau lần đo không sửa hay xoá được dòng nào. Thứ duy nhất thêm được là dòng của chính
note, do `release.compose` (code) soạn. Tập đường dẫn được phép vì thế không phải cửa sau cho nội dung tuỳ ý.

**Gọi lại sau push hỏng**: commit điền số đã có `(#9)` nhưng note trên bus chưa mang số. Dòng `(#9)` vẫn khớp
dòng của note, nên lần gọi lại đi tiếp như trước.

Marker `no-ky-thuat` ở `publish()` bị xoá vì nợ đã trả.

## Phương án đã loại

- **Đổi danh tính thành "cây code", bỏ hẳn `CHANGELOG.md`/`docs/sessions/` khỏi `content_tree`** (hướng gợi ý ban
  đầu). Ưu điểm: một phép so bằng, `_evidence_current` và `publish()` y hệt nhau. Loại vì ba lẽ:
  - Với ticket `fix_docs`, thứ duy nhất CLI `run` thi hành được, toàn bộ patch nằm ngoài danh tính. Sau lần đo,
    ai sửa `CHANGELOG.md` thế nào publish cũng qua. Lỗ I2 chuyển từ "mọi ticket" sang "đúng loại ticket đang chạy
    thật".
  - Phải loại trừ cả thư mục `docs/sessions/`, mà nhật ký phiên của người cũng nằm ở đó.
  - Đổi định nghĩa `patch_id` buộc mọi báo cáo cũ lệch danh tính. Chi phí bằng 0 hôm nay (không bus sản xuất),
    nhưng là thay đổi kiến trúc không cần thiết.
- **Loại trừ đường dẫn nhưng bắt buộc patch có diff code thật.** Loại vì nó chặn vĩnh viễn ticket `fix_docs`, tức
  chặn đúng đường thật duy nhất.
- **Tái dựng nội dung kỳ vọng (`record` chạy lại trên cây đã đo) rồi so bằng.** Ưu điểm: chặt nhất. Loại vì
  `fix_docs` chèn CHANGELOG theo vị trí tiêu đề và đọc ngày nhật ký từ `session_date` mà `publish` không biết. Sao
  lại thuật toán chèn ở bước kiểm là bản sao thứ hai sẽ lệch. Phép "dãy con + dòng của note" chặn cùng lớp lỗi mà
  không phụ thuộc vị trí chèn.
- **Ghi dòng release vào worktree trước lần đo** (điều kiện quay lại của marker cũ). Loại vì note chỉ có sau
  `open_pr()`, mà `open_pr()` chỉ chạy sau khi cổng `evidence` đã mở trên báo cáo. Đảo thứ tự là vòng tròn. Dù có
  đảo, `fill_pr_number` vẫn đổi `(#PR)` → `(#n)` sau lần đo.
- **So danh tính bằng `patch_identity(ticket_id)` như cổng `evidence`.** Loại theo (a): nó đo thư mục làm việc của
  worktree mặc định, không đo ref nhánh được push.
- **Chỉ kiểm trước lần push đầu.** Loại vì bảng bối cảnh #3: `commit -a` của bước điền số là đường thứ hai cho code
  chưa đo lên PR. Ca `test_publish_kiem_lai_truoc_lan_push_thu_hai` đỏ khi bỏ lần kiểm thứ hai.

## Hệ quả

- **Phải sửa theo:**
  - `worktree.py`: `tree_of`, `tree_changes`, `blob_text`; bổ sung `commit_of`.
  - `release.py`: `CHANGELOG_PATH`, `unmeasured_changes`.
  - `orchestrator.py`: `_require_measured` (trả sha đã kiểm), hai lời gọi trong `publish()`.
  - `publish.py`: `push_branch(wt, *, sha, …)` bắt buộc `sha` — không còn đường push theo tên nhánh.
  - `cli.py`: mã thoát 4.
  - Test cũ của `publish` từng ghi một dòng CHANGELOG **khác** dòng của note (`bump requests … tier low`, trong khi
    note là `requests … tier medium`). Giờ chúng ghi đúng `note.changelog_line`.
- **Khó hơn:**
  - Thêm khoảng 0,09 s × 2 mỗi lần `publish` trên repo cỡ này. Không đáng kể với một lệnh người gọi tay.
  - Người sửa tay `CHANGELOG.md` sau lần đo, kể cả sửa chữ, phải đo lại. Đây là chặt hơn có chủ ý.
- **Cố ý chưa làm:**
  - ~~Kiểm rồi push theo **tên nhánh**, không theo sha đã kiểm.~~ Đã trả 2026-10-05: push đúng sha đã kiểm (mục a,
    "Push đúng sha đã kiểm"); marker `no-ky-thuat` tại `_require_measured` đã gỡ.
  - Ai ghi được `release-notes` thì chọn được nội dung "dòng của note". Thứ được thêm vẫn chỉ là dòng trong hai
    file markdown, không phải code.
- **Nhận biết nếu sai:**
  - `keeper publish` thoát 4 trên một ticket không ai sửa sau `open_pr`, nghĩa là có thứ ghi worktree mà ADR không
    biết (lệnh CI, hook, công cụ format). Lý do in ra nêu đích danh đường dẫn.
  - PR keeper có file ngoài `patch_id` + hai file release, nghĩa là có đường push không đi qua `_require_measured`.
