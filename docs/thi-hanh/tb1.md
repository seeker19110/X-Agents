# tb1 — Thông báo đẩy khi có gate mới chờ người

Ngày lập 2026-10-11 · căn cứ `main@a13bcf2` (#426) + PR #427 (df1) · đề bài: *"nên vận hành X-Agents theo cách
nào?"* → trả lời ba lớp (luôn chạy: hub container · người trực: console PWA + thông báo · kỹ sư: phiên Claude) → *"ok
triển khai lớp thông báo đẩy khi gate pending"*.

## A. Hiện trạng

### A1. Kết luận

- Lớp luôn chạy và lớp người trực đều đã có (ADR gốc 0013; console ADR 0001–0004). Mảnh thiếu duy nhất: **không có
  gì gọi người** khi gate xuất hiện — `remind_at`/`timeout` chỉ tô màu cho người đang mở trang.
- Không xây desktop app (console đã là PWA), không vận hành trong phiên chat (phiên bị thu hồi, model đắt làm việc
  rẻ, không ký gate thay người được).

### A2. Đo trước khi làm

| Câu hỏi | Nguồn | Kết quả 2026-10-11 |
|---|---|---|
| Console có gửi gì ra ngoài khi gate chờ không | `grep -rn "remind\|notify" platform/console/src` | không — `remind_at` chỉ đổi `sev` |
| Có chỗ nào hợp nhất hàng đợi gate hai xưởng + link ngăn kéo | `collect()["gates"]`, hash `#/truc-ban/gate/<id>` (ADR-0002) | có — console là nơi duy nhất |
| Vòng dò bus có sẵn chạy không cần trình duyệt | `server.py` `_api_stream` | không — chỉ chạy khi có client SSE |

## B. Kế hoạch

| Mã | Việc | Mảng | Mức | Khi nào |
|---|---|---|---|---|
| N1 | ADR-0005; `notify.py`: `Notifier` (ntfy, Telegram), `NotifyWatcher` thread nền, `build_notifier` | console | C2 | xong (commit này) |
| N2 | Nối `ConsoleServer` (`notifier=`, `notify_watcher`, `server_close`), khoá `notify` trong `/api/state`; cờ CLI + banner | console | C2 | xong (commit này) |
| N3 | Tài liệu: ADR, CODEMAP, CLAUDE.md, API.md, ARCHITECTURE, README console, README gốc, HUONG-DAN §8, CHANGELOG | docs | C1 | xong (commit này) |
| L1 | Ô "Thông báo" ở màn Trực ban (hiện `sent`/`failed`/`last_error`) | console | C1 | **lấy sau**: khi `failed > 0` xảy ra thật mà người trực không biết — đo `/api/state.notify.failed` |
| L2 | Nhắc lại định kỳ gate quá hạn (`sev == over`) | console | C1 | **lấy sau**: khi đo thấy `gate.request → gate.decide` trung vị vẫn > 12 h sau một tuần có tin lần đầu |
| L3 | Duyệt gate từ trong tin (nút Telegram) | console+core | C3 | **lấy sau**: ADR riêng; chỉ khi mở console trên điện thoại là điểm nghẽn đo được |
| L4 | Kênh thứ ba (webhook JSON chung / email) | console | C1 | **lấy sau**: khi có người trực không dùng được ntfy lẫn Telegram |

**Cố ý không làm**: để orchestrator từng công ty tự gửi (mất link ngăn kéo, nhân đôi cấu hình); webhook chung thay
hai kênh cụ thể; bất kỳ thay đổi nào ở `HumanGate`.

## C. Gói việc

### tb1-notify — ADR-0005
`src/console/notify.py` (mới), `src/console/server.py` (`notifier=`, `notify_watcher`, `state["notify"]`),
`src/console/__main__.py` (`--notify-ntfy`, `--notify-telegram`, `--public-url`, banner, `NotifyConfigError` → 2),
`tests/test_notify.py` (28 ca), `tests/test_server.py` (2 ca hợp đồng nhận khoá `notify`).

Đo hai chiều: 28 ca đỏ trước (`ImportError: cannot import name 'notify'`, rồi `make_server() got an unexpected keyword
argument 'notifier'`, `KeyError: 'notifier'` ở CLI), xanh sau.

## D. Đo sau khi áp

| Chỉ số | Lệnh | Mục tiêu |
|---|---|---|
| `gate.request → gate.decide` | `sqlite3 company.sqlite` trên `audit-log`, ghép theo `subject_id` | trung vị giảm so với tuần trước khi bật |
| tỉ lệ tin hỏng | `curl -H "X-Console-Token: …" /api/state \| jq .notify` | `failed / (sent + failed)` < 5 % |

## F. Nhật ký

- 2026-10-11: N1–N3 xong trong một commit; cổng console xanh (xem CHANGELOG). PR mở sau khi #427 (df1) merge để
  không chồng lên PR đang chờ.
