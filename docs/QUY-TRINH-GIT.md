# Quy trình làm việc với Git — X-Agents

Áp từ quy trình của dự án `donghanh` (`CONTRIBUTING.md`, `docs/DEVELOPMENT_WORKFLOW.md`,
`CLAUDE.md` mục 11), rút gọn cho repo này: repo tài liệu + Python (`software-company/`),
làm việc chủ yếu một mình cùng AI, cổng chất lượng là `make lint` + `make test`.

Luồng chuẩn: **Ý tưởng → Đặc tả → Nhánh → PR → CI/Review → Merge (squash) → Quan sát**.

## 1. Cổng đặc tả (chỉ với thay đổi lớn)

Thay đổi kiến trúc, thêm/bỏ agent, đổi schema topic, đổi hợp đồng event → viết ADR trong
`<công ty>/docs/adr/` (ví dụ `software-company/docs/adr/`) **trước** khi code, và link ADR trong PR. Sửa lỗi nhỏ, chỉnh
prompt/skill, sửa tài liệu thì đi thẳng bước 2.

Không dùng "AI đề xuất" làm bằng chứng. Mọi khẳng định quan trọng phải truy được về code,
test, hoặc nguồn chính thống có ngày truy cập.

## 2. Nhánh

- Tách nhánh từ `main`, mỗi tính năng/sửa lỗi một nhánh.
- Đặt tên: `feat/<slug>`, `fix/<slug>`, `refactor/<slug>`, `perf/<slug>`, `docs/<slug>`,
  `chore/<slug>`. Có issue thì `feat/<issue>-<slug>`.
- **Không push thẳng `main`.** Mọi thay đổi vào `main` đều qua pull request, kể cả khi làm một mình.

## 3. Commit

- Conventional Commits: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `style`, `perf`,
  `build`, `ci`, `revert`. Scope viết **chữ thường**: `feat(software-company): ...`.
- Một commit = một thay đổi logic. Commit nhỏ, thân bài nêu *vì sao*, không chỉ *cái gì*.

## 4. Cổng kiểm thử theo mức rủi ro

| Thay đổi | Bằng chứng tối thiểu |
| --- | --- |
| Tài liệu thuần (`*.md`, docs) | Đọc lại diff, `git diff --check` |
| Prompt agent / skill / template | `make test` (golden 20 agent bắt được thay đổi prompt) |
| Code `src/company/**` | `make lint` + `make test`, thêm test cho hành vi mới |
| Schema topic / hợp đồng event | Các cổng trên + ADR + kiểm test nhất quán registry↔events |
| Đổi cổng CI | Chạy thật trên PR đó rồi đọc thời gian từng job, không đoán |

Không commit secret, `llm.yaml`, khóa API, hay dữ liệu thật. Không gọi provider trả phí trong test.

## 5. Pull request — bốn bước làm liền một mạch

1. **Kiểm tiêu đề trước khi tạo PR.** Cổng `metadata` chặn tiêu đề sai:
   ```
   ^(feat|fix|refactor|docs|test|chore|style|perf|build|ci|revert)(\([a-z0-9._/-]+\))?!?: .+
   ```
   Bẫy: scope chỉ nhận chữ thường — `fix(skillTiering)` trượt, `fix(skills)` đạt.
2. **Tạo PR ở trạng thái ready, không để nháp.** GitHub từ chối bật auto-merge trên PR nháp.
3. **Bật auto-merge (squash) ngay sau lệnh tạo PR** — gọi một lần, không hỏi lại. Thất bại thì
   **không bỏ mặc PR**: theo dõi CI, **xanh + không xung đột là merge (squash) ngay**.

   **Nhịp theo dõi CI: kiểm mỗi 2,5 phút (150 giây) cho tới khi có kết luận.** Không kiểm liên
   tục (tốn lượt gọi API, không nhanh hơn vì job mất vài phút), cũng không bỏ đi rồi quay lại
   sau nửa tiếng. Lệnh một vòng kiểm:

   ```bash
   gh pr checks <số PR> --watch --interval 150
   ```

   Hoặc kiểm rời từng nhịp: `gh pr checks <số PR>`. Xanh hết → merge (squash) ngay. Có check đỏ
   → đọc log (`gh run view <id> --log-failed`), tái hiện lỗi ở máy, sửa, push, rồi lại theo nhịp
   2,5 phút. Đang `queued`/`in_progress` → chờ nhịp kế tiếp, không kết luận sớm.
4. **Chỉ gộp `main` khi thật sự cần**: GitHub báo xung đột, hoặc `main` vừa đổi thứ PR này cũng
   đụng (nguy cơ xung đột ngữ nghĩa). Không gộp theo phản xạ.

**Cấm merge tay để đi tắt khi CI chưa xanh.** Đó là điều duy nhất bị cấm ở bước merge.

PR là của người tạo: CI đỏ thì đọc log, tái hiện lỗi ở máy, sửa và push cho tới khi xanh —
không để PR nằm đỏ chờ người khác.

Merge sạch (không xung đột) thì **không** chạy lại toàn bộ cổng ở máy — CI đã chạy trên kết quả
đã gộp. Merge có xung đột, hoặc `main` chạm file PR cũng chạm → chạy lại đủ cổng ở máy.

## 6. Definition of Done

- Thay đổi khớp đặc tả/ADR; điểm lệch được ghi rõ.
- Test mới chứng minh hành vi; `make lint` và `make test` xanh.
- Đã tự đọc lại diff; chỉ gồm thay đổi thuộc phạm vi.
- Không secret, không debug log, không file sinh tự động lọt vào.
- Tài liệu (`README.md`, `docs/`, ADR) cập nhật theo thay đổi.
- Breaking change được gọi tên kèm cách chuyển đổi.

## 7. Merge và sau merge

- Mặc định **squash merge**; xoá nhánh sau khi merge.
- Sau merge, kiểm `main` còn xanh; hỏng thì ưu tiên revert rồi điều tra trong PR mới.
- Tag `vX.Y.Z` khi phát hành mốc (`version` trong `software-company/pyproject.toml`).

## 8. Việc cần bật trên GitHub (một lần)

Quy trình trên giả định `main` có branch protection. Trong Settings → Branches của
`seeker19110/X-Agents`, thêm rule cho `main`:

- Require a pull request before merging.
- Required status checks: `quality`, `metadata`.
- **Tắt** "Require branches to be up to date before merging" (tránh mỗi PR khác merge là mọi PR
  đang mở phải gộp `main` rồi chờ CI lại).
- Bật "Allow auto-merge" và "Automatically delete head branches".
