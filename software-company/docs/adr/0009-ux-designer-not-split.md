# ADR-0009: Không tách ux-designer; đính chính quân số của ADR-0003

Trạng thái: Accepted · Ngày: 2026-09-02 · Sửa ADR-0003

## Bối cảnh
ADR-0003 quyết định mở rộng lên 22 agent, trong đó có `ux-designer` ở khối nghiên cứu, và ghi
"nghiên cứu 9". Thực tế repo có 20 agent và khối nghiên cứu có 6. `ux-designer` chưa bao giờ được tạo:
thay vào đó lĩnh vực này được giao bằng skill `ui-ux-design` cho frontend, mobile, researcher và spec-writer.

Một ADR đã Accepted mà mô tả sai hệ thống thì nguy hiểm hơn là không có ADR: người đọc sau sẽ đi tìm
một agent không tồn tại, hoặc tưởng có ai đó đang sở hữu thiết kế UX.

## Quyết định
Giữ nguyên 20 agent. Không tạo `ux-designer`.

Lý do: đầu ra thiết kế (flow, design token, trạng thái rỗng/lỗi/tải) luôn phải đi kèm code màn hình mới
kiểm chứng được. Tách thành agent riêng thì thêm một vòng envelope và một điểm chờ giữa thiết kế và hiện
thực, trong khi phần lớn giá trị nằm ở checklist — thứ mà skill đã chuyển tải được. Nếu về sau xuất hiện
đủ bằng chứng (frontend và mobile lệch nhau về design token, hoặc gate accessibility trượt lặp lại) thì mở
ADR mới để tách, chứ không âm thầm dựa vào ADR-0003.

Ba agent còn lại của ADR-0003 — `security-engineer`, `platform`, `data` — đã được tạo đúng như quyết định.

## Hệ quả
- Quân số đúng: nghiên cứu 6, quản lý 1, kỹ thuật 6, chất lượng 3, vận hành 3, giám sát 1 = 20, cộng human gate.
- Namespace `design` do `researcher` sở hữu (`context_namespace_write: [glossary, design]`, và `NAMESPACE_OWNERS`
  trong `src/company/events.py`) — không phải "không ai sở hữu" như bản đầu của ADR này ghi.
- Researcher nạp skill `ui-ux-design` ở mức đầy đủ với tư cách chủ quản (ADR-0016: mỗi skill phải có ít nhất một
  agent nạp đầy đủ). Frontend và mobile hiện thực thiết kế, nạp `ui-ux-design` mức rút gọn và `accessibility`
  mức đầy đủ (ADR-0008).
- `test_registry.py` khoá con số 20; ADR-0003 phải đọc kèm ADR này.
