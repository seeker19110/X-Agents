# PRD — Bản demo website Đồng Hành Cùng Bạn (DHCB)

- project_id: DHCB
- Phiên bản: 1.0 (Gate 2, chờ người duyệt)
- Ngày: 2026-09-02
- Tác giả: spec-writer
- Nguồn đầu vào: `clarification-answers` key=DHCB actor=human:po (CQ-01..CQ-05); `requirements-draft` sau rà rủi ro của agent `risk` (ticket DHCB-004, gồm RSK-01..RSK-12, ACC-01..ACC-02, recommend_drop REQ-011/REQ-028/REQ-021).
- Giới hạn bằng chứng: lời gọi tạo PRD này không có tool nên không đọc repo, không tra cứu văn bản pháp luật. Mọi dữ kiện repo (commit 1466ebb, 4 file, 17 dòng, không có thư mục .github/) là bằng chứng thứ cấp dẫn lại từ researcher qua synthesizer; brief.pdf không có trong workspace (BLK-01/BLK-02 vẫn mở).

## 1. Mục tiêu

### 1.1 Mục tiêu nghiệp vụ
- BG-01: Cho đại diện DHCB xem được một bản demo chạy được của website, để chốt hướng nội dung và luồng đăng ký tình nguyện viên trước khi đầu tư làm bản đầy đủ.
- BG-02: Chứng minh luồng đăng ký tình nguyện viên hoạt động đầu-cuối (nhập → kiểm tra → xác nhận) mà không tạo ra nghĩa vụ pháp lý về dữ liệu cá nhân, vì khách đã chốt ở CQ-01 rằng demo chỉ mô phỏng, không lưu dữ liệu thật.
- BG-03: Giữ chi phí và phụ thuộc ở mức thấp nhất: Python thuần, không framework ngoài (CQ-05), lưu trữ SQLite cục bộ trong repo, không có bên thứ ba (CQ-02).

### 1.2 Không phải mục tiêu
Bản demo này không nhằm vận hành thật, không nhận hồ sơ thật của người thật, và không thay thế trang chính thức của tổ chức.

### 1.3 Người dùng và các bên liên quan
- Đại diện DHCB (người duyệt demo, ký nghiệm thu ở Gate 2).
- Khách tham quan trang demo: người quan tâm hoạt động thiện nguyện, đọc trang chủ và trang giới thiệu.
- Người muốn đăng ký làm tình nguyện viên (trong demo là người đóng vai, dữ liệu mô phỏng).
- delivery-lead (chủ sở hữu kỹ thuật), account-manager (chạy UAT theo nguyên văn Gherkin dưới đây).

### 1.4 Ràng buộc do khách đặt (không phải giải pháp do đội tự chọn)
- CST-01 (nguồn CQ-05): hiện thực bằng Python thuần, không thêm framework ngoài.
- CST-02 (nguồn CQ-02): dữ liệu đăng ký ghi vào một tệp SQLite cục bộ nằm trong repo; không gửi tới bất kỳ dịch vụ bên thứ ba nào.
- CST-03 (nguồn CQ-01, CQ-03): demo không nhận và không lưu lâu dài dữ liệu cá nhân thật; dữ liệu trong SQLite là dữ liệu mô phỏng của buổi trình diễn.
- CST-04 (nguồn CQ-04): mọi thông tin pháp lý của tổ chức (tên pháp nhân, số quyết định thành lập, mã số thuế) để trống trong demo vì khách chưa xác nhận.

## 2. Phạm vi

Ưu tiên theo MoSCoW. Mỗi yêu cầu là một câu, kiểm chứng được, có id ổn định và có nguồn gốc. Mọi Must đều có tiêu chí Gherkin ở mục 3 và kiểm được bằng test tự động chạy trên code Python thuần: không cần mạng, không cần trình duyệt thật (kiểm bằng cách gọi hàm dựng trang và hàm xử lý đăng ký, rồi kiểm chuỗi HTML trả về và bản ghi trong SQLite tạm).

### 2.1 Must (bắt buộc cho bản demo)

