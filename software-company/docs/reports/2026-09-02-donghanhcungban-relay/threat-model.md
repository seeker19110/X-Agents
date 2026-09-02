# Threat Model v1 — Bản demo DHCB

- project_id: DHCB
- Phiên bản: 1.0
- Ngày: 2026-09-02
- Tác giả: security-engineer (chế độ threat-model, trước ticket đầu tiên)
- Đầu vào: `approved-specs` key=DHCB (PRD 1.0, requirements 1.0, ADR-001..ADR-006, glossary), ticket DHCB-004 (sổ rủi ro RSK-01..RSK-12, ACC-01..ACC-02)
- Phạm vi: BẢN DEMO chạy cục bộ, Python thuần (thư viện chuẩn), SQLite cục bộ, không đăng nhập, không thanh toán, không triển khai công khai (W-01, W-02, W-11).
- Giới hạn bằng chứng: lời gọi này KHÔNG có tool — không đọc repo, không chạy SAST/SCA/secret-scan, không tra cứu văn bản pháp luật. Mọi kết luận dưới đây là phân tích trên spec; phần cần bằng chứng máy móc được ghi rõ là "chưa kiểm chứng" và chuyển sang release-check.
- Mức ASVS áp dụng: L1 cho bản demo cục bộ (không xác thực, không dữ liệu thật). Bản đầy đủ nhận dữ liệu cá nhân thật phải nâng lên L2 và làm lại mô hình này.

## 0. Bốn câu hỏi khung
- Đang xây cái gì: ba trang HTML tĩnh sinh bằng hàm Python + một form đăng ký tình nguyện viên ghi vào SQLite cục bộ, phục vụ bằng `http.server`.
- Cái gì có thể sai: xem T-01..T-14 dưới đây.
- Sẽ làm gì với nó: 12 biện pháp ánh xạ về M-03..M-12, S-02, S-04, S-05, ADR-004..ADR-006; 2 rủi ro chấp nhận có ADR.
- Đã đủ tốt chưa: đủ cho phạm vi demo cục bộ. KHÔNG đủ cho bất kỳ lần chạy nào có mạng ngoài hoặc dữ liệu thật — điều kiện xem lại ghi ở §7.

## 1. Tài sản cần bảo vệ
| id | Tài sản | Vì sao đáng bảo vệ |
|---|---|---|
| A-01 | Bản ghi đăng ký trong tệp SQLite (họ tên, số điện thoại, email, khu vực, lý do, consent, timestamp) | Dù spec nói là dữ liệu mô phỏng (CST-03), người đóng vai vẫn có thể nhập dữ liệu thật của chính họ. Cấu trúc dữ liệu là PII. |
| A-02 | Tệp SQLite trên đĩa máy trình diễn | Bản sao dữ liệu tồn tại sau buổi demo nếu không xoá (ASM-04 là thao tác thủ công, không phải chức năng). |
| A-03 | Log ứng dụng | Là kênh rò rỉ PII nằm ngoài phạm vi xoá (RSK-10). |
| A-04 | Tính toàn vẹn nội dung trang hiển thị cho đại diện khách | Trang bị chèn nội dung/HTML làm hỏng buổi nghiệm thu và tạo hiểu nhầm về tổ chức (RSK-04). |
| A-05 | Uy tín và danh tính tổ chức DHCB | Nội dung mẫu chưa được duyệt bị hiểu là công bố chính thức (RSK-04, RSK-06, CST-04). |
| A-06 | Máy trình diễn (host chạy `http.server`) | Chuỗi tấn công path traversal / SSRF nội bộ nếu server bind ra ngoài loopback. |
| A-07 | Chuỗi cung ứng mã nguồn (repo, CI ở S-05) | Secret vô tình commit, dependency lạ len vào dù CST-01 cấm gói ngoài. |

