# Đóng góp cho X-Agents

Mọi thay đổi đi theo một luồng duy nhất:
**Ý tưởng → Đặc tả (khi lớn) → Nhánh → Pull request → CI → Merge (squash) → Quan sát**.

Chi tiết, tiêu chí vào/ra và ma trận kiểm thử: [`docs/QUY-TRINH-GIT.md`](docs/QUY-TRINH-GIT.md).

## Bắt đầu nhanh

1. Thay đổi lớn (kiến trúc, agent, schema topic) → viết ADR ở `software-company/docs/adr/` trước.
2. Tách nhánh từ `main`: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `perf/<slug>`…
3. Commit theo Conventional Commits, scope chữ thường, một thay đổi logic mỗi commit.
4. Chạy cổng phù hợp mức rủi ro (bảng trong `docs/QUY-TRINH-GIT.md` mục 4).
5. Tạo PR ở trạng thái **ready** (không nháp), tiêu đề đúng quy ước, bật auto-merge (squash).
6. Theo dõi CI **mỗi 2,5 phút** (`gh pr checks <số PR> --watch --interval 150`).
7. CI xanh + không xung đột → merge (squash). Không merge tay khi CI chưa xanh.

## Lệnh kiểm tra chuẩn

```bash
cd software-company
uv sync
make lint
make test
```

Với thay đổi tài liệu thuần, đọc lại diff và `git diff --check` là đủ.

Sửa `agents/` hoặc `skills/` → tăng `version`, `make golden`, rồi `make eval-record AGENT=<id>` bằng model thật và
commit `evals/recordings/<id>.json`; CI phát lại bản ghi và đỏ nếu bản ghi lệch prompt (ADR-0010).

## Quy tắc an toàn

- Không commit secret, khóa API, `llm.yaml` hay dữ liệu thật.
- Không gọi provider trả phí trong test.
- Không push thẳng `main`; mọi thay đổi vào `main` đều qua pull request.
