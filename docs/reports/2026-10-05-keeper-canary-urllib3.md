# BT8 — canary với cảnh báo urllib3 thật

Ngày 05/10/2026. Ticket `KEEP:8ab7ab2bc2b840bf99b57008369e2b6e`, risk high.

## Nguồn và giới hạn

GitHub Dependabot có ba cảnh báo đang mở cho urllib3 2.7.0: GHSA-8988-9cw3-xx77,
GHSA-vxq7-64xx-v4gw và GHSA-gh4c-6fx4-qh6g. Cả ba chỉ ra phiên bản vá 2.8.0.
Nguồn: API repo và [release upstream](https://github.com/urllib3/urllib3/releases/tag/2.8.0).

Phiên chính nhập kết quả API thật qua `submit_signal` của keeper; đây là adapter ingestion thủ công,
không phải bằng chứng watcher dependency tự phát hiện. Keeper triage thành ticket high, đòi gate.
Chủ repo giao toàn quyền quyết định kỹ thuật trong chat ngày 05/10. Gate ghi rõ quyết định được thực thi
thay chủ repo, không coi đó là một lượt review độc lập.

## Patch và phép đo

`uv lock --upgrade-package urllib3` nâng duy nhất urllib3 lên 2.8.0 trong lockfile. `apply_edits` của
keeper kiểm đường dẫn và phát patch proposal. Không đổi manifest vì requests kéo urllib3 bắc cầu.

Test đọc lock thật và kiểm phiên bản vá cả ba advisory. `collect_two_way` cất toàn bộ patch trong
worktree ticket, chạy pytest đỏ với 2.7.0, khôi phục patch rồi chạy xanh với 2.8.0. Danh tính cây đo được
gắn vào verification report; publish kiểm lại danh tính trước từng push, kể cả commit điền số PR.

Rà họ: không có pin trực tiếp urllib3 ở pyproject.toml; chỉ lock cần đổi. Quét mã các công ty/platform
không thấy dùng tùy chọn HTTPS proxy forwarding/TLS custom của urllib3. Thư viện vẫn được cập nhật để
đóng các đường xử lý chung, không suy từ việc không dùng một tùy chọn thành miễn trừ advisory.

Hạn mức canary riêng `KEEPER_MAX_PR_PER_WEEK=30` được chủ repo ủy quyền: tại lúc đo có 28 PR repo merge
trong tuần, mặc định 5 đã hết. Vẫn giữ cổng một PR mở, high gate, bằng chứng hai chiều và coverage 100%.
Không sửa mặc định trong mã hay hạ coverage.

## Chứng cứ lưu tại máy vận hành

Bus keeper và log chứa dữ liệu vận hành ở ngoài Git. Nhật ký hai chiều, pip-audit và cổng CI được lưu
trong thư mục evidence ngày 05/10. Không commit bus hoặc cấu hình riêng. PR chỉ mang lock và báo cáo
công khai này cùng CHANGELOG/session theo luật repo. Việc mở PR cần đi qua `KeeperOrchestrator.publish`,
việc merge được chủ repo quyết định; keeper không có quyền merge.