## 2. Kẻ tấn công giả định (cụ thể, không chung chung)
- ATK-01 — Người ngồi cùng mạng LAN/Wi-Fi tại buổi trình diễn, không xác thực: nếu `http.server` bind `0.0.0.0`, họ mở được trang và gửi được POST đăng ký.
- ATK-02 — Chính người đóng vai điền form (người dùng hợp lệ): gửi payload dị dạng, chuỗi rất dài, ký tự điều khiển, `<script>`, `=SUM(...)`.
- ATK-03 — Người dùng khác trên cùng máy trình diễn (multi-user OS): đọc trực tiếp tệp SQLite nếu quyền tệp là mặc định 0644.
- ATK-04 — Nội bộ đội dự án: commit nhầm tệp `.db` chứa dữ liệu buổi demo lên repo (ADR-002 cấm nhưng chưa có kiểm soát kỹ thuật).
- ATK-05 — Chuỗi cung ứng: một gói ngoài được thêm lén dù CST-01 cấm; hoặc CI (S-05) chạy action bên thứ ba không ghim phiên bản.
- ATK-06 — Người xem demo hiểu nhầm (không ác ý nhưng gây thiệt hại): tưởng trang là trang chính thức, chia sẻ ảnh chụp màn hình.
- KHÔNG áp dụng trong phạm vi này: kẻ tấn công đa khách (không có tenant), kẻ tấn công qua cổng thanh toán (W-02), qua kênh nhận bên thứ ba (W-04).

## 3. Data-flow diagram (DFD) với ranh giới tin cậy

Ký hiệu: `[EE]` thực thể ngoài · `(P)` tiến trình · `{DS}` kho dữ liệu · `==TB-n==` ranh giới tin cậy (trust boundary).

```
                       ==TB-1: biên mạng máy trình diễn (loopback vs LAN)==
 [EE-1 Khách xem/đóng vai]  --F1: GET /, /gioi-thieu, /dang-ky (HTTP, plaintext)-->  (P1 http.server handler)
 [EE-1]                     --F2: POST /dang-ky (form-urlencoded: họ tên, SĐT, email, khu vực, lý do, consent)--> (P1)
 [EE-2 Người xem cùng LAN]  --F3: truy cập trái phép nếu bind 0.0.0.0-->            (P1)

                       ==TB-2: biên tiến trình ứng dụng (dữ liệu chưa tin cậy -> logic)==
 (P1) --F4: dict tham số thô--> (P2 validate_registration)
 (P2) --F5: dữ liệu đã kiểm/chuẩn hoá--> (P3 submit_registration)
 (P2) --F6: danh sách lỗi (chỉ TÊN trường, không giá trị)--> (P4 render_html)
 (P3) --F7: INSERT tham số hoá--> {DS-1 SQLite dhcb.db}
 (P3) --F8: sự kiện (submit_ok / submit_rejected + tên trường)--> {DS-2 Log ứng dụng}
 (P4) --F9: HTML đã escape--> (P1) --F10: HTTP 200/400 --> [EE-1]

                       ==TB-3: biên lưu trữ trên đĩa (tiến trình vs hệ tệp / người dùng OS khác)==
 {DS-1} <--F11: đọc tệp trực tiếp-- [EE-3 Người dùng OS khác / công cụ sao lưu / git]
 {DS-2} <--F12: đọc log-- [EE-3]

                       ==TB-4: biên chuỗi cung ứng (repo/CI vs môi trường chạy)==
 [EE-4 Repo GitHub + CI (S-05)] --F13: mã nguồn, workflow--> (P1..P4)
```

Luồng cắt ranh giới cần duyệt STRIDE: F1, F2, F3 (qua TB-1); F4, F5, F6 (qua TB-2); F7, F8, F11, F12 (qua TB-3); F13 (qua TB-4).

## 4. Giả định bảo mật (ghi tường minh — đây là nơi sự cố hay xảy ra)
- SEC-ASM-01: Máy trình diễn được coi là môi trường tin cậy vừa phải, KHÔNG phải tin cậy tuyệt đối (có thể có người dùng OS khác, có công cụ sao lưu đám mây).
- SEC-ASM-02: Mạng của buổi trình diễn KHÔNG được coi là tin cậy. Vì vậy T-01 yêu cầu bind loopback thay vì dựa vào "chỉ có người của mình trong phòng".
- SEC-ASM-03: Không có HTTPS trong phạm vi demo; chấp nhận được CHỈ KHI luồng không rời loopback (T-01 là điều kiện tiên quyết của giả định này).
- SEC-ASM-04: Dữ liệu nhập là mô phỏng theo CST-03, nhưng mô hình này vẫn xử lý A-01 như PII vì không có kiểm soát kỹ thuật nào ngăn người đóng vai nhập số điện thoại thật của họ.
- SEC-ASM-05: Không có gói ngoài (CST-01), nên bề mặt SCA gần bằng 0; giả định này phải được kiểm chứng bằng máy ở release-check, không phải bằng lời.
- SEC-ASM-06: Không có nhật ký kiểm toán (ADR-004, ACC-01/ACC-02) — mọi kết luận điều tra sau sự cố demo sẽ dựa vào trí nhớ người trình diễn.

