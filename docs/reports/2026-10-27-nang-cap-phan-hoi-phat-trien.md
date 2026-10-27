# Nâng cấp phản hồi phát triển và độ tin cậy phép đo

## Phạm vi

Chủ dự án duyệt triển khai sau khảo sát môi trường ngày 27/10/2026. Hạng mục này sửa các nút thắt có bằng chứng tái hiện: số đo runner khi chạy song song, vòng đời token console, cổng kiểm tra trước commit chạy trùng và chỉ số chất lượng đang đếm sai. Không đổi prompt, model, ngưỡng coverage hoặc quyền phát hành.

## Tiêu chí nghiệm thu

- Hai `generate()` trên cùng runner vẫn chồng nhau nhưng giữ riêng token đầu vào, cache read/write và số lượt provider; callback gọi lồng không ghi đè số liệu lượt ngoài.
- Console mở trùng không thay token phiên đang sống; lỗi mở cổng hoặc ghi token giải phóng tài nguyên; test không ghi token thật của máy phát triển.
- Chạy toàn bộ hook Bash đã đăng ký chỉ thực thi bộ cổng được chọn một lần; cổng đỏ vẫn chặn, đủ gói phụ thuộc, docs-only và trường hợp không xác định phạm vi.
- Quyết định gate thông thường không được tính là ticket mở lại. Tín hiệu sức khỏe CI chỉ dùng các kết quả hoàn tất có thể so sánh; không gọi biến động workflow là bằng chứng flaky test.
- `scripts/dev-task.sh gate all` giữ đủ lint, kiểm kiểu và coverage 100% dòng/nhánh. Giữ kiểm secret, nhánh được phép và các giới hạn Git.

## Bằng chứng và thiết kế

### Runner

Trước sửa, hai tác vụ dùng chung `_usage_extra` và `_first_input`: test barrier quan sát cả hai nhận cache 300 thay vì 100/200. Callback gọi lồng cũng thay số liệu lượt ngoài. Sửa bằng đối tượng usage cục bộ từng `generate()`, truyền qua mọi đường completion và vòng tool, kể cả lượt chốt bắt buộc. Không khóa toàn runner.

Các test tập trung ở `companies/software-company/tests/test_runner_and_persistence.py`. Phạm vi bảo đảm là số đo từng lời gọi; đây không phải tuyên bố sửa mọi giới hạn tái nhập của toolbox hoặc tracing.

### Console

Trước sửa, CLI ghi `.console-token` trước khi bind. Phiên thứ hai lỗi mở cổng vẫn thay file token; token trong file nhận HTTP 401 trong khi token gốc vẫn 200. Test lỗi mở cổng cũng đi qua đường ghi file thật. Khóa vòng đời và công bố token sau khi mở server bảo vệ quyền sở hữu phiên; các test dùng đường dẫn tạm.

### Hook trước commit

`pre-commit-gate.sh` đã có bộ chọn gói bị tác động, gói phụ thuộc và console. `pre-bash-guard.sh` lại chạy thêm `gate` cả workspace. Giữ hook đầu làm chủ duy nhất của cổng chất lượng; hook sau tiếp tục kiểm lệnh nguy hiểm, ranh giới commit và yêu cầu duyệt hiện hành. Không thêm cache có nguy cơ dùng kết quả của candidate cũ. Test tích hợp chạy các hook lấy từ chính `.claude/settings.json`, thay lệnh gate bằng runner ghi nhận lời gọi và mã lỗi.

### Chỉ số chất lượng

Chỉ đếm `ticket.reopened` làm lượt mở lại ticket; `gate.decide` tiếp tục phục vụ số quyết định/chờ gate. Dữ liệu `gh run list` không có kết quả test theo matrix hoặc nguyên nhân hạ tầng, vì vậy tín hiệu CI chỉ chứng minh biến động kết quả workflow có cùng danh tính/ngữ cảnh, không đủ kết luận flaky test. Dữ liệu thiếu hoặc đang chạy không được tính như một kết quả thành công/thất bại.

## Kiểm chứng

Kiểm chứng trên Linux, Python 3.12.14, uv 0.12.23; company dùng 4 worker xdist. Bản vá thêm **56 ca được pytest thu thập**, không thêm file test mới hoặc phụ thuộc.

| Gói | Đạt | Bỏ qua | Coverage dòng/nhánh | Thời gian pytest |
|---|---:|---:|---|---:|
| company | 2.529 | 1 | 100% | 159,01 s |
| gateway | 303 | 0 | 100% | 12,46 s |
| console | 956 | 0 | 100% | 114,26 s |
| core | 691 | 2 | 100% | 12,25 s |
| keeper | 913 | 0 | 100% | 14,76 s |
| Tổng | **5.392** | **3** | **cả năm gói 100%** | **312,74 s** |

Thời gian là tổng thời gian pytest được runner báo, không gồm lint/mypy/build và không dùng làm cam kết phần trăm tăng tốc. `--durations=10` được bật để lưu các ca chậm nhất. Ba ca container bỏ qua vì thiếu image cài sẵn `python:3.12-slim` và `ubuntu/squid:6.6-24.04_beta`; không tính chúng là đã đạt. Gateway có một cảnh báo runpy đã có từ nền.

