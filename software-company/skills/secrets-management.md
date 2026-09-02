---
name: secrets-management
version: 1
standards: [OWASP ASVS V6 (mã hóa) & V2, NIST SP 800-57 (quản lý khóa), CIS Controls v8 §5, OIDC workload identity, PCI DSS 3.6, gitleaks/trufflehog]
---
# Skill: secrets-management

## Tiêu chuẩn tham chiếu
- OWASP ASVS V2/V6: lưu trữ và quản lý bí mật, khóa mã hóa, thông tin xác thực
- NIST SP 800-57: vòng đời khóa — sinh, phân phối, sử dụng, xoay vòng, thu hồi, hủy
- CIS Controls v8 §5 (quản lý tài khoản) và §6 (quản lý quyền truy cập)
- OIDC workload identity federation: bí mật ngắn hạn thay cho khóa dài hạn trong CI/CD và cloud
- PCI DSS yêu cầu 3.6 cho quản lý khóa mã hóa; gitleaks/trufflehog để quét lịch sử git

## Quy trình (làm đúng thứ tự)
Liệt kê mọi bí mật đang tồn tại và nơi chúng nằm → chuyển tất cả vào kho bí mật tập trung → cấp cho ứng dụng qua workload identity hoặc chứng thư ngắn hạn thay vì khóa tĩnh → bật quét bí mật ở pre-commit và CI, gồm cả lịch sử git → đặt lịch xoay vòng theo loại bí mật → thiết lập quy trình thu hồi khi lộ và diễn tập nó → giám sát truy cập kho bí mật và cảnh báo bất thường.
Bí mật đã lọt ra ngoài phải coi là đã lộ vĩnh viễn: xoay vòng trước, điều tra sau; xóa commit không phải là biện pháp khắc phục.

## Quy tắc — nơi lưu và cách cấp phát
- Nguồn sự thật duy nhất là kho bí mật (HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault hoặc tương đương), có kiểm soát truy cập và nhật ký kiểm toán.
- Cấm tuyệt đối trong kho mã, kể cả file `.env` mẫu, comment, test fixture, IaC, ảnh chụp màn hình trong tài liệu và ticket.
- Ứng dụng đọc bí mật lúc khởi động hoặc qua sidecar/agent; biến môi trường chấp nhận được nhưng không ghi ra file trên đĩa chia sẻ và không in ra khi khởi động.
- CI/CD dùng OIDC workload identity liên kết với cloud, không lưu khóa truy cập dài hạn trong biến của runner; secret của pipeline không hiển thị cho PR từ fork.
- Quyền theo nguyên tắc tối thiểu và theo dịch vụ, không theo con người; truy cập của người là tạm thời, có phê duyệt và hết hạn (just-in-time).
- Mỗi bí mật có chủ sở hữu, mục đích và môi trường ghi rõ; bí mật dùng chung giữa production và môi trường thấp hơn là cấm.
- Mã hóa dữ liệu: khóa quản lý bằng KMS/HSM, không nằm cạnh dữ liệu được mã hóa (xem `disaster-recovery` cho khôi phục khóa).

## Quy tắc — xoay vòng và thu hồi
- Chu kỳ xoay vòng tối đa: chứng thư truy cập tự động và token dịch vụ ≤ 24 giờ; khóa API và mật khẩu dịch vụ ≤ 90 ngày; khóa mã hóa dữ liệu ≤ 12 tháng; chứng chỉ TLS theo hạn phát hành nhưng gia hạn tự động trước hạn ≥ 30 ngày.
- Xoay vòng phải tự động và không gây gián đoạn: hỗ trợ hai bí mật hợp lệ cùng lúc (overlap) khi chuyển đổi, rồi vô hiệu bản cũ.
- Xoay vòng bắt buộc ngoài lịch khi: có người rời dự án hoặc đổi vai trò, bàn giao cho khách (xem `handover`), nghi ngờ lộ, hoặc sau bất kỳ sự cố bảo mật nào.
- Khi lộ: thu hồi bí mật trong ≤ 1 giờ kể từ khi phát hiện, rà nhật ký tìm dấu hiệu sử dụng trái phép, đánh giá phạm vi ảnh hưởng, và mở sự cố theo `incident-management`; nếu chạm dữ liệu cá nhân thì kích hoạt thêm `privacy-compliance`.
- Bí mật đã lộ không được tái sử dụng dưới bất kỳ hình thức nào, kể cả ở môi trường thử.
- Bí mật không xoay vòng được (thư viện hoặc đối tác không hỗ trợ) phải có ADR ghi rủi ro và biện pháp bù đắp.

