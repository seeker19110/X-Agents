# ADR-0002: Cấu trúc 7 khối, 18 agent

Trạng thái: Accepted, đã đính chính bởi ADR-0009 · Ngày: 2026-09-02

> Đính chính: con số 18 trong tiêu đề và bảng dưới là con số gốc, nay sai. Thực tế 20 agent
> (nghiên cứu 6, quản lý 1, kỹ thuật 6, chất lượng 3, vận hành 3, giám sát 1), theo ADR-0003,
> ADR-0006 và ADR-0009. Tên file giữ nguyên vì lịch sử ADR là bất biến.

## Quyết định
Nghiên cứu 8, quản lý dự án 1, kỹ thuật 4, chất lượng 2, vận hành 2, giám sát 1, human gate (con số gốc, nay sai — xem đính chính ở trên).

## Lý do gộp
- Delivery lead gộp Architect + PM + Tech lead: cùng nguồn thông tin, tách ra chỉ tăng chi phí đồng bộ.
- Reviewer gộp code review + security: cùng đọc diff, khác checklist.
- QA gộp test + debugger: người chạy test là người có ngữ cảnh lỗi tốt nhất.
- Release engineer gộp integrator + devops: cùng sở hữu pipeline.
- Supervisor gộp watchdog + cost + knowledge: cùng subscribe audit-log.

## Lý do giữ nguyên
- Nghiên cứu giữ 8 (nay 6, sau khi ADR-0006 gộp bốn agent nghiên cứu) vì mỗi agent có nguồn dữ liệu khác nhau (web, repo, tài liệu, người).
- Kỹ thuật giữ 4 (nay 6, sau ADR-0003) vì skill và tool khác hẳn nhau.
