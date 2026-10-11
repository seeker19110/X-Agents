# ARCHITECTURE.md — console

```
trình duyệt (index.html, một file; PWA cài được; hash route #/<màn>[/gate|ticket/<id>])
   │  fetch + SSE /api/stream (đẩy trước, lùi về hỏi lại 10s khi đứt)
   ▼
server.py ── http.server thư viện chuẩn · token phiên mỗi lần chạy · cờ --allow-decide/--allow-submit/--allow-config
   │           không cờ → POST 403; mặc định 127.0.0.1, ra ngoài cần --i-know
   ├── collect.py ── đọc SQLite mode=ro của software-company + keeper: gate, ticket, PR, review, audit, chi phí, pool
   ├── truth.py ──── "sự thật giao hàng": phễu release, phễu SẢN PHẨM (ô rỗng = xám), bế tắc im lặng, quyết định chưa áp
   ├── git_truth.py  commit vượt nhánh tích hợp: `git rev-list --count` (chỉ đọc; repo đọc từ audit `project.repo`)
   ├── brief.py ──── hồ sơ gate_brief cho ngăn kéo gate → gọi thẳng `company.gate_brief` (chỉ đọc)
   ├── decide.py ─── duyệt gate → HumanGate của công ty (four-eyes, allowlist, audit-log giữ nguyên)
   ├── submit.py ─── việc mới → SQLiteBus của công ty (JSON Schema kiểm như CLI publish)
   ├── settings.py ─ đọc/ghi llm.yaml của công ty (giữ .bak); CLI `models`
   └── notify.py ─── thread nền: bus đổi → collect() → gate MỚI chờ người → ntfy/Telegram kèm link ngăn kéo (ADR-0005)
```

Bảy màn: trực ban · phễu sản phẩm · phần mềm · công ty bảo trì · chi phí · nhật ký · cài đặt (+ hướng dẫn). Console
**hiển thị và publish**, không điều phối: không có `orchestrator run --watch` của công ty thì mọi thứ nó gửi nằm im
trên bus.

Nguyên tắc thiết kế màn hình rút từ vận hành thật (`TRAPS.md`, chốt ở ADR-0003): mỗi ô trả lời một câu hỏi của
người trực; ô không có dữ liệu là ô XÁM chứ không xanh; tách sự thật git khỏi nhãn FSM; gate hiện `kind` và hậu quả
CẢ HAI CHIỀU; bằng chứng phải rẻ hơn chữ ký; console không giữ nguồn sự thật nào của riêng nó.