| id | Yêu cầu | Nguồn | Cách kiểm |
|---|---|---|---|
| M-01 | Trang chủ trả về nội dung HTML gồm tên gọi "Đồng Hành Cùng Bạn", một đoạn mô tả hoạt động, và một liên kết trỏ tới trang đăng ký tình nguyện viên. | BG-01; REQ-003 của draft | test gọi hàm dựng trang chủ, kiểm chuỗi trả về |
| M-02 | Trang giới thiệu trả về nội dung HTML gồm phần giới thiệu tổ chức và phần hoạt động chính, mỗi phần có tiêu đề riêng. | BG-01; REQ-003 | như trên |
| M-03 | Mọi trang của demo hiển thị băng-rôn cố định với nguyên văn "Bản demo — nội dung chưa được tổ chức duyệt". | RSK-04 mitigation (risk, DHCB-004) | test kiểm chuỗi trên tất cả trang |
| M-04 | Form đăng ký tình nguyện viên nhận đúng các trường: họ tên (bắt buộc), số điện thoại (bắt buộc), email (tuỳ chọn), khu vực (bắt buộc), lý do/kỹ năng (tuỳ chọn, tối đa 500 ký tự) và một ô đồng ý (consent) bắt buộc. | CQ-01; REQ-004; RSK-09 (giới hạn 500 ký tự) | test gọi hàm xử lý đăng ký với các bộ dữ liệu |
| M-05 | Đăng ký bị từ chối và không tạo bản ghi nào khi thiếu bất kỳ trường bắt buộc nào, hoặc khi ô đồng ý không được tích. | CQ-01; nguyên tắc consent | test đường lỗi |
| M-06 | Thông báo lỗi của form nêu tên trường sai và cách khắc phục, mỗi lỗi là một câu bằng tiếng Việt. | skill ui-ux-design (lỗi có nguyên nhân + cách khắc phục) | test kiểm nội dung thông báo |
| M-07 | Đăng ký hợp lệ tạo đúng một bản ghi trong tệp SQLite cục bộ, gồm các trường đã nhập, giá trị consent và dấu thời gian. | CQ-02 | test dùng tệp SQLite tạm, đếm bản ghi và đọc lại giá trị |
| M-08 | Sau khi đăng ký thành công, trang xác nhận hiển thị nguyên văn "Đăng ký này chỉ để trình diễn, dữ liệu không được lưu lâu dài". | CQ-01, CQ-03; RSK-01 mitigation | test kiểm chuỗi trả về |
| M-09 | Mọi giá trị người dùng nhập được escape khi đưa vào HTML, nên chuỗi chứa `<script>` xuất hiện ở trang xác nhận dưới dạng văn bản chứ không phải thẻ. | RSK-09 (Tampering) | test gửi chuỗi có thẻ, kiểm HTML trả về |
| M-10 | Không có giá trị của bất kỳ trường cá nhân nào (họ tên, số điện thoại, email) xuất hiện trong log ứng dụng khi xử lý một lượt đăng ký. | REQ-019; RSK-10 | test bắt log trong lúc gọi hàm đăng ký |
| M-11 | Mỗi ô nhập trong HTML của form có một nhãn `<label>` liên kết đúng bằng thuộc tính `for` tới `id` của ô đó, và trang khai báo `lang="vi"`. | skill accessibility (form có label hiển thị) | test phân tích HTML bằng thư viện chuẩn của Python |
| M-12 | Trang chủ, trang giới thiệu và trang đăng ký dùng chung một bố cục có phần tử `<header>`, `<main>` và `<footer>`, mỗi trang có đúng một `<h1>`. | skill accessibility (HTML ngữ nghĩa trước) | test phân tích HTML của cả ba trang |

