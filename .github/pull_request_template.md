## Tóm tắt

-

## Issue / outcome

Closes #

## Đặc tả / ADR

<!-- Bắt buộc với thay đổi kiến trúc, agent, schema topic, hợp đồng event. -->

- ADR / đặc tả:
- Điểm lệch so với đặc tả (nếu có):

## Loại thay đổi

- [ ] feat
- [ ] fix
- [ ] refactor
- [ ] perf
- [ ] docs
- [ ] test
- [ ] chore
- [ ] breaking change

## Validation

- [ ] `scripts/dev-task.sh gate <gói>` cho mọi gói bị đụng (`company|gateway|console|core|keeper|all` — khớp đúng `ci.yml`)
- [ ] Test đỏ TRƯỚC khi sửa, xanh sau (`AGENTS.md` luật bắt buộc 4) — tên ca:
- [ ] Chạm `agents/`/`skills/`: đủ 7 bước `CONTRIBUTING.md` §3
- [ ] Kiểm tay:

### Bằng chứng

<!-- Số test, output lệnh, hoặc diff golden. -->

## Definition of Done

- [ ] Thay đổi khớp đặc tả/ADR; điểm lệch đã ghi.
- [ ] Test mới chứng minh hành vi; mọi cổng liên quan xanh.
- [ ] Đã tự đọc lại diff; chỉ gồm thay đổi thuộc phạm vi.
- [ ] Không secret, không debug log, không file sinh tự động ngoài ý muốn.
- [ ] Tài liệu (`README.md`, `docs/`, ADR) đã cập nhật.
- [ ] Dòng `CHANGELOG.md` mang `(#<số PR>)` và `docs/sessions/<ngày>.md` nằm trong CHÍNH PR này (`AGENTS.md` luật bắt buộc 10).
- [ ] Breaking change được nêu rõ kèm cách chuyển đổi.

## BÁO CÁO XÁC THỰC

<!-- AGENTS.md luật cấm 8 bước 4: điền bằng output lệnh vừa chạy trong lượt này, không chép lượt trước. Bất kỳ ❌ nào
     ⇒ chưa bật auto-merge. `n-a` chỉ khi PR không chạm phần đó. -->

```
BÁO CÁO XÁC THỰC — <nhánh> @ <sha>
make lint ✅/❌ (ruff: .. | mypy: .. file)
make test ✅/❌ (X passed, Y failed, Z skipped)
make cov  ✅/❌ (fail_under = 100 — đạt/thiếu <n> dòng ở <file>)
evals --replay --strict ✅/❌/n-a   | subagents check ✅/❌/n-a   | assetscan scan ✅/❌/n-a
Test đỏ TRƯỚC khi sửa (luật bắt buộc 4, đo hai chiều) ✅/❌/n-a — tên ca: <..>
Bảy bước CONTRIBUTING §3 (nếu chạm agents/ hoặc skills/) ✅/n-a
CHANGELOG + docs/sessions/<ngày>.md trong CHÍNH PR này (luật 10) ✅/❌
KẾT LUẬN: Sẵn sàng  /  Cần xử lý: <..>
```

## Ghi chú cho reviewer
