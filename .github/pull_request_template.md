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

## Definition of Done

<!-- Chỉ những ô máy không kiểm được; cổng, CHANGELOG, test đỏ trước nằm ở CI và khối BÁO CÁO dưới. Ô không áp dụng
     (vd không có breaking change) thì tick và ghi "không có". -->

- [ ] Thay đổi khớp đặc tả/ADR; điểm lệch đã ghi.
- [ ] Đã tự đọc lại diff; chỉ gồm thay đổi thuộc phạm vi.
- [ ] Tài liệu (`README.md`, `docs/`, ADR) đã cập nhật.
- [ ] Breaking change được nêu rõ kèm cách chuyển đổi.

## BÁO CÁO XÁC THỰC

<!-- AGENTS.md luật cấm 8 bước 4: điền bằng output lệnh vừa chạy trong lượt này, không chép lượt trước. Bất kỳ ❌ nào
     ⇒ chưa bật auto-merge. `n-a` chỉ khi PR không chạm phần đó. Bằng chứng thêm (kiểm tay, diff golden) dán ngay dưới khối. -->

```
BÁO CÁO XÁC THỰC — <nhánh> @ <sha>
scripts/dev-task.sh gate <gói> ✅/❌ (X passed, Y failed; phủ 100% đạt/thiếu <n> dòng ở <file>)
evals --replay --strict ✅/❌/n-a   | subagents check ✅/❌/n-a   | assetscan scan ✅/❌/n-a
Test đỏ TRƯỚC khi sửa (luật bắt buộc 4, đo hai chiều) ✅/❌/n-a — tên ca: <..>
Bảy bước CONTRIBUTING §3 (nếu chạm agents/ hoặc skills/) ✅/n-a
Dòng CHANGELOG.md trong CHÍNH PR này (luật 10) ✅/❌
KẾT LUẬN: Sẵn sàng  /  Cần xử lý: <..>
```

## Ghi chú cho reviewer
