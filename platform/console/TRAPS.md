# TRAPS.md — bẫy riêng của console

Console không chạy sai; nó **hiển thị đúng số nhưng người đọc hiểu sai**. Đêm 2026-09-05/06 vận hành QLKH mất hàng
giờ vì đọc sai trạng thái. Mười chỗ dưới đây là chuyện thật, ghi để không thiết kế lại cùng cái bẫy. Một số đã sửa
ở #76/#80; cột cuối nói còn gì.

| # | Bẫy hiển thị | Đã xảy ra | Trạng thái |
|---|---|---|---|
| 1 | Nhãn `merged` ≠ đã gộp vào nhánh tích hợp | 14/14 ticket có merge commit thật; bảng hiện 10 `approved`, 4 `merged` — `merged` chỉ đổi khi release deploy | #76 tách sự thật git; C7 thêm cột "commit vượt integration" (đếm bằng `rev-list --count`, KHÔNG `branch --contains`) |
| 2 | `status` xanh toàn tập khi dự án chết đứng | `queue: 0, blocked: [], gates: {}` — xanh vì RỖNG; 18/19 release không đi đâu | #76 + C1: phễu SẢN PHẨM, ô `n=0` là ô XÁM (ADR-0003 §2) |
| 3 | `delivery: {}` | Nghĩa là chưa từng giao — 0 tag, 0 production — nhìn suốt đêm không nhận ra | #76 "đã giao n/m" lên tiêu đề |
| 4 | Không thấy phễu release | 4 staging/failed, 6 pending_human, 3 deployed, 5 void, 0 production — phải truy vấn tay | #76 phễu RC; C1 thêm phễu sản phẩm ở màn `#/phieu`, bậc staging/production neo vào `smoke` |
| 5 | Chỉ hiện "gate chờ", không hiện `kind` và hậu quả | Duyệt `escalation` cho REL-xxx tưởng đã giao hàng; chỉ `kind=release` mới deploy | #76 + C2: hậu quả CẢ HAI CHIỀU (duyệt → agent nào chạy lại; từ chối → về đâu) + C8 hồ sơ `gate_brief` tại chỗ |
| 6 | Quyết định xếp sau lượt model dài, nhìn như vô tác dụng | Duyệt 01:34, áp 01:48; dashboard im | #76 + C3: badge "quyết định chưa áp" gắn lên đúng ticket; đầu hàng đợi ghi "đang chạy n phút" |
| 7 | Ticket `blocked` không có gate = im lặng chết | QLKH-010/014: khoá `once` trùng, không ai được hỏi, vẫn xanh | C4: cảnh báo đỏ riêng ở ĐẦU trang, có số đếm (`silent_deadlocks`) |
| 8 | Verdict trên bằng chứng đã bị cắt, không ai thấy là cắt | security chặn vì "thiếu diff" — openapi 804 dòng ăn hết hạn mức | C5: `trim_src` liệt kê từng nguồn bị cắt + số ký tự mất, cạnh verdict và trong ngăn kéo ticket |
| 9 | Ngân sách so tổng token với đầu ra | Số "vượt ngân sách" sai bản chất | #76: mỗi con số ghi rõ đo cái gì (`tokens` vs `output_tokens`) |
| 10 | Lý do duyệt "ok" đi qua | Agent nhận hint rỗng (13:05 2026-09-06) | #80 giữ nguyên; C6 thêm nút chèn mẫu `root_cause`/`decision`/`hint` và ô xem trước NGUYÊN VĂN chuỗi agent nhận |

## Bẫy kỹ thuật

