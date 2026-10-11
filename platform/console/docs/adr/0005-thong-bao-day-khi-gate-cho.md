# ADR-0005 — Thông báo đẩy khi có gate mới chờ người

Ngày: 2026-10-11 · Trạng thái: chấp nhận · Thay thế: không · Liên quan: ADR-0002 (địa chỉ là trạng thái — link
mở đúng ngăn kéo gate), ADR-0003 (ô rỗng là ô xám — trạng thái đo được), ADR-0004 (động cơ: con chết cùng cha)

## Bối cảnh

Console biết một gate đang chờ bao lâu: `remind_at` 12 giờ tô vàng, `timeout` 24 giờ tô đỏ (`collect.py`
`gates()`). Nhưng hai màu đó chỉ có nghĩa với **người đang mở trang**. Người trực rời máy — đi ngủ, đi làm việc
khác — thì gate chờ hàng giờ mà không ai hay. Đây là cùng một "chế độ hỏng im lặng" ADR-0004 đã gọi tên cho động
cơ: không lỗi, không dấu hiệu, công ty đứng im chờ một chữ ký.

Đo trước khi quyết (2026-10-11, câu hỏi vận hành *"nên vận hành X-Agents theo cách nào"*):

- Lớp luôn chạy đã có: hub container (ADR gốc 0013) chạy `orchestrator run --watch` + console.
- Lớp người trực đã có: console là PWA, `#/truc-ban/gate/<id>` mở đúng ngăn kéo (ADR-0002), ký gate đi qua
  `HumanGate` (ADR-0001).
- Mảnh thiếu duy nhất giữa hai lớp: **không có gì gọi người** khi gate xuất hiện. Gate `release` của REL-001 trong
  fixture test đã chờ 30 giờ — con số đó có trên trang, nhưng trang không có ai nhìn.

Hai điều kiện đo tiếp sau khi áp (ghi ở `docs/thi-hanh/tb1.md`): thời gian `gate.request` → `gate.decide` trước và
sau khi bật thông báo; tỉ lệ tin hỏng (`failed / (sent + failed)`) trong `/api/state.notify`.

## Quyết định

`src/console/notify.py`: một `Notifier` gửi tin ra **ntfy** (POST văn bản vào một topic) hoặc **Telegram** (bot
`sendMessage`) qua `urllib` thư viện chuẩn; một `NotifyWatcher` là thread nền dò dấu vân tay bus đúng như
`/api/stream` rồi gọi `collect()` khi bus đổi, **không cần ai mở trang**. Bật bằng cờ `--notify-ntfy URL` /
`--notify-telegram CHAT_ID` (+ `--public-url` để link trong tin mở được từ điện thoại). Trạng thái đi kèm
`/api/state` và `/api/stream` dưới khoá `notify`.

Năm ràng buộc là một phần của quyết định:

1. **Chỉ đọc.** Nguồn duy nhất là `collect(...)["gates"]` — hàng đợi gate của cả hai xưởng, gồm cả câu hỏi làm rõ
   (`kind=clarification`). Console vẫn không dựng event, không ghi bus (ADR-0001).
2. **Một gate mới = một tin; khởi động = một tin tóm tắt.** Bộ nhớ "đã báo" chỉ giữ những gate còn đang chờ: gate
   bị từ chối rồi mở lại cùng id là một lượt chờ người mới → báo lại. Không báo lại gate đã báo, không nhắc định kỳ
   (nhắc định kỳ là việc khác, có điều kiện quay lại ở `tb1.md`).
3. **Không bao giờ ném ra ngoài.** Mạng hỏng, 5xx, timeout là `failed += 1` và `last_error` (tên kênh + mã lỗi);
   thread không chết, server không chết, `collect()` ném thì lần sau thử lại.
4. **Bí mật không đi qua dòng lệnh, không vào log, không vào `status()`.** Token Telegram chỉ đọc từ env
   `CONSOLE_TELEGRAM_TOKEN` (dòng lệnh thì `ps` thấy); URL Telegram (mang token) không bao giờ xuất hiện trong
   `last_error`, `repr`, hay log. Topic ntfy bắt buộc `https://` trừ máy chủ tự host trên loopback. Link trong tin
   là `--public-url` + hash, **không mang token phiên** — trang `/` tự chèn token khi mở.
5. **Trạng thái đo được** (ADR-0003): `notify` khai `enabled`, `channels`, `sent`, `failed`, `last_error`,
   `last_sent_at`, `watching`. Không có trường "đã bật"; không kênh nào thì `enabled: false` nằm ngay trong payload,
   không im.

## Phương án đã cân nhắc

- **Chỉ gửi khi có trình duyệt nối `/api/stream`** (móc vào vòng SSE sẵn có, không thêm thread). Rẻ nhất, nhưng
  sai mục đích: lúc cần gọi người nhất là lúc **không ai** mở trang. ADR-0004 đã loại thread cho *động cơ* vì
  exception trong vòng agent giết mặt kính; ở đây thread chỉ đọc và nuốt mọi lỗi vào số đếm, rủi ro đó không có.
- **Để orchestrator của từng công ty tự gửi** khi ghi `gate.request`. Gần nguồn hơn, nhưng mỗi công ty một bản cấu
  hình kênh, và link ngăn kéo gate là của console — chỉ console biết `#/truc-ban/gate/<id>` và hợp nhất hàng đợi
  hai xưởng. Console cũng là nơi duy nhất người trực đã cấu hình.
- **Webhook chung (POST JSON tới URL bất kỳ)** thay vì hai kênh cụ thể. Linh hoạt hơn nhưng không ai dùng được
  ngay trên điện thoại mà không tự dựng thêm một dịch vụ; ntfy (không tài khoản) và Telegram (phổ biến) phủ đủ
  người trực hiện có. Thêm kênh = một lớp `send(msg, post)` nữa.
- **Duyệt gate ngay trong Telegram** (nút Approve). Đổi ranh giới ai được ký (`HumanGate` allowlist, four-eyes,
  token phiên) — việc riêng, cần ADR riêng, và chỉ đáng khi đo thấy mở console trên điện thoại là điểm nghẽn thật.
- **Nhắc lại định kỳ gate quá hạn.** Dễ thành dội tin; chờ đo `gate.request → gate.decide` sau khi có tin lần đầu.

## Hệ quả

- Người trực nhận một tin trên điện thoại trong ~1 giây sau khi gate xuất hiện, bấm là mở đúng ngăn kéo (cần
  `--public-url` trỏ địa chỉ console nhìn từ ngoài — tunnel/VPN là việc của hạ tầng, không phải của console).
- Console có thêm một thread nền khi bật; chết cùng server (`server_close`), như động cơ.
- `/api/state` thêm khoá `notify`; trang chưa vẽ ô cho nó (lấy sau khi có ô "Thông báo" ở màn Trực ban — điều kiện:
  `failed > 0` xảy ra thật mà người trực không biết).
- Hai kênh gọi ra Internet từ tiến trình console. Nội dung tin: tên xưởng, `kind`, `subject_id`, tiêu đề ticket, hậu
  quả duyệt, link. Không có checklist, không có bằng chứng, không có token.
