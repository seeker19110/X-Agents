# ADR-0047: DAST tối thiểu do orchestrator chạy cho release-check, và chấm lại RC cũ

Trạng thái: Accepted · Ngày: 2026-09-27 · Nối tiếp ADR-0046 (SBOM/license), ADR-0029 (bằng chứng chạy là của
orchestrator), ADR-0035 (sandbox), ADR-0041 (`runtime.deploy`). Không đổi route, không đổi prompt của `security`.

## Bối cảnh — số đo

REL-007 (CAMPUS-UNI, 26/09) bị `security` chặn với ba finding `block`: thiếu SBOM, thiếu license, và **thiếu DAST** —
*"TCK-011 mang risk_tags auth (T-01 brute-force, T-02, T-03) — cần bằng chứng quét động (rate-limit đăng nhập, khoá
tài khoản, cookie session HttpOnly/SameSite) trước Gate 3"*. ADR-0046 (#357) lo hai cái đầu; cái thứ ba vẫn không có
đường pass: route `release-candidates → security` không có tool, và agent được dặn không đoán số liệu. Phiên chính
đã ký thay (`reviewer:phien-chinh`, 15:44 UTC) và ghi rủi ro máy chấp nhận thay khách: "không có DAST; chưa rate-limit
đăng nhập theo IP (T-01)".

Máy trực không có `docker` (audit `release.deploy_skipped` REL-007: *không có `docker` trên PATH*), nên công cụ DAST
đóng gói bằng container (OWASP ZAP baseline) không chạy được ở đây.

Sau khi PR sửa bằng chứng merge, RC cũ không được chấm lại: `release-candidates` chỉ xử lý một lần (`processed`).
REL-007 muốn được chấm bằng bằng chứng mới thì không có đường nào ngoài tạo RC mới.

## Quyết định

1. Trước lượt `security` trên `release-candidates`, cùng chỗ với ADR-0046, orchestrator chạy **DAST tối thiểu** trên
   đúng cây RC (`_release_root`) và đưa vào `evidence.dast` (`verified_by=orchestrator`):
   - Khởi động sản phẩm bằng `runtime.command` của spec qua sandbox (`run_smoke`, ADR-0029/0035), trên **cổng trống**
     khi lệnh có `{port}` — không tranh cổng với smoke staging/QA hồi quy của cùng RC. Chờ health đúng như smoke.
   - Khi sản phẩm đang chạy, chỉ gửi request tới `127.0.0.1:<cổng vừa mở>`:
     - `GET /`, `GET <health>`, `GET /__dast-<ngẫu nhiên>`: header bảo mật có/thiếu (`X-Content-Type-Options`,
       `X-Frame-Options`, `Content-Security-Policy`, `Referrer-Policy`), `Server`/`X-Powered-By` có số phiên bản,
       trang lỗi lộ dấu vết debug (traceback, `DEBUG = True`, Werkzeug debugger).
     - **Cửa đăng nhập lấy từ `api-contract` của dự án** (OpenAPI trên blackboard), không dò đường: operation `POST`
       công khai (`security: []`, hoặc không có `security` ở cả op lẫn gốc), thân `application/json` có thuộc tính
       `password`, và khai phản hồi `401`. Không path param; trường bắt buộc phải là chuỗi.
       - 12 lần sai liên tiếp, **mỗi lần một username ngẫu nhiên** → có bị giới hạn theo nguồn không (429,
         `Retry-After`) — đo được T-01.
       - 12 lần sai liên tiếp **cùng một username ngẫu nhiên** → có giới hạn theo username không phụ thuộc tồn tại.
       - Một thân JSON hỏng → có trả 5xx/lộ traceback không.
     - `Set-Cookie` thấy được ở mọi phản hồi: tên, `HttpOnly`, `SameSite`, `Secure`.
   - Kết quả: `checks` (sự thật đo được), `issues` (sự thật thường là finding, câu trung tính, **không** gắn mức),
     `notes` (điều máy không đo được — ghi thẳng, không để im lặng thành "pass").
