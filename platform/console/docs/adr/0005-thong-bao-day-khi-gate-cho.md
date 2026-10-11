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
- `/api/state` thêm khoá `notify`; ô "Thông báo" ở màn Trực ban vẽ nó — xem Bổ sung dưới.
- Hai kênh gọi ra Internet từ tiến trình console. Nội dung tin: tên xưởng, `kind`, `subject_id`, tiêu đề ticket, hậu
  quả duyệt, link. Không có checklist, không có bằng chứng, không có token.

## Bổ sung 2026-10-11 — ô "Thông báo" ở màn Trực ban

Trạng thái `notify` có trong `/api/state` nhưng không ô nào vẽ: kênh hỏng (token Telegram sai, topic ntfy gõ nhầm)
thì `failed` tăng trong JSON mà người trực vẫn tin là mình sẽ được báo. Đó là hỏng im lặng thứ hai, nằm ngay trong
lớp sinh ra để chống hỏng im lặng.

Quyết định: ô "Thông báo" ngay dưới ô Động cơ (hai câu "công ty có chạy không" và "rời máy tôi có được báo không"
đứng cạnh nhau). **Mức do tầng dữ liệu tính**, như `empty=True` của phễu sản phẩm (ADR-0003): `Notifier.verdict()`
trả `{level, say}`, `level` thuộc tập đóng `VERDICT_LEVELS = (off, good, warn, crit)`; `static/js/notify.js` chỉ tra
pill theo `level` và in `say`. Thứ tự (chỗ đầu tiên khớp thắng):

| Mức | Khi | Vì sao không xanh |
|---|---|---|
| `off` (xám) | không kênh nào | không có gì canh — số 0 ở đây là số của một việc không diễn ra, nên ô không in số |
| `crit` | đọc hàng đợi gate hỏng (`watch_error`) | gate mới không được thấy thì không được báo |
| `crit` | có kênh mà **lần gửi gần nhất** qua nó hỏng (`failing`) | người trực có thể chỉ theo dõi đúng kênh đó |
| `warn` | `--public-url` là loopback | tin tới điện thoại nhưng link không mở được |
| `warn` | chưa gửi được tin nào | kênh chưa được chứng minh là thông (xanh vì rỗng) |
| `good` | còn lại | đã gửi được, lần cuối lúc nào |

`failing` là trạng thái hiện tại từng kênh, không phải lịch sử: gửi lại được thì hết đỏ, còn `failed` (đếm từ khi
console chạy) vẫn giữ. Lỗi đọc bus tách khỏi lỗi kênh (`watch_error` ≠ `last_error`), đọc lại được thì xoá.

Phương án đã loại: tính mức trong JS (không test được — CI không chạy JS, repo kiểm giao diện bằng phép đọc mã
nguồn; và lặp lại đúng thứ ADR-0003 cấm: CSS đoán trạng thái); nút "Gửi thử" (việc riêng lúc đó — làm ở Bổ sung 2).

Đo bằng trình duyệt thật (Chromium headless, bus thật, ntfy giả trên loopback): bốn mức hiện đúng, 0 lỗi JS; thêm
một gate `escalation` vào bus đang chạy → tin đi trong ~1 giây với link `#/truc-ban/gate/TCK-112`, ô chuyển "Đã gửi
2 tin". Ảnh chụp lần đầu lộ hai chỗ đọc sai — ô `off` vẫn in "đang canh 0 gate · đã gửi 0 tin", ô `crit` in cùng
một lỗi hai lần — cả hai có test riêng (`test_static_ui.py`).

## Bổ sung 2 (2026-10-11) — nút "Gửi thử" trên ô Thông báo

Ô Thông báo đứng vàng "chưa gửi tin nào" cho tới gate thật đầu tiên — có thể nhiều ngày. Người vừa khai kênh cần
biết NGAY là tin có tới điện thoại không; chờ gate thật để phát hiện topic gõ nhầm là phát hiện lúc đã muộn.

Quyết định: nút **Gửi thử** (chỉ vẽ khi có kênh) → `POST /api/notify/test` body `{by}` → `Notifier.send_test(by)`.

- **Quyền là cờ `--notify-*`, không thêm `--allow-*`.** Đây là ngoại lệ có chủ đích của "chỉ đọc là mặc định"
  (`CLAUDE.md` của console, điều 2): người chạy console đã khai kênh là đã cho phép console gửi tới kênh đó; tin
  thử không đụng bus, không đụng `HumanGate`, không đụng repo khách — không có gì để khoá thêm. Không kênh → 409.
- **Nội dung do server dựng.** Tiêu đề cố định `Tin thử từ console X-Agents`, link `<public_url>/#/truc-ban` (cùng
  link với tin tóm tắt — thử luôn được `--public-url`). Thứ duy nhất từ client là `by`: ký tự điều khiển thành dấu
  cách, cắt `BY_MAX` = 64 ký tự — không bẻ được dòng thành tiêu đề giả, không dài vô hạn.
- **Giãn cách** `TEST_COOLDOWN` = 30 giây giữa hai lần thử (đếm cả lần hỏng) → 429 "thử lại sau N giây". Bấm lặp
  không thành spam điện thoại; khoá cùng lượt kiểm–ghi nên hai cú bấm đồng thời không cùng lọt.
- **Tin thử là bằng chứng như tin thật.** Kết quả đi vào `sent`/`failing` như mọi tin: tới được thì ô vàng → xanh,
  không tới thì ô đỏ ngay, kèm kết quả từng kênh `{channel, ok, error}` trả về cho nút. `status()` thêm
  `last_test_at`. Không đụng `_seen` — gate đang chờ vẫn được báo như trước.
- Vẫn cần token phiên (401) như mọi `/api/*`.

Phương án đã loại: cờ `--allow-notify-test` riêng (thêm một cờ để mở một việc mà cờ `--notify-*` đã nói rõ ý; người
chạy chỉ đọc + có kênh sẽ phải chạy lại console chỉ để thử); gửi thử tự động lúc khởi động (tin rác mỗi lần chạy
lại, và không trả lời được "kênh còn thông không" về sau); cho client gửi nội dung tin (biến console thành relay).

Đo bằng Chromium headless + ntfy giả trên loopback: ô vàng → bấm → "ntfy:…: tới", ô xanh "Đã gửi 1 tin"; bấm lại →
"vừa gửi thử; thử lại sau 30 giây"; kênh trỏ cổng chết → ô đỏ, "không tới (URLError)"; không kênh → không có nút.