## 5. Duyệt STRIDE theo từng luồng cắt ranh giới

### TB-1 — F1/F2/F3: trình duyệt khách ↔ `http.server`
| STRIDE | Có mối đe dọa? | Ghi chú |
|---|---|---|
| S — Spoofing | Có → T-02 | Không có xác thực (W-01), mọi người gửi form đều ẩn danh. Chấp nhận trong phạm vi demo, nhưng phải ghi ra. |
| T — Tampering | Có → T-03, T-06 | Client sửa bất kỳ trường nào, kể cả trường ẩn honeypot (S-04) và độ dài lý do; kiểm tra phía trình duyệt không có giá trị bảo mật. |
| R — Repudiation | Có → T-13 | Không log danh tính (không có danh tính để log), ADR-004. |
| I — Information disclosure | Có → T-01, T-04 | Bind ra LAN làm lộ toàn bộ A-01/A-04; traceback Python mặc định lộ đường dẫn và mã nguồn. |
| D — Denial of service | Có → T-05 | `http.server` đơn luồng; body POST không giới hạn kích thước. |
| E — Elevation of privilege | Có → T-07 | `SimpleHTTPRequestHandler` phục vụ tệp theo đường dẫn; nếu tái dùng, path traversal đọc được `dhcb.db` và mã nguồn. |

### TB-2 — F4/F5/F6: dữ liệu chưa tin cậy vào logic ứng dụng
| STRIDE | Có mối đe dọa? | Ghi chú |
|---|---|---|
| S | Không đáng kể | Trong tiến trình, không có định danh để giả mạo. |
| T | Có → T-06, T-08, T-09 | Vượt độ dài, ký tự điều khiển/NUL, chuỗi mở đầu `=`/`+`/`-`/`@` (công thức bảng tính), HTML injection. |
| R | Không đáng kể | Đã gộp vào T-13. |
| I | Có → T-10 | Thông báo lỗi (F6) có nguy cơ dội lại giá trị người dùng nhập vào HTML và vào log. |
| D | Có → T-05 | Xử lý chuỗi rất dài trước khi kiểm độ dài. |
| E | Có → T-11 | Nếu bất kỳ truy vấn nào nối chuỗi thay vì tham số hoá → SQL injection trong SQLite. |

### TB-3 — F7/F8/F11/F12: tiến trình ↔ đĩa (SQLite + log)
| STRIDE | Có mối đe dọa? | Ghi chú |
|---|---|---|
| S | Không áp dụng | Không có định danh ở tầng tệp trong phạm vi này. |
| T | Có → T-12 | Bất kỳ người dùng OS nào ghi được tệp `.db` đều sửa được bản ghi; không có checksum. |
| R | Có → T-13 | Không truy vết ai đọc/sửa tệp (ACC-02). |
| I | Có → T-04, T-12, T-14 | Quyền tệp mặc định; tệp `.db` bị commit; sao lưu đám mây tự động nuốt tệp; PII vào log. |
| D | Có (thấp) | Xoá tệp `.db` làm mất dữ liệu demo — tác động nghiệp vụ không đáng kể, chấp nhận không xử lý. |
| E | Không áp dụng | Không có phân quyền trong ứng dụng. |

### TB-4 — F13: repo/CI ↔ môi trường chạy
| STRIDE | Có mối đe dọa? | Ghi chú |
|---|---|---|
| S | Có (thấp) → T-15 | CI action không ghim phiên bản có thể bị thay thế. |
| T | Có → T-15 | Dependency ngoài len vào trái với CST-01. |
| R | Có (thấp) | Commit không ký; chấp nhận trong phạm vi demo. |
| I | Có → T-14 | Secret hoặc tệp `.db` chứa dữ liệu buổi demo bị commit. |
| D | Không đáng kể | CI hỏng không ảnh hưởng buổi trình diễn cục bộ. |
| E | Không đáng kể | Không có quyền production để leo thang (W-11). |

### LINDDUN — mối đe dọa riêng tư cho A-01 (dữ liệu cá nhân)
| LINDDUN | Đánh giá |
|---|---|
| Linkability / Identifiability | Bản ghi gồm họ tên + số điện thoại → định danh trực tiếp. Xem T-04, T-12, T-14. |
| Non-repudiation | Không áp dụng (không có nghĩa vụ chứng minh hành vi người dùng). |
| Detectability | Không đáng kể trong phạm vi cục bộ. |
| Disclosure of information | T-01, T-04, T-12, T-14. |
| Unawareness | Được xử lý bởi M-08 (trang xác nhận) + M-03 (băng-rôn) + ô consent bắt buộc (M-04, M-05). |
| Non-compliance | T-16 — nghĩa vụ NĐ 13/2023 chưa phát sinh theo ADR-003, nhưng chỉ đúng khi dữ liệu thực sự là mô phỏng; điều kiện xem lại ở §7. |