### 2.2 Should (làm nếu còn thời gian, không chặn nghiệm thu)
- S-01: Bố cục đọc được ở bề rộng 375px mà không tràn ngang (kiểm thủ công, không có test tự động trong phạm vi demo).
- S-02: Có tệp README ghi cách chạy demo và cách xoá tệp SQLite sau buổi trình diễn.
- S-03: Có kiểm tra định dạng số điện thoại Việt Nam ở phía nhận; giữ ở Should vì khách chưa chốt danh sách trường cuối cùng (RSK-06).
- S-04: Có chống spam tối thiểu (trường ẩn honeypot). Giữ ở Should vì CQ-01 đã chốt demo không nhận dữ liệu thật, nên RSK-05 không còn tác động nghiệp vụ trong phạm vi này.
- S-05: Có tệp CI chạy test và lint (REQ-024, RSK-07).

### 2.3 Could
- C-01: Trang liên hệ tĩnh không có form.
- C-02: Chế độ hiển thị tối (dark mode).

### 2.4 Won't — phạm vi ngoài (không làm trong bản demo này)
Mục này là hợp đồng: những gì liệt kê ở đây không được đòi lúc nghiệm thu.
- W-01: Không có đăng nhập, tài khoản, phân quyền hay trang quản trị.
- W-02: Không có thanh toán, quyên góp trực tuyến, hay tích hợp cổng thanh toán.
- W-03: Không có mục tin tức, blog, hệ quản trị nội dung hay trình soạn thảo nội dung.
- W-04: Không gửi hồ sơ tới bất kỳ kênh nhận bên thứ ba nào (Google Sheet, email, API) — REQ-011 hoãn theo đề nghị của risk; kích hoạt lại khi CONF-01 chốt là nhận dữ liệu thật.
- W-05: Không công bố thông tin pháp lý của tổ chức (tên pháp nhân, số quyết định thành lập) — REQ-028 hoãn theo CQ-04.
- W-06: Không có thông báo xử lý dữ liệu cá nhân đầy đủ theo NĐ 13/2023 và không có quy trình xoá theo yêu cầu chủ thể dữ liệu, vì demo không nhận dữ liệu thật (CQ-01, CQ-03).
- W-07: Không gửi email, SMS hay thông báo cho người đăng ký.
- W-08: Không có bản đa ngôn ngữ; chỉ tiếng Việt.
- W-09: Không có tải tệp lên (CV, ảnh) từ người đăng ký.
- W-10: Không có tìm kiếm, phân tích lưu lượng, hay công cụ theo dõi người dùng.
- W-11: Không có triển khai lên tên miền công khai và không gắn DNS trong phạm vi demo (RSK-11); demo chạy cục bộ.
- W-12: Không có cam kết hiệu năng bằng số (thời gian phản hồi, số người dùng đồng thời) vì demo chạy cục bộ cho một người xem.
- W-13: Không có quản lý danh sách tình nguyện viên, không có xuất dữ liệu, không có nhật ký kiểm toán ai gửi hồ sơ nào (ACC-01).

## 3. Tiêu chí nghiệm thu (Gherkin) — hợp đồng nghiệm thu

Nguyên văn dưới đây vừa là tiêu chí chấp nhận vừa là kịch bản UAT. account-manager dùng nguyên văn, không diễn giải lại. Mỗi Must có ít nhất một đường thành công và một đường lỗi hoặc ca biên.

### M-01 — Trang chủ
```gherkin
Tính năng: Trang chủ giới thiệu tổ chức
  Kịch bản: Khách xem trang chủ
    Given bản demo đã chạy
    When khách mở trang chủ
    Then trang hiện tên gọi "Đồng Hành Cùng Bạn"
    And trang hiện một đoạn mô tả hoạt động của tổ chức
    And trang có một liên kết dẫn tới trang đăng ký tình nguyện viên

  Kịch bản: Đường lỗi — địa chỉ không tồn tại
    Given bản demo đã chạy
    When khách mở một địa chỉ không có trong demo
    Then hệ thống trả về trang báo "Không tìm thấy trang" kèm liên kết về trang chủ
    And hệ thống không báo lỗi kỹ thuật cho khách
```

