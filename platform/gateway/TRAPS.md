# TRAPS.md — bẫy riêng của gateway

Gateway là nơi khuôn 1 (`../../TRAPS.md`: *chế độ hỏng không tự khai báo*) cắn nhiều nhất, vì nó đứng giữa hai bên đều
không nhìn thấy nhau. Mỗi dòng dưới đây có test hoặc đoạn code làm chốt chặn; không có thì ghi "chưa".

## Bẫy vận hành

| Bẫy | Đã xảy ra / thấy ở đâu | Chốt chặn / lần sau |
|---|---|---|
| Timeout upstream → `HTTP 500` thân RỖNG | `str(httpx.ReadTimeout(""))` là chuỗi rỗng; công ty retry vô ích (2026-09-04, khi trần còn 120 s) | Trần nay 900 s (`GATEWAY_UPSTREAM_TIMEOUT_S`, `client.py:862`); timeout → 504 kèm thông điệp (`server.py:57-58,70-72`; `tests/test_server.py:159,190`). Đọc dấu thời gian: mọi lần hỏng cách nhau đúng bằng trần là timeout |
| Hạn mức dài bị che bằng cooldown mặc định 1 giờ | Pool "hết" lặp lại mỗi giờ, không ai thấy con số thật; Code Assist không gửi `Retry-After`, chỉ ghi "Resets in 7m29s" trong thân | `cooldown_hint` đọc cả header lẫn thân (`client.py:100-131`); số giây thật vào 429 + header `Retry-After` (`tests/test_server.py:177`) |
| Cổng 1123 đã có người giữ | `start` chờ 10 s rồi "healthcheck quá hạn", `status` OFFLINE, nhưng `curl` vào cổng trả 200 (bridge Hermes từng cùng lấy 8100) | `is_server_running` kiểm `service == "gateway"` (`server.py:283`), không chỉ kiểm cổng mở; `curl /health` xem ai giữ; chạy `--port` khác (ADR-0002) |
| Hai proxy cùng bộ tài khoản, cooldown không chung | Gateway và bridge Hermes đọc hai file token; proxy này nghỉ tài khoản, proxy kia vẫn bắn | Cooldown là của **file** (`auth.py:379-381`): dùng chung `XAGENTS_HOME`/`HERMES_HOME` hoặc chia tài khoản |
| LRU hoà nhau trên đồng hồ thô (Windows ~15 ms) → pool kẹt một tài khoản | Hai lượt cùng `time.time()` → khoá sắp xếp bằng nhau → thứ tự file thắng | Dấu `max(now, newest + 1e-3)` (`auth.py:363-367`; `tests/test_account_pool.py:170`) |
| Lỗi mạng khi refresh làm nguội cả pool | Một nhịp DNS chập chờn → mọi tài khoản cooldown | Lỗi mạng → bỏ qua lượt này, không cooldown; chỉ HTTP 4xx của Google mới cooldown (`auth.py:340-352`; `tests/test_account_pool.py:101`) |
| `stop` giết nhầm tiến trình tái dùng PID | PID file mồ côi sau crash; 2026-10-02: phép kiểm cũ là chuỗi con `"gateway"` nên `api-gateway-khac.py` cũng bị nhận là daemon (khuôn 6) | Linux/macOS khớp đúng `DAEMON_SIGNATURE` — chuỗi `cmd_start` đặt vào `python -c` (`manage.py:63,125`; `tests/test_x_manage_coverage.py:72`). Windows chỉ biết "là một tiến trình python" — giới hạn đã biết, ghi trong docstring `_pid_is_gateway` |
| Đọc file token lỗi → coi như rỗng → GHI ĐÈ, xoá sạch pool | 2026-10-02: `_read_file` nuốt mọi lỗi thành `{}`; một lần đọc hỏng tạm thời (Defender giữ file, JSON đang ghi dở) lúc `save_credentials`/`mark_unavailable` là mọi tài khoản khác biến mất | Đường GHI đọc qua `_read_for_write` (`strict=True`): đọc lỗi thì KHÔNG ghi và log `error`; `login` báo lỗi thay vì báo thành công (`auth.py:184-210`; `tests/test_account_pool.py:300`, `tests/test_login_pkce.py`). Đường ĐỌC vẫn lành tính `{}` |
| Request đang bay hoàn tác `logout` | 2026-10-02: `_update_account_fields` ghi `last_used_at`/cooldown cho tài khoản vừa bị gỡ → tạo lại nó trong pool (và tạo lại file đã xoá) | Tài khoản không còn trong `accounts` thì bỏ cập nhật, log `info` (`auth.py:291-310`; `tests/test_account_pool.py:360`) |
| `--host` nội suy vào mã `python -c` của daemon | 2026-10-02: `cmd_start` dựng `_run_daemon(host='{host}')` bằng f-string — một dấu `'` trong `--host` là chạy mã tuỳ ý | host/port đi qua `argv`, mã cố định (`manage.py:166`; `tests/test_x_manage_coverage.py:210`). Mọi `-c`/`eval` dựng từ tham số: dữ liệu đi `argv`, không đi chuỗi mã |
| `status` exit 1 nhưng server ONLINE | Exit 1 gộp "OFFLINE" và "0 tài khoản sẵn sàng" (`manage.py:196`) | Script đọc dòng `Server:`; `tests/test_x_manage_coverage.py:257` |
| `models` báo "không có backend nào trỏ vào gateway" | Chạy gateway ở `--port` khác nhưng `models` đối chiếu mặc định 1123 | Truyền cùng `--port` cho `models` (`manage.py:407`) |
| Model đã chết vẫn trả HTTP 200 | Body có "no longer available" | `models --probe` phân loại theo thân (`client.py:255-261`), mã HTTP không đủ |