## 6. Danh mục mối đe dọa

Định dạng mỗi mục: id · chữ STRIDE · tài sản · kịch bản cụ thể · CVSS 4.0 (ước lượng, không có công cụ để kiểm chứng) · giảm nhẹ ánh xạ ASVS · yêu cầu/ticket · cách kiểm chứng · owner · trạng thái.

**T-01 · Information disclosure · A-01, A-04 · CVSS 4.0 ~5.3 (Medium)**
Kịch bản: người trình diễn chạy `python -m ...` với `HTTPServer(("", 8000), ...)`; server bind `0.0.0.0`; ATK-01 ngồi cùng Wi-Fi hội trường mở `http://<ip-máy>:8000/dang-ky`, gửi POST và cũng đọc được trang xác nhận. Không có TLS nên nội dung form đi plaintext trên LAN.
Giảm nhẹ: bind cứng `127.0.0.1` trong mã, không cho tham số hoá địa chỉ bind; README (S-02) ghi rõ demo chỉ chạy loopback (ASVS 1.1.4 kiến trúc / 14.4 cấu hình an toàn mặc định).
Yêu cầu ánh xạ: NFR-05, S-02 · Ticket đề xuất: **TCK-SEC-01** (bind loopback + dòng README).
Kiểm chứng: test khẳng định hằng số host của module bằng `"127.0.0.1"`; mục kiểm trong code review.
Owner: backend · Trạng thái: open (chưa có yêu cầu nào trong PRD phủ điều này — xem finding SEC-F-01).