### M-02 — Trang giới thiệu
```gherkin
Tính năng: Trang giới thiệu
  Kịch bản: Khách đọc phần giới thiệu
    Given bản demo đã chạy
    When khách mở trang giới thiệu
    Then trang có một phần "Giới thiệu" có tiêu đề riêng
    And trang có một phần "Hoạt động chính" có tiêu đề riêng

  Kịch bản: Ca biên — nội dung chưa được khách duyệt
    Given nội dung trang giới thiệu là nội dung mẫu
    When khách mở trang giới thiệu
    Then trang vẫn hiện băng-rôn "Bản demo — nội dung chưa được tổ chức duyệt"
```

### M-03 — Băng-rôn bản demo
```gherkin
Tính năng: Nhãn bản demo trên mọi trang
  Kịch bản: Băng-rôn xuất hiện ở mọi trang
    Given bản demo đã chạy
    When khách mở lần lượt trang chủ, trang giới thiệu, trang đăng ký và trang xác nhận
    Then mỗi trang đều hiện đúng dòng chữ "Bản demo — nội dung chưa được tổ chức duyệt"

  Kịch bản: Đường lỗi — trang lỗi cũng phải có nhãn
    Given bản demo đã chạy
    When khách mở một địa chỉ không có trong demo
    Then trang báo không tìm thấy vẫn hiện dòng chữ "Bản demo — nội dung chưa được tổ chức duyệt"
```

### M-04 — Các trường của form đăng ký
```gherkin
Tính năng: Form đăng ký tình nguyện viên
  Kịch bản: Form có đủ các trường đã thoả thuận
    Given bản demo đã chạy
    When khách mở trang đăng ký tình nguyện viên
    Then form có các ô nhập: họ tên, số điện thoại, email, khu vực, lý do hoặc kỹ năng
    And form có một ô đồng ý cho phép xử lý thông tin trong buổi trình diễn
    And các ô họ tên, số điện thoại, khu vực và ô đồng ý được đánh dấu là bắt buộc

  Kịch bản: Ca biên — lý do hoặc kỹ năng vượt 500 ký tự
    Given khách nhập đủ các trường bắt buộc và đã tích ô đồng ý
    And khách nhập phần lý do dài 501 ký tự
    When khách gửi đăng ký
    Then hệ thống từ chối đăng ký
    And hệ thống báo phần lý do chỉ được tối đa 500 ký tự
```

### M-05 — Từ chối khi thiếu bắt buộc hoặc thiếu đồng ý
```gherkin
Tính năng: Kiểm tra dữ liệu bắt buộc và sự đồng ý
  Kịch bản: Thiếu họ tên
    Given khách để trống họ tên và điền đủ các trường còn lại
    And khách đã tích ô đồng ý
    When khách gửi đăng ký
    Then hệ thống từ chối đăng ký
    And không có bản ghi đăng ký nào được tạo thêm

  Kịch bản: Không tích ô đồng ý
    Given khách điền đủ mọi trường bắt buộc
    And khách không tích ô đồng ý
    When khách gửi đăng ký
    Then hệ thống từ chối đăng ký
    And không có bản ghi đăng ký nào được tạo thêm

  Kịch bản: Ca biên — họ tên chỉ gồm khoảng trắng
    Given khách nhập họ tên chỉ gồm các dấu cách
    And khách điền đủ các trường còn lại và đã tích ô đồng ý
    When khách gửi đăng ký
    Then hệ thống từ chối đăng ký
    And không có bản ghi đăng ký nào được tạo thêm
```

### M-06 — Thông báo lỗi nêu nguyên nhân và cách khắc phục
```gherkin
Tính năng: Thông báo lỗi của form
  Kịch bản: Lỗi nêu rõ trường và cách sửa
    Given khách để trống số điện thoại và điền đủ các trường còn lại
    And khách đã tích ô đồng ý
    When khách gửi đăng ký
    Then hệ thống hiện một thông báo nhắc tới trường số điện thoại
    And thông báo nói rõ khách cần làm gì để gửi lại được

  Kịch bản: Ca biên — nhiều lỗi cùng lúc
    Given khách để trống cả họ tên và khu vực
    And khách không tích ô đồng ý
    When khách gửi đăng ký
    Then hệ thống hiện một thông báo riêng cho từng lỗi
    And dữ liệu khách đã nhập ở các trường khác không bị mất
```