2. Sau lượt, `evidence.dast` trong `review-results` bị ghi đè bằng bản của orchestrator; model tự khai thì bỏ và ghi
   `dast.claimed_ignored` (cùng khuôn `supply_chain.claimed_ignored`). `dast_summary` là lời đọc của model, giữ nguyên.
3. **Không ghi đè verdict.** Thiếu CSP ở một API nội bộ loopback có phải lỗi chặn không là chính sách; máy đưa số.
4. Không quét được → `unverified` kèm lý do: spec không có `runtime`; spec khai `runtime.deploy` (sản phẩm cần môi
   trường dựng riêng, ADR-0041 — lệnh trần không đại diện); không có worktree tích hợp; sản phẩm không lên (kèm
   `smoke` với mã thoát/đuôi stderr).
5. **Chấm lại RC cũ**: `python -m company.orchestrator recheck <REL> --by human:<tên>|reviewer:<id>` chạy lại đúng
   route security của RC với bằng chứng mới (cùng khuôn `redeploy`: giữ lease, `_recall` rồi `_call`). Không đụng
   quyết định đã có: RC đã được chấp nhận rủi ro (`release_waived`) vẫn giữ; review mới thay review cũ trong
   `release_reviews` nên người ký Gate 3 thấy verdict và finding mới. Từ chối: RC không cần security, RC đã huỷ,
   RC đã giao, `by` không phải `human:`/`reviewer:`.

## Cái giá đã biết

- **Không đo khoá tài khoản thật**: máy không có tài khoản nào, nên username ngẫu nhiên không tồn tại. "Không khoá"
  ở burst cùng username không chứng minh thiếu khoá cho tài khoản có thật — `notes` nói đúng câu này. Khoá tài khoản
  thật vẫn phải dựa test của khách.
- **Không quan sát cookie phiên**: không đăng nhập thành công được, nên `sessionid` thường không xuất hiện; chỉ thấy
  cookie phát cho khách vãng lai (vd `csrftoken`).
- HTTP loopback: không kiểm HSTS/`Secure`/TLS.
- Burst ghi 24 lần đăng nhập sai vào dữ liệu của checkout RC (nhật ký kiểm toán của sản phẩm nếu có). Checkout theo
  sha tách khỏi worktree tích hợp; dữ liệu đó là của lượt quét.
- Không crawl, không fuzz, không quét lỗ hổng theo chữ ký như ZAP; không có `api-contract` OpenAPI thì không thử cửa
  đăng nhập (ghi `login.skipped`).
- Sản phẩm `runtime.deploy` (compose) ra `unverified`.
- Recheck với RC đã waived: verdict mới `block` không mở lại escalation (đã duyệt) — nó hiện ở Gate 3.

## Phương án đã loại

- **OWASP ZAP baseline qua docker.** Máy trực không có docker (đo ở trên); thêm phụ thuộc hạ tầng cho một bằng chứng
  mà bản tối thiểu đủ trả lời đúng các câu security đã hỏi (rate-limit, cookie, header).
- **Crawl tìm form đăng nhập.** CAMPUS-UNI đăng nhập bằng JSON API (`POST /api/v1/auth/session`), không có form HTML;
  đoán đường (`/login`, `/api/auth`) là đoán. `api-contract` là thứ đã được ký ở pha plan.
- **Cho security tool mạng rồi để nó tự quét.** Kết quả vẫn là lời khai; và agent có tool vẫn có lúc không gọi tool
  (`review.no_tool_evidence`).
- **Tự chấm lại mọi RC cũ khi orchestrator khởi động.** Tốn một lượt model mỗi RC, và đổi review của RC đã được người
  quyết mà không ai yêu cầu. Chấm lại là việc chủ ý, có người/ reviewer đứng tên.
- **Recheck huỷ waiver cũ.** Muốn mở lại escalation thì phải sửa luật "escalation đã duyệt thì không mở lại" — luật
  chống mở gate lặp. Để verdict mới hiện ở Gate 3 là đủ cho người ký, không phá luật đó.
