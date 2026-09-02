# ADR-0018: Blackboard phân vùng theo dự án

Trạng thái: Accepted · Ngày: 2026-09-02

## Bối cảnh
`shared-context` dùng `namespace` làm key toàn cục. Một công ty gia công phục vụ nhiều khách cùng lúc:
hai dự án chạy trên cùng bus sẽ ghi đè `prd`, `architecture`, `api-contract` của nhau, và agent của dự án B
đọc phải PRD của dự án A mà không có gì báo lỗi. Đây là rò rỉ dữ liệu giữa khách hàng, không chỉ là lỗi kỹ thuật.

## Quyết định
Artifact trên blackboard thuộc về một dự án: `SharedContext.project_id`, trạng thái giữ theo `(project_id, namespace)`,
key của event là `<project_id>/<namespace>`.

Ngoại lệ là `GLOBAL_NAMESPACES = {knowledge}`: bài học estimate-vs-actual có giá trị vì được dùng chung cho mọi dự án,
nên nó giữ `project_id=None` và key trần `knowledge`.

Runner dựng ngữ cảnh cho agent bằng `snapshot(project)` của đúng dự án trong envelope đầu vào. Event không mang
`project_id` (release-events, review-results, pull-requests) được orchestrator tra ngược qua ticket hoặc release
(`Orchestrator.project_of`) và điền vào payload trước khi gọi agent.

## Hệ quả
- Agent chỉ thấy artifact dự án mình, cộng các namespace toàn công ty. Không cần đổi prompt.
- `Blackboard.read`/`snapshot` nhận thêm `project_id`; gọi không truyền thì chỉ thấy phần toàn công ty.
- Replay theo key vẫn lọc được theo dự án nhờ tiền tố key.
- Nhiều orchestrator chạy song song theo dự án về sau sẽ không tranh nhau namespace.