### M-07 — Lưu bản ghi vào SQLite cục bộ
```gherkin
Tính năng: Lưu đăng ký vào cơ sở dữ liệu cục bộ
  Kịch bản: Đăng ký hợp lệ được lưu
    Given cơ sở dữ liệu cục bộ chưa có bản ghi đăng ký nào
    And khách điền đủ mọi trường bắt buộc và đã tích ô đồng ý
    When khách gửi đăng ký
    Then cơ sở dữ liệu cục bộ có đúng một bản ghi đăng ký
    And bản ghi giữ đúng họ tên, số điện thoại và khu vực khách đã nhập
    And bản ghi có giá trị đồng ý và có dấu thời gian

  Kịch bản: Ca biên — hai lượt gửi hợp lệ liên tiếp
    Given cơ sở dữ liệu cục bộ chưa có bản ghi đăng ký nào
    When khách gửi hai lượt đăng ký hợp lệ khác nhau
    Then cơ sở dữ liệu cục bộ có đúng hai bản ghi đăng ký

  Kịch bản: Đường lỗi — đăng ký không hợp lệ không để lại dấu vết
    Given cơ sở dữ liệu cục bộ chưa có bản ghi đăng ký nào
    When khách gửi một lượt đăng ký thiếu ô đồng ý
    Then cơ sở dữ liệu cục bộ vẫn không có bản ghi đăng ký nào
```

### M-08 — Trang xác nhận nói rõ đây là trình diễn
```gherkin
Tính năng: Trang xác nhận sau khi đăng ký
  Kịch bản: Xác nhận kèm lời nhắc về bản demo
    Given khách gửi một lượt đăng ký hợp lệ
    When hệ thống hiện trang xác nhận
    Then trang xác nhận hiện đúng dòng chữ "Đăng ký này chỉ để trình diễn, dữ liệu không được lưu lâu dài"

  Kịch bản: Đường lỗi — đăng ký bị từ chối thì không có xác nhận
    Given khách gửi một lượt đăng ký thiếu trường bắt buộc
    When hệ thống trả kết quả
    Then trang trả về không phải trang xác nhận thành công
    And trang không hiện dòng chữ xác nhận đăng ký thành công
```

### M-09 — Escape dữ liệu người dùng nhập
```gherkin
Tính năng: Hiển thị an toàn dữ liệu người dùng nhập
  Kịch bản: Chuỗi giống mã kịch bản hiện ra dưới dạng chữ
    Given khách nhập họ tên là chuỗi chứa một thẻ script
    And khách điền đủ các trường còn lại và đã tích ô đồng ý
    When khách gửi đăng ký và xem trang xác nhận
    Then trang xác nhận hiện chuỗi đó dưới dạng văn bản
    And trang xác nhận không chứa thẻ script nào do khách nhập vào

  Kịch bản: Ca biên — chuỗi bắt đầu bằng dấu bằng
    Given khách nhập phần lý do bắt đầu bằng dấu bằng
    And khách điền đủ các trường còn lại và đã tích ô đồng ý
    When khách gửi đăng ký và xem trang xác nhận
    Then trang xác nhận hiện nguyên chuỗi đó dưới dạng văn bản
```

### M-10 — Không ghi dữ liệu cá nhân vào log
```gherkin
Tính năng: Log không chứa thông tin cá nhân
  Kịch bản: Một lượt đăng ký hợp lệ
    Given hệ thống đang ghi log ở mức thông tin
    When khách gửi một lượt đăng ký hợp lệ
    Then log không chứa họ tên khách đã nhập
    And log không chứa số điện thoại khách đã nhập
    And log không chứa email khách đã nhập

  Kịch bản: Đường lỗi — đăng ký bị từ chối
    Given hệ thống đang ghi log ở mức thông tin
    When khách gửi một lượt đăng ký thiếu ô đồng ý
    Then log ghi lại việc đăng ký bị từ chối
    And log không chứa họ tên hay số điện thoại khách đã nhập
```