| Bẫy | Vì sao | Chốt chặn |
|---|---|---|
| Service worker cache `/` hoặc `/api/*` | `/` mang token phiên sinh mới mỗi lần chạy → lần sau 401 toàn tập; `/api` cũ là số liệu cũ | SW chỉ cache 2 icon; test kiểm |
| Bind ra ngoài loopback | SW không đăng ký, PWA không cài; và mở cửa cho mạng | `--i-know` bắt buộc; mặc định 127.0.0.1 |
| `enabled: false` cho backend không tắt thật | `company.llm.load_config` bỏ qua khoá lạ | `settings.py` "tắt phải tắt thật" — xoá khỏi `backends` hoặc cơ chế công ty hiểu |
| Input dị dạng làm đứt kết nối thay vì trả mã lỗi | 2026-10-02: token không ASCII (`compare_digest` ném TypeError), byte NUL trong `/static/` (ValueError — POSIX ném ở `resolve()`, Windows chỉ ném ở `open()`: bắt ở `resolve()` thì Linux xanh mà CI windows-latest đỏ), `{"action": []}` (`[] in {…}` ném TypeError), JSON lồng 100k tầng (RecursionError) — client nhận kết nối đứt, không biết mình sai gì | So token bằng bytes, chặn chuỗi có `\x00` trước mọi thao tác đường dẫn (thứ tự nổ khác nhau theo OS), `except` đủ kiểu, kiểm thành viên bằng tuple; `tests/test_server.py` mục "input dị dạng" gửi đúng bốn thân đó |
| `.bak`/`.tmp` của `llm.yaml` mang khoá mà quyền rộng | Ghi theo umask 0644 rồi mới chmod → khoảng hở; `.tmp` sót lại không bị `.gitignore`/`.dockerignore`/hook bắt | `_write_with_mode` siết quyền trước khi ghi (`tests/test_settings.py` `test_khong_luc_nao_ban_sao_khoa_mang_quyen_rong`); ba hàng rào bắt `llm.yaml.*` (`test_cong_repo.py`, `test_cong_docker.py`, `test_cong_khung.py`) |
| Vẽ đè dữ liệu mới lên ngăn kéo đang mở | Người đang đọc mất chỗ | Giữ lại + nút "Có dữ liệu mới — xem" |
| Trả lỗi mà không đọc thân request (request desync) | `protocol_version = "HTTP/1.1"` giữ keep-alive; `_guard` trả 404/403 rồi `return` khi thân POST chưa đọc → `http.server` đọc thân đó thành request THỨ HAI, không qua `_guard` với header thật của kẻ tấn công. Đo 2026-10-10: nhồi `GET /` vào thân một POST có `Host: evil` → 2 phản hồi, phản hồi hai mang token phiên | `_error` đặt `close_connection = True`, `_send` kèm `Connection: close`; `tests/test_server.py::test_request_bi_chan_thi_dong_ket_noi_khong_doc_tiep_than` gửi đúng gói đó qua socket thô và đếm đúng một phản hồi. **Bẫy con (Windows):** đóng socket khi thân POST còn chưa đọc ⇒ kernel gửi RST thay vì FIN, Windows vứt luôn phản hồi 403 đã tới ⇒ `WinError 10053` ở `getresponse()`; CI `console-unit (windows-latest)` đỏ 2 ca mà Linux xanh. `_error` gọi `_drain_body()` đọc bỏ thân (chỉ khi `Content-Length` ≤ `MAX_BODY_BYTES`, cờ `_body_read` đặt lại mỗi request trong `handle_one_request`) rồi mới trả lỗi và đóng; thân quá trần thì vẫn đóng thẳng (RST là giá chấp nhận, không đọc vô hạn) |
| Cổng cục bộ chạy 3.13, CI còn 3.11 — `http.server` khác nhau ở lỗi 400 | Test gửi dòng request không parse được rồi đòi `HTTP/1.1 400 ` ở đầu phản hồi: xanh ở 3.13 (đặt `request_version = ""` trước `send_error` nên có dòng trạng thái), đỏ ở 3.11 (giữ `HTTP/0.9`, `send_response_only` bỏ dòng trạng thái, chỉ gửi thân HTML). PR #403 đỏ đúng một job `console-unit (ubuntu-latest, 3.11)` | Đòi thứ mọi bản đều gửi (`Error code: 400` trong thân). Tái hiện cục bộ không đụng `.venv`: `UV_PROJECT_ENVIRONMENT=<scratch> uv sync --locked --python 3.11` rồi `uv run --python 3.11 pytest …` ở gói |

## Nguyên tắc rút ra cho mọi màn mới

Chốt thành ADR: [`docs/adr/0003-moi-o-tra-loi-mot-cau-hoi-o-rong-la-o-xam.md`](docs/adr/0003-moi-o-tra-loi-mot-cau-hoi-o-rong-la-o-xam.md).
`Studio-creators` đã tách thành repo riêng (`docs/sessions/`); console không còn màn "Xưởng video" nào để nợ (C9).


Trước khi thêm một con số lên trang, trả lời ba câu: *nó đo cái gì đúng nghĩa đen?* · *nó xanh vì tốt hay vì rỗng?*
· *người thấy nó sẽ làm gì tiếp — và làm thế có đúng không?* Không trả lời được câu ba thì chưa đưa lên.
