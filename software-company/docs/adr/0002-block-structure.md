# ADR-0002: Cấu trúc 7 khối, 18 agent

Trạng thái: Accepted · Ngày: 2026-09-02

## Quyết định
Nghiên cứu 8, quản lý dự án 1, kỹ thuật 4, chất lượng 2, vận hành 2, giám sát 1, human gate.

## Lý do gộp
- Delivery lead gộp Architect + PM + Tech lead: cùng nguồn thông tin, tách ra chỉ tăng chi phí đồng bộ.
- Reviewer gộp code review + security: cùng đọc diff, khác checklist.
- QA gộp test + debugger: người chạy test là người có ngữ cảnh lỗi tốt nhất.
- Release engineer gộp integrator + devops: cùng sở hữu pipeline.
- Supervisor gộp watchdog + cost + knowledge: cùng subscribe audit-log.

## Lý do giữ nguyên
- Nghiên cứu giữ 8 vì mỗi agent có nguồn dữ liệu khác nhau (web, repo, tài liệu, người).
- Kỹ thuật giữ 4 vì skill và tool khác hẳn nhau.