### M-11 — Nhãn của ô nhập và ngôn ngữ trang
```gherkin
Tính năng: Nhãn tiếp cận được cho form
  Kịch bản: Mỗi ô nhập có nhãn liên kết đúng
    Given bản demo đã chạy
    When khách mở trang đăng ký tình nguyện viên
    Then mỗi ô nhập trong form có một nhãn hiển thị liên kết tới đúng ô đó
    And trang khai báo ngôn ngữ là tiếng Việt

  Kịch bản: Đường lỗi — thông báo lỗi gắn với ô nhập
    Given khách gửi một lượt đăng ký thiếu họ tên
    When hệ thống hiện lại form kèm lỗi
    Then thông báo lỗi của ô họ tên được gắn với chính ô họ tên
```

### M-12 — Bố cục chung và cấu trúc ngữ nghĩa
```gherkin
Tính năng: Bố cục chung cho mọi trang
  Kịch bản: Ba trang dùng chung bố cục
    Given bản demo đã chạy
    When khách mở lần lượt trang chủ, trang giới thiệu và trang đăng ký
    Then mỗi trang có phần đầu trang, phần nội dung chính và phần chân trang
    And mỗi trang có đúng một tiêu đề cấp một

  Kịch bản: Ca biên — chân trang không có thông tin pháp lý
    Given khách chưa xác nhận thông tin pháp lý của tổ chức
    When khách mở bất kỳ trang nào
    Then chân trang không nêu tên pháp nhân hay số quyết định thành lập
```

## 4. Yêu cầu phi chức năng trong phạm vi demo
- NFR-01 (khả năng tiếp cận, Must): mọi ô nhập có nhãn liên kết; trang khai báo `lang="vi"`; kiểm bằng test phân tích HTML — xem M-11.
- NFR-02 (bảo mật, Must): mọi giá trị người dùng nhập được escape khi dựng HTML — xem M-09.
- NFR-03 (riêng tư, Must): không ghi dữ liệu cá nhân vào log — xem M-10.
- NFR-04 (khả năng bảo trì, Should): bộ test chạy được bằng thư viện chuẩn của Python, không cần mạng và không cần trình duyệt; đo bằng: chạy bộ test trong môi trường không có mạng vẫn qua.
- NFR-05 (khả năng chuyển đổi, Should): demo chạy được bằng một lệnh Python duy nhất, không cài thêm gói ngoài (CST-01).
- Các nhóm ISO 25010 còn lại (hiệu năng, tương thích, tin cậy) cố ý không đặt ngưỡng số trong bản demo — xem W-12. Đây là quyết định có chủ ý, không phải bỏ sót.

## 5. Bảng truy vết

| Mục tiêu | Yêu cầu | Tiêu chí | Rủi ro liên quan |
|---|---|---|---|
| BG-01 | M-01, M-02, M-12 | Gherkin M-01, M-02, M-12 | RSK-06 |
| BG-01 | M-03 | Gherkin M-03 | RSK-04 |
| BG-02 | M-04, M-05, M-06, M-07, M-08 | Gherkin M-04..M-08 | RSK-01 (đã đóng bằng CQ-01), RSK-09 |
| BG-02 | M-09, M-10 | Gherkin M-09, M-10 | RSK-09, RSK-10 |
| BG-03 | M-07, NFR-04, NFR-05 | Gherkin M-07 | RSK-07 |
| BG-01 | M-11 | Gherkin M-11 | — |

## 6. Giả định
- ASM-01: Tên gọi tổ chức trong demo là "Đồng Hành Cùng Bạn"; chưa có xác nhận bằng văn bản về loại hình pháp lý (CQ-04 trả lời là chưa xác nhận).
- ASM-02: Nội dung trang chủ và trang giới thiệu là nội dung mẫu do brief.pdf không có trong workspace (BLK-01/BLK-02); nội dung sẽ được thay khi khách cung cấp.
- ASM-03: Buổi trình diễn chạy trên máy cục bộ, một người xem tại một thời điểm.
- ASM-04: Tệp SQLite được xoá sau buổi trình diễn; việc xoá là thao tác thủ công của người trình diễn, không phải chức năng của phần mềm.
Không giả định nào ở đây được nâng lên thành Must.