## Quy tắc — quét, log và AI
- Quét bí mật chạy ở pre-commit và trong CI, chặn merge khi phát hiện; quét toàn bộ lịch sử git định kỳ ≥ 1 lần/tháng và khi nhận bàn giao kho từ bên ngoài.
- Không bao giờ ghi bí mật vào log, trace, thông báo lỗi, thông điệp exception hay báo cáo crash; có bộ lọc che (redaction) ở tầng logging và kiểm bằng test (xem `observability`).
- Không đưa bí mật vào prompt của mô hình ngôn ngữ, vào ngữ cảnh agent, vào ticket hay kênh chat; agent cần truy cập thì dùng token phạm vi hẹp, ngắn hạn, do hệ thống cấp lúc chạy (xem `ai-governance`, `prompt-engineering`).
- Không chia sẻ bí mật qua email, chat hay bảng tính; cần đưa cho người thì dùng kênh một lần có hạn hoặc cấp quyền trực tiếp trong kho bí mật.
- Nhật ký truy cập kho bí mật được giữ và giám sát; đọc bí mật production ngoài giờ hoặc từ danh tính lạ sinh cảnh báo.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi bí mật nằm trong kho tập trung, không có trong kho mã hay IaC
- [ ] CI/CD dùng workload identity, không có khóa dài hạn trong runner
- [ ] Mỗi bí mật có chủ sở hữu, phạm vi và môi trường riêng biệt
- [ ] Quét bí mật ở pre-commit và CI; quét lịch sử git hằng tháng
- [ ] Lịch xoay vòng đúng chu kỳ (≤ 24h / ≤ 90 ngày / ≤ 12 tháng) và tự động
- [ ] Xoay vòng có giai đoạn overlap, không gây gián đoạn
- [ ] Có quy trình thu hồi ≤ 1 giờ khi lộ, đã diễn tập
- [ ] Bí mật bị che trong log, trace và báo cáo lỗi, có test chứng minh
- [ ] Không có bí mật trong prompt, ngữ cảnh agent, ticket hay chat
- [ ] Xoay vòng bắt buộc khi người rời dự án hoặc khi bàn giao

## Ví dụ tốt
GitHub Actions lấy quyền AWS qua OIDC, không có `AWS_ACCESS_KEY_ID` nào trong kho. Ứng dụng lấy chuỗi kết nối từ Vault lúc khởi động, chứng thư database hết hạn sau 12 giờ và được cấp lại tự động. gitleaks chặn 3 PR trong quý. Ngày 11/08 một khóa Stripe test lọt vào log của worker: phát hiện 09:02 qua cảnh báo, thu hồi 09:26, rà nhật ký không thấy sử dụng lạ, bộ lọc redaction bổ sung kèm test, postmortem trong 48h. Bàn giao dự án tháng 09 xoay vòng toàn bộ 31 bí mật.

## Ví dụ xấu
`config/prod.yaml` chứa mật khẩu database, commit từ 2023 và vẫn đang dùng; khóa cloud dài hạn dán trong biến của runner CI và lộ qua log build của một PR từ fork; sau khi bị lộ chỉ `git commit --amend` rồi force push và coi là đã xử lý; token production dán vào kênh chat để "anh em tiện test"; agent nhận khóa quản trị đầy đủ dán thẳng vào system prompt.