## Bẫy hợp đồng với lớp trên

| Bẫy | Đã xảy ra / thấy ở đâu | Chốt chặn / lần sau |
|---|---|---|
| Structured output về qua `tool_calls`, client đọc `content` rỗng, mã 200 | Không lỗi nào để bắt | Client của công ty đọc cả hai; gateway giữ `finish_reason` thật (`client.py:1030-1032`) |
| Stream xoay tài khoản giữa chừng | Chunk đầu đã đi rồi thì không thể đổi | Chỉ xoay **trước** chunk đầu (`client.py:954`); 5xx lúc mở stream → tài khoản kế, không cooldown (`client.py:975-978`); lỗi giữa stream → chunk `error` + `[DONE]` (`server.py:252-255`; `tests/test_server.py:203`) |
| Bearer giữ chỗ bị coi là ghim tài khoản | `dummy`, `gateway-local`… | Danh sách `_DUMMY_BEARERS` ở **`server.py:39`** (không phải `auth.py`); chỉ token trùng email/access token mới ghim (`tests/test_server.py:83`) |
| `usage` không có token cache | Audit-log công ty đếm thiếu → chi phí sai | Trả đủ từ `usageMetadata` (`client.py:698`) |
| `cooldown_hint` treo luồng vì regex backtrack bậc ba | 2026-10-02: `\s*` đứng giữa các nhóm tuỳ chọn `(\d+h)?(\d+m)?` — thân lỗi 1000 khoảng trắng mất 4,4 s, thân do upstream/client gửi nên ai cũng gây được | Khoảng trắng sau mỗi đơn vị nằm TRONG nhóm của nó (`client.py:108`; `tests/test_failover.py:421` đo < 0,5 s). Regex mới khớp thân lỗi: thử chuỗi dài toàn khoảng trắng trước khi merge |
| Đổi chuỗi "Thử lại sau khoảng Ns" hay dòng log `lần thử i/n` | Chưa xảy ra — và router hai công ty khớp chuỗi, người vận hành đọc log | Đổi là phải sửa cả hai `routing.py` và `tests/test_failover.py:355-397` |
| Model lạ âm thầm chạy model mặc định | Trước đây fallback + warning | `GATEWAY_STRICT_MODELS=1` mặc định → 400 `invalid_request_error`, không xoay tài khoản (`client.py:209-235`; `tests/test_server.py:241`) |

## Bẫy khi sửa test / chạy trên Windows

| Bẫy | Thấy ở đâu | Chốt chặn |
|---|---|---|
| Test quyền file 0600/0700 bị skip trên Windows | `@pytest.mark.skipif(os.name == "nt", reason="chmod POSIX")` (`tests/test_account_pool.py:205,301`) → 3 skip trong `pytest -q` là bình thường | Nhánh `os.chmod` vẫn được phủ bằng monkeypatch `os.name="posix"` (`tests/test_account_pool.py:307-312`) — đừng xoá test đó để "gọn" |
| Console cp1252 in tiếng Việt lỗi | `manage.py:464-469` tự `reconfigure(utf-8)`, nhưng pytest thì không | `PYTHONIOENCODING=utf-8` khi chạy test |
| Coverage `fail_under = 100` thiếu dòng POSIX trên Windows | `../../AGENTS.md` luật bắt buộc 3 | CI Linux mới là số thật |
| `os.replace` trả `[WinError 5] Access is denied` khi Defender/indexer giữ file đích một khoảnh khắc; `_update_account_fields` nuốt lỗi nên cooldown, `last_used_at`, token vừa refresh **mất im lặng** | 2026-09-22: 1/8 lượt chạy cả bộ đỏ ở `test_round_robin_*` + `test_mark_unavailable_*`, chạy lẻ luôn xanh; log bắt được có dòng `Không ghi được token file … WinError 5`. CI Linux không bao giờ thấy | `_atomic_write` thử lại `REPLACE_ATTEMPTS` lần khi `PermissionError`, nghỉ tăng dần (`tests/test_account_pool.py` `test_atomic_write_retries_transient_permission_error`). Test LRU đỏ "chỉ trên máy tôi" → tìm dòng `Không ghi được` trong captured log trước khi gọi là chập chờn |

## Cách rà

Với mỗi nhánh lỗi trong `client.py`/`auth.py`: *"người vận hành đọc log này có biết đích xác chuyện gì không?"* và
*"lớp trên nhận mã này sẽ làm gì — retry, chờ bao lâu, đổi backend?"* Nếu câu trả lời là "chờ mặc định", đó là bẫy.
Với mỗi trường mới ra ngoài (`/auth/status`, log, thông điệp lỗi): đối chiếu bảng lộ dữ liệu ADR-0003 §2.