## 7. Câu hỏi còn mở
Không còn câu hỏi chặn cho bản demo. Các câu hỏi dưới đây chỉ liên quan tới bản đầy đủ và không chặn Gate 2:
- OQ-01: Kênh nhận hồ sơ thật là gì? Người trả lời: đại diện DHCB. Hạn: trước khi mở phạm vi bản đầy đủ. Chặn: REQ-011 (W-04).
- OQ-02: Thời hạn lưu hồ sơ tình nguyện viên là bao lâu? Người trả lời: đại diện DHCB. Hạn: trước khi bản đầy đủ nhận dữ liệu thật. Chặn: REQ-006 (W-06).
- OQ-03: Loại hình pháp lý và thông tin pháp nhân của DHCB? Người trả lời: đại diện DHCB. Hạn: trước khi công bố công khai. Chặn: REQ-028 (W-05).
- OQ-04: Hiệu lực và nội dung áp dụng của NĐ 13/2023 tại thời điểm triển khai thật (CONF-05) chưa được kiểm chứng vì lời gọi này không có mạng. Người trả lời: researcher khi có tool.

## 8. Rủi ro còn lại trong phạm vi demo

| id | Rủi ro | Mức | Xử lý trong PRD này |
|---|---|---|---|
| RSK-01 | Demo nhận dữ liệu cá nhân thật khi chưa có thông báo xử lý dữ liệu | high (đã hạ) | Đóng bằng CQ-01/CQ-03 và W-04, W-06; M-08 nhắc người dùng đây là trình diễn |
| RSK-02 | Lộ dữ liệu qua kênh nhận bên thứ ba | high (không còn áp dụng) | Không có bên thứ ba (CQ-02, W-04) |
| RSK-04 | Trang demo bị hiểu là trang chính thức | high | M-03 băng-rôn trên mọi trang; W-11 không triển khai công khai |
| RSK-06 | Nội dung là giả định vì thiếu brief.pdf | high | ASM-02; nghiệm thu chỉ tính khung và luồng, không tính nội dung |
| RSK-09 | Chèn công thức hoặc mã kịch bản qua trường tự do | medium | M-09 escape; M-04 giới hạn 500 ký tự |
| RSK-10 | Dữ liệu cá nhân lọt vào log | medium | M-10 |
| RSK-07 | Thiếu nền build/CI, ước lượng vỡ | medium | S-05; CST-01 giữ một toolchain duy nhất |
| RSK-12 | Ảnh và font không rõ giấy phép | low | Demo không dùng ảnh hay font tải về; nếu dùng thì phải ghi nguồn và giấy phép |
| RSK-05 | Bot đổ bản ghi rác | medium → thấp trong phạm vi này | Demo chạy cục bộ, không công khai (W-11); S-04 để dành cho bản đầy đủ |
| RSK-03, RSK-08, RSK-11 | Kênh nhận, thời hạn lưu, tên miền | — | Chuyển sang bản đầy đủ; xem OQ-01..OQ-03 |
| ACC-01, ACC-02 | Không có nhật ký kiểm toán / nhật ký truy cập hồ sơ | chấp nhận | W-13; ADR-004 chờ delivery-lead ký |

## 9. Định nghĩa hoàn thành cho Gate 2
- 12/12 Must có Gherkin gồm đường thành công và ít nhất một đường lỗi hoặc ca biên: đạt.
- Phạm vi ngoài (Won't) có 13 mục, không rỗng: đạt.
- Câu hỏi còn mở chỉ còn loại giả định và loại thuộc bản đầy đủ, không có câu hỏi chặn: đạt.
- Bảng truy vết hai chiều, không id trùng: đạt.
- Trạng thái: pending_human — chờ đại diện DHCB và delivery-lead duyệt.