**T-02 · Spoofing · A-01 · CVSS 4.0 ~2.0 (Low)**
Kịch bản: không có xác thực (W-01), ATK-02 gửi đăng ký dưới tên người khác; không cách nào phân biệt.
Giảm nhẹ: chấp nhận rủi ro — dữ liệu là mô phỏng, không có hệ quả nghiệp vụ (ASVS 1.2 không áp dụng ở L1 không xác thực).
Yêu cầu ánh xạ: W-01 · Ticket: không · Trạng thái: **accepted** (nằm trong phạm vi Won't đã ký ở Gate 2, không cần ADR riêng).

**T-03 · Tampering · A-01 · CVSS 4.0 ~4.3 (Medium)**
Kịch bản: ATK-02 tắt JavaScript / dùng `curl` gửi thẳng POST, bỏ qua mọi kiểm tra `required` của trình duyệt, gửi consent=off nhưng vẫn kỳ vọng có bản ghi.
Giảm nhẹ: mọi kiểm tra bắt buộc + consent thực thi ở phía nhận, không chỉ ở HTML (ASVS 5.1.3, 5.1.4). Đã có trong spec.
Yêu cầu ánh xạ: **M-05** (từ chối + không tạo bản ghi), ADR-005 · Kiểm chứng: Gherkin M-05 (ba kịch bản, gồm ca chỉ có khoảng trắng) · Owner: backend · Trạng thái: **mitigated**.

**T-04 · Information disclosure · A-01, A-02 · CVSS 4.0 ~5.1 (Medium)**
Kịch bản: sau buổi demo, tệp `dhcb.db` nằm lại thư mục làm việc với quyền mặc định; ATK-03 (người dùng OS khác) hoặc công cụ sao lưu đám mây đọc và mang đi bản sao họ tên + số điện thoại.
Giảm nhẹ: (a) tạo tệp DB với `umask` chặt / `os.chmod(0o600)` ngay sau khi tạo; (b) README (S-02) có lệnh xoá tệp và mục kiểm sau buổi trình diễn; (c) mặc định đặt tệp DB ngoài thư mục được đồng bộ (ASVS 14.2, 8.3.4).
Yêu cầu ánh xạ: **S-02**, ASM-04 · Ticket đề xuất: **TCK-SEC-02**.
Kiểm chứng: test kiểm chế độ tệp sau `submit_registration` đầu tiên (chạy trên POSIX); mục kiểm trong checklist đóng buổi demo.
Owner: backend + người trình diễn · Trạng thái: **open** — ASM-04 hiện là thao tác thủ công không được nhắc bởi phần mềm (finding SEC-F-02).

**T-05 · Denial of service · A-06 · CVSS 4.0 ~2.3 (Low)**
Kịch bản: ATK-02 gửi POST với `Content-Length` rất lớn; handler đọc toàn bộ body vào bộ nhớ trước khi kiểm độ dài 500 ký tự; `http.server` đơn luồng nên buổi trình diễn treo.
Giảm nhẹ: từ chối request có `Content-Length` vượt ngưỡng cứng (ví dụ 64 KB) TRƯỚC khi đọc body (ASVS 12.1, 13.2.2).
Yêu cầu ánh xạ: mở rộng của M-04 · Ticket đề xuất: **TCK-SEC-03** (ưu tiên thấp).
Kiểm chứng: unit test gọi handler với header khai kích thước lớn, kỳ vọng 413.
Owner: backend · Trạng thái: **open, chấp nhận được nếu trượt** (tác động chỉ là gián đoạn demo cục bộ).

**T-06 · Tampering · A-01 · CVSS 4.0 ~3.1 (Low)**
Kịch bản: ATK-02 gửi trường `lý do` dài 100.000 ký tự để làm phình tệp SQLite và làm hỏng hiển thị trang xác nhận.
Giảm nhẹ: kiểm độ dài ≤ 500 ở phía nhận, từ chối chứ không cắt ngầm (ASVS 5.1.4).
Yêu cầu ánh xạ: **M-04** (ca biên 501 ký tự), ADR-005 · Kiểm chứng: Gherkin M-04 ca biên · Owner: backend · Trạng thái: **mitigated**.

**T-07 · Elevation of privilege · A-06, A-02 · CVSS 4.0 ~6.9 (Medium)**
Kịch bản: nếu hiện thực tái dùng `SimpleHTTPRequestHandler` để phục vụ CSS/tệp tĩnh, ATK-01 gửi `GET /../../dhcb.db` (hoặc biến thể mã hoá URL) và tải về cơ sở dữ liệu, hoặc đọc mã nguồn.
Giảm nhẹ: KHÔNG phục vụ hệ tệp; định tuyến bằng bảng đường dẫn cố định (allow-list `/`, `/gioi-thieu`, `/dang-ky`), mọi đường dẫn khác trả trang 404 của M-03 (ASVS 12.3.1, 4.1.3).
Yêu cầu ánh xạ: **M-03** (trang 404 có băng-rôn) + Gherkin M-01 đường lỗi · Ticket đề xuất: **TCK-SEC-04** (ghi rõ ràng buộc "định tuyến allow-list, không serve tệp").
Kiểm chứng: test gửi `/../dhcb.db`, `/%2e%2e/dhcb.db`, kỳ vọng 404 và thân trang không chứa byte của DB.
Owner: backend · Trạng thái: **open** (spec ngụ ý nhưng không nói tường minh — finding SEC-F-03).

**T-08 · Tampering · A-04 · CVSS 4.0 ~4.8 (Medium)**
Kịch bản: ATK-02 nhập họ tên `<img src=x onerror=alert(1)>` hoặc `"><script>...`; trang xác nhận dội lại nguyên văn → HTML/JS injection ngay trước mặt đại diện khách. Lưu ý chuỗi đó cũng nằm trong DB nên có thể bùng lại ở bản đầy đủ (stored XSS).
Giảm nhẹ: `html.escape(value, quote=True)` cho MỌI giá trị người dùng khi dựng HTML, kể cả khi đặt trong thuộc tính `value=` của form khi hiện lại lỗi (ASVS 5.3.3).
Yêu cầu ánh xạ: **M-09**, NFR-02, ADR-005 · Kiểm chứng: Gherkin M-09 · Owner: backend · Trạng thái: **mitigated**, kèm cảnh báo: M-09 mới nêu trang xác nhận, chưa nêu form-hiện-lại-lỗi ở M-06 (finding SEC-F-04).

**T-09 · Tampering · A-01 · CVSS 4.0 ~2.0 (Low, hoãn)**
Kịch bản: ATK-02 nhập lý do bắt đầu bằng `=cmd|'/c calc'!A1`; nếu bản đầy đủ xuất CSV, máy của người mở tệp thực thi công thức (CSV formula injection).
Giảm nhẹ trong demo: chỉ hiển thị dưới dạng văn bản, không xuất tệp (W-13); ghi nợ kỹ thuật để bản đầy đủ thêm tiền tố `'` khi xuất (ASVS 5.3.10).
Yêu cầu ánh xạ: **M-09** ca biên "chuỗi bắt đầu bằng dấu bằng", W-13 · Owner: backend · Trạng thái: **accepted trong phạm vi demo**, mở lại khi có chức năng xuất dữ liệu.

**T-10 · Information disclosure · A-01, A-03 · CVSS 4.0 ~4.0 (Medium)**
Kịch bản: thông báo lỗi (M-06) hoặc dòng log "từ chối" tiện tay chèn giá trị người dùng: `logger.info("reject %s", form)` → số điện thoại nằm trong log, ngoài phạm vi xoá của ASM-04. Traceback chưa bắt cũng lộ đường dẫn hệ thống cho ATK-01.
Giảm nhẹ: (a) log chỉ ghi TÊN trường lỗi, không ghi giá trị, không log nguyên request (ADR-006); (b) bắt mọi ngoại lệ ở biên handler, trả trang lỗi thân thiện, không trả traceback (ASVS 7.4.1, 8.3.4).
Yêu cầu ánh xạ: **M-10**, NFR-03, ADR-006 (đã có); phần traceback ánh xạ Gherkin M-01 đường lỗi "không báo lỗi kỹ thuật cho khách".
Kiểm chứng: test bắt log so khớp giá trị đã nhập; test gọi handler với đầu vào gây ngoại lệ, khẳng định thân trang không chứa `Traceback`.
Owner: backend · Trạng thái: **mitigated một phần** — nhánh traceback chưa có yêu cầu kiểm được (finding SEC-F-05).

**T-11 · Elevation of privilege · A-01, A-02 · CVSS 4.0 ~8.7 (High nếu xảy ra)**
Kịch bản: hiện thực viết `cur.execute("INSERT INTO dang_ky VALUES ('%s',...)" % ho_ten)`; ATK-02 nhập `', ''); DROP TABLE dang_ky;--` và xoá bảng, hoặc đọc `sqlite_master`.
Giảm nhẹ: BẮT BUỘC truy vấn tham số hoá (`?` placeholder) trong 100% truy vấn; cấm nối chuỗi SQL; bật quy tắc quét (grep/Bandit B608 hoặc mục kiểm review nếu không có công cụ) (ASVS 5.3.4).
Yêu cầu ánh xạ: chưa có yêu cầu tường minh trong PRD → **TCK-SEC-05** (ràng buộc hiện thực + test).
Kiểm chứng: test gửi họ tên chứa `'; DROP TABLE`, khẳng định bảng còn nguyên và bản ghi lưu đúng nguyên văn chuỗi đó; mục kiểm bắt buộc trong code review mọi PR chạm `submit_registration`.
Owner: backend · Trạng thái: **open** — đây là threat mức cao nhất của mô hình; nó KHÔNG chặn Gate 2 vì đã có giảm nhẹ rõ ràng và ticket, nhưng phải mitigated trước Gate 3 (finding SEC-F-06).

**T-12 · Tampering + Information disclosure · A-02 · CVSS 4.0 ~3.6 (Low)**
Kịch bản: ATK-03 mở `dhcb.db` bằng `sqlite3` CLI, sửa hoặc chép bản ghi; không có gì phát hiện được (ACC-02).
Giảm nhẹ: cùng biện pháp T-04 (quyền 0600, xoá sau buổi demo); chấp nhận phần "không phát hiện được" theo ADR-004.
Trạng thái: **accepted-with-ADR** (ADR-004, chờ delivery-lead ký — xem finding SEC-F-07).

**T-13 · Repudiation · A-01, A-03 · CVSS 4.0 ~2.0 (Low)**
Kịch bản: không biết ai đã gửi bản ghi nào, ai đã đọc tệp; sau buổi demo không dựng lại được sự việc.
Giảm nhẹ: không hiện thực trong demo.
Trạng thái: **accepted-with-ADR** — ADR-004 (ACC-01, ACC-02) đang ở trạng thái "đề xuất, chờ delivery-lead ký". Điều kiện xem lại: khi bản đầy đủ có quản lý danh sách tình nguyện viên.

**T-14 · Information disclosure · A-01, A-07 · CVSS 4.0 ~6.1 (Medium)**
Kịch bản: sau buổi demo lập trình viên chạy `git add -A`; tệp `dhcb.db` chứa họ tên và số điện thoại của người đóng vai được đẩy lên GitHub và tồn tại vĩnh viễn trong lịch sử git; xoá dòng sau đó là chưa đủ.
Giảm nhẹ: `.gitignore` chứa `*.db`/`*.sqlite3` NGAY từ ticket đầu tiên; quét secret + tệp dữ liệu trong CI (S-05); mục kiểm trong code review (ASVS 14.3.2, 1.6).
Yêu cầu ánh xạ: ADR-002 ("không được commit lên repo" — hiện chỉ là câu văn, chưa có kiểm soát), **S-05** · Ticket đề xuất: **TCK-SEC-06**.
Kiểm chứng: bước CI thất bại nếu `git ls-files` khớp `*.db`.
Owner: backend + delivery-lead · Trạng thái: **open** (finding SEC-F-08).

**T-15 · Tampering (chuỗi cung ứng) · A-07 · CVSS 4.0 ~3.1 (Low)**
Kịch bản: ai đó thêm `requirements.txt` với một gói tiện tay (vi phạm CST-01), hoặc CI ở S-05 dùng `actions/checkout@v4` không ghim SHA và upstream bị chiếm.
Giảm nhẹ: kiểm soát "không có phụ thuộc ngoài" bằng test (`import` chỉ từ thư viện chuẩn) và bằng việc CI chạy trên môi trường Python sạch không `pip install`; ghim action theo SHA nếu dùng (ASVS 14.2.1; SLSA nguồn gốc — chưa áp dụng đầy đủ ở mức demo).
Yêu cầu ánh xạ: **CST-01, NFR-04, NFR-05, S-05** · Ticket đề xuất: **TCK-SEC-07** (gộp vào ticket CI).
Kiểm chứng: job CI chạy `python -X importtime -c "import app"` trong venv trống; test danh sách module top-level.
Owner: delivery-lead · Trạng thái: **open**.

**T-16 · Non-compliance (LINDDUN) · A-01 · CVSS 4.0 — không áp dụng thang CVSS (rủi ro pháp lý)**
Kịch bản: người đóng vai tại buổi trình diễn nhập số điện thoại THẬT của chính họ; dữ liệu cá nhân thật được lưu trong khi ADR-003 tuyên bố nghĩa vụ NĐ 13/2023 "chưa phát sinh", và không có thông báo xử lý dữ liệu (W-06) lẫn quy trình xoá theo yêu cầu chủ thể (W-06).
Giảm nhẹ trong phạm vi demo: (a) ô consent bắt buộc nói rõ phạm vi "trong buổi trình diễn" (M-04, M-05); (b) trang xác nhận nêu nguyên văn "dữ liệu không được lưu lâu dài" (M-08); (c) băng-rôn demo (M-03); (d) xoá tệp sau buổi demo (S-02, ASM-04); (e) người trình diễn hướng dẫn miệng dùng dữ liệu giả.
Ánh xạ pháp lý: chưa kiểm chứng được hiệu lực và điều khoản áp dụng của NĐ 13/2023 vì lời gọi này không có mạng — trùng với OQ-04, người trả lời: researcher khi có tool. DPIA: KHÔNG bắt buộc trong phạm vi demo (dữ liệu mô phỏng, không công khai, xoá sau buổi trình diễn); BẮT BUỘC trước khi bản đầy đủ nhận dữ liệu thật (OQ-02).
Owner: delivery-lead + account-manager · Trạng thái: **accepted trong phạm vi demo**, với điều kiện xem lại ở §7.

## 7. Điều kiện bắt buộc rà lại mô hình này (bất kỳ điều nào xảy ra ⇒ threat model v2 trước khi code tiếp)
1. Demo được truy cập từ ngoài loopback, hoặc triển khai lên tên miền (đảo W-11) — T-01, T-05, T-07 đổi mức ngay.
2. Bất kỳ dữ liệu cá nhân THẬT nào được nhận — T-16 chuyển thành nghĩa vụ pháp lý; cần thông báo xử lý dữ liệu, thời hạn lưu (OQ-02) và DPIA.
3. Thêm kênh nhận bên thứ ba (đảo W-04, REQ-011) — RSK-02/RSK-03 sống lại, thêm ranh giới tin cậy mới.
4. Thêm đăng nhập / trang quản trị (đảo W-01) — bổ sung toàn bộ nhóm ASVS 2/3/4 và test phân quyền theo đối tượng.
5. Thêm chức năng xuất dữ liệu hoặc bảng tính (đảo W-13) — T-09 nâng mức.
6. Thêm tải tệp lên (đảo W-09) hoặc bất kỳ phụ thuộc ngoài nào (đảo CST-01) — T-15 nâng mức, cần SCA + license scan.

## 8. Ánh xạ requirement ⇄ threat (dùng cho `risk_tags` của ticket)
| Yêu cầu | Threat được xử lý | risk_tags đề xuất cho ticket |
|---|---|---|
| M-03 (băng-rôn mọi trang, kể cả 404) | T-07 (trang 404 an toàn), hỗ trợ RSK-04 | `T-07` |
| M-04 (trường + giới hạn 500 + consent) | T-06, T-16 | `pii`, `T-06`, `T-16` |
| M-05 (từ chối phía nhận, không tạo bản ghi) | T-03, T-16 | `pii`, `T-03` |
| M-06 (thông báo lỗi) | T-08 (escape khi hiện lại), T-10 | `T-08`, `T-10` |
| M-07 (ghi SQLite) | T-11, T-04, T-12, T-14 | `pii`, `T-11`, `T-04`, `T-14` |
| M-08 (trang xác nhận) | T-16 | `pii`, `T-16` |
| M-09 (escape HTML) | T-08, T-09 | `T-08` |
| M-10 (không PII trong log) | T-10 | `pii`, `T-10` |
| S-02 (README: cách chạy + cách xoá DB) | T-01, T-04, T-16 | `T-01`, `T-04` |
| S-04 (honeypot) | T-03 (một phần); ưu tiên thấp vì chạy cục bộ | — |
| S-05 (CI) | T-14, T-15 | `T-14`, `T-15` |
| TCK-SEC-01..07 (đề xuất mới) | T-01, T-04, T-05, T-07, T-11, T-14, T-15 | tương ứng |

## 9. Tickets bảo mật đề xuất (để planner đưa vào backlog)
| Ticket | Nội dung | Threat | Ưu tiên |
|---|---|---|---|
| TCK-SEC-01 | Bind server cứng `127.0.0.1`; README nêu rõ chỉ chạy cục bộ | T-01 | cao |
| TCK-SEC-02 | Đặt quyền 0600 cho tệp SQLite khi tạo; checklist xoá sau buổi demo trong README | T-04, T-12 | cao |
| TCK-SEC-03 | Từ chối POST vượt ngưỡng Content-Length trước khi đọc body | T-05 | thấp |
| TCK-SEC-04 | Định tuyến allow-list, không phục vụ hệ tệp; 404 dùng bố cục chung | T-07 | cao |
| TCK-SEC-05 | Toàn bộ truy vấn SQLite tham số hoá + test chống SQL injection | T-11 | cao |
| TCK-SEC-06 | `.gitignore` cho `*.db`/`*.sqlite3` + bước CI chặn commit tệp DB | T-14 | cao |
| TCK-SEC-07 | CI khẳng định không có phụ thuộc ngoài; ghim action theo SHA | T-15 | trung bình |

## 10. Giấy phép và chuỗi cung ứng (license-compliance, phạm vi demo)
- Không có phụ thuộc bên thứ ba theo CST-01/ADR-001 ⇒ danh mục giấy phép hiện tại rỗng; không có copyleft mạnh cần ADR.
- Chưa kiểm chứng bằng máy (lời gọi này không có tool): phải chạy scan phụ thuộc + SBOM ở chế độ release-check trước Gate 3, kể cả khi kỳ vọng là rỗng.
- RSK-12 (ảnh, font không rõ giấy phép): demo không dùng tài sản tải về. Nếu ticket nào thêm font/icon/ảnh thì phải ghi định danh SPDX và qua security-engineer trước khi merge.

## 11. Trạng thái tổng kết
- Tổng số threat: 16. Critical: 0. High: 0 đang mở (T-11 là High-nếu-xảy-ra nhưng có giảm nhẹ tiêu chuẩn + ticket + test ⇒ không phải "High reachable chưa xử lý"). Medium: 6. Low: 8. Không áp dụng thang: 1.
- 0 threat High/Critical không có giảm nhẹ ⇒ không có căn cứ chặn Gate 2.
- 2 rủi ro chấp nhận cần chữ ký: T-12, T-13 qua ADR-004 (đang chờ delivery-lead ký) — đây là mục theo dõi, không phải điều kiện chặn của bản demo.
- Phiên bản kế tiếp: rà lại khi bất kỳ điều kiện §7 xảy ra, hoặc chậm nhất trước Gate 3 (release-check).