Lệnh thực tế: `scripts/dev-task.sh gate all` hoàn thành lint/mypy cả năm gói và test company/gateway, rồi phát hiện ba test thông báo chưa cô lập khóa khi có console thật đang chạy. Sửa fixture chung trong `platform/console/tests/conftest.py`, chạy lại **`gate console` → 956 đạt, coverage 100%**; **`gate core`** và **`gate keeper`** cũng exit 0. Không lặp lại hai bộ company/gateway vì bản sửa tiếp theo chỉ thay fixture console; không mô tả lượt `gate all` đầu tiên là exit 0.

Một console thật chạy xuyên suốt các kiểm tra, được dò `/api/state` có xác thực mỗi hai giây. Token không đổi, API luôn HTTP 200; sau đó chỉ console do phiên này tạo được dừng và token được dọn. Kiểm tra này phát hiện ba test còn dùng khóa máy thật mà các lượt test đứng riêng không thấy; chuyển fixture vào conftest giải quyết cả họ caller CLI.

Hai script tái hiện ban đầu đều trả exit 0 sau sửa: runner giữ cache 100/200 và lượt 1/1; console mở trùng trả lỗi mà token gốc và token file đều vẫn nhận HTTP 200. Smoke console khởi động/dừng hai lần với SQLite thật, từ chối thiếu token 401 và POST ở chế độ chỉ đọc 403.

Các kiểm tra bổ sung chạy mới trong phiên: company selftest 59/59, company strict replay 59/59, keeper strict replay 21/21; subagent khớp nguồn; assets 121 file, 0 lỗi nặng/0 cảnh báo; prompt lớn nhất 20% ngân sách, dưới trần 50%. Build năm package tạo đủ 5 wheel và 5 sdist; core wheel giữ `py.typed`. Không gọi model thật; số token của replay là dữ liệu bản ghi.

### Test đỏ trước sửa

- Runner: 3 ca đỏ do trộn usage hoặc callback ghi đè; sau sửa, 120 ca runner/trace/liên quan đạt.
- Hook: 11 ca đỏ và 2 đối chứng xanh trước sửa; 13/13 integration xanh sau sửa, toàn bộ file hook 230 ca đạt. Docs-only trước chạy `repo-gate` **và** cổng toàn workspace; sau chỉ `repo-gate`. Các lỗi nhánh/secret/coverage vẫn chặn.
- Metric: company 2 ca đỏ; keeper 24 ca đỏ ở các trường hợp thiếu mẫu, sai danh tính/trạng thái. Sau sửa, các kiểm tra riêng và cổng package đều qua.
- Console: các vòng test đỏ bắt ghi đè token, rò tài nguyên, quyền sở hữu, ghi dở/rename lỗi và lỗi bất ngờ. Lượt tích hợp với console thật phát hiện thêm 3 ca thông báo đỏ; fixture chung sửa chúng, không nới khóa production.

Rà soát độc lập đã kiểm tra các đường completion, phạm vi chọn gói, consumer metric và thứ tự vòng đời console. Hai điểm bổ sung được sửa trong review: giữ khóa trước khi constructor bật notifier, và dùng ExitStack để đóng notifier/server trước khi nhả khóa cả khi lỗi.

### Trạng thái giao thay đổi

Lint, mypy, test/coverage, replay, kiểm tài sản và smoke đã có bằng chứng cục bộ trong phiên này. `CHANGELOG.md`, số test README, tài liệu hook/console/keeper và nhật ký phiên đi cùng bản vá. Bảy bước sửa prompt không áp dụng vì không thay `agents/`, `skills/` hoặc golden/recording. Chưa chạy CI từ xa hoặc ma trận Python 3.11/3.13; chưa mở hay merge PR, chưa deploy/publish. Kết luận là bản sửa đã được kiểm chứng cục bộ và cần bước PR/CI khi GitHub API được cấp đường mạng.

## Bước tiếp theo cần dữ liệu vận hành

Sau các bản sửa, lấy ít nhất 20 task và 30 lượt CI có thể so sánh để lập baseline p50/p95 thời gian phản hồi, chờ gate, nghiệm thu lần đầu và lỗi lọt. Thử tăng worker hoặc đổi tier theo pha chỉ khi số đo đáng tin và bài nghiệm thu sản phẩm thực tế không giảm. Mức giảm thời gian 20% trong khảo sát là mục tiêu pilot, chưa phải kết quả đo được.

GitHub API của môi trường hiện bị proxy từ chối CONNECT tới `api.github.com`; đọc Git qua origin vẫn hoạt động. Đã lưu bổ sung hostname cụ thể vào bản nháp môi trường, không thay các preset hoặc cấp thêm secret. Kiểm tra PR/issue trùng, CI từ xa và publication chỉ được xác nhận sau khi thao tác thực tế thành công.
