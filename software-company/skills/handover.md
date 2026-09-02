---
name: handover
version: 1
standards: [PMBOK Close Project or Phase, ISO/IEC 12207 (transition process), ITIL 4 Service Transition, ISO/IEC 25010 (maintainability), Escrow mã nguồn]
---
# Skill: handover

## Tiêu chuẩn tham chiếu
- PMBOK — Close Project or Phase: nghiệm thu, bàn giao sản phẩm, đóng hợp đồng, lưu hồ sơ, bài học
- ISO/IEC 12207: quy trình chuyển giao (transition) và bảo trì phần mềm
- ITIL 4 Service Transition và Knowledge Management cho chuyển giao vận hành
- ISO/IEC 25010: khả năng bảo trì là thuộc tính chất lượng phải chứng minh, không phải lời hứa
- Escrow mã nguồn khi hợp đồng yêu cầu bảo đảm cho khách

## Quy trình (làm đúng thứ tự)
Chốt phạm vi bàn giao theo hợp đồng từ khi ký, không để tới cuối → dựng danh mục bàn giao và theo dõi độ hoàn thành mỗi sprint → kiểm chứng bằng "dựng lại từ số không" trên máy của khách → chuyển giao tri thức qua các buổi có ghi hình và bài tập thực hành → chuyển quyền sở hữu tài khoản và hạ tầng → khách vận hành thử dưới sự hỗ trợ của ta → ký nghiệm thu bàn giao → giai đoạn bảo hành → đóng hợp đồng và lưu hồ sơ.
Bàn giao là hoạt động chạy suốt dự án; dự án nào chỉ bắt đầu bàn giao ở tuần cuối thì đã trễ.

## Quy tắc — danh mục bàn giao
- Mã nguồn đầy đủ trong kho của khách, kèm toàn bộ lịch sử git, nhánh và tag phát hành.
- Tài liệu: kiến trúc và ADR, sơ đồ hệ thống và luồng dữ liệu, tài liệu API, hướng dẫn cài đặt và vận hành, runbook sự cố, danh mục nợ kỹ thuật đã biết, hạn chế và rủi ro còn lại.
- Hạ tầng dưới dạng IaC dựng lại được, cấu hình theo môi trường, và pipeline CI/CD chạy được trong tổ chức của khách.
- Dữ liệu: lược đồ, script migration, dữ liệu mẫu đã ẩn danh, quy trình sao lưu và khôi phục đã diễn tập (xem `disaster-recovery`).
- Bảo mật: SBOM, kết quả quét mới nhất, danh sách bí mật cần xoay vòng khi bàn giao (xem `secrets-management`), mô hình phân quyền.
- Bàn giao phải qua kiểm chứng thật: một người của khách, chỉ dùng tài liệu, dựng được môi trường và chạy hết bộ test trong ≤ 1 ngày làm việc. Không đạt thì tài liệu chưa xong.
- Không bàn giao "sẽ hoàn thiện tài liệu sau": mục nào chưa xong thì ghi rõ trong biên bản kèm hạn và người chịu trách nhiệm.

## Quy tắc — chuyển giao tri thức và quyền sở hữu
- Tối thiểu 3 buổi có ghi hình: tổng quan kiến trúc và quyết định; vận hành thường ngày và xử lý sự cố; phát triển tính năng mới đầu-cuối.
- Chuyển giao ngược: người của khách tự thực hiện ít nhất một thay đổi thật đi hết vòng từ ticket tới production, ta chỉ ngồi cạnh quan sát.
- Quyền sở hữu tài khoản chuyển sang pháp nhân khách: tên miền, DNS, kho mã, cloud, kho artifact, chứng chỉ, cửa hàng ứng dụng, tài khoản dịch vụ bên thứ ba và hóa đơn.
- Mọi bí mật đều được xoay vòng tại thời điểm bàn giao; sau đó thu hồi toàn bộ quyền truy cập của người thuộc bên gia công trong ≤ 5 ngày làm việc, trừ tài khoản hỗ trợ bảo hành có giới hạn thời gian và phạm vi.
- Danh sách quyền truy cập trước và sau bàn giao được đối chiếu và ký; không để tài khoản cá nhân còn quyền vì "phòng khi cần".
- Bàn giao cả quan hệ vận hành: lịch trực, kênh cảnh báo, nhà cung cấp, và các hợp đồng phụ trợ.

## Quy tắc — bảo hành và tiêu chí kết thúc
- Bảo hành mặc định 90 ngày kể từ ngày ký nghiệm thu: sửa lỗi thuộc phạm vi đã nghiệm thu, không bao gồm tính năng mới; yêu cầu mới đi qua change request có báo giá.
- Thời gian phản hồi trong bảo hành theo mức nghiêm trọng thống nhất với `incident-management`, ghi trong hợp đồng, không suy diễn.
- Tiêu chí kết thúc: mọi mục danh mục bàn giao đã bàn giao và ký; kiểm chứng dựng lại đạt; không còn lỗi mức nghiêm trọng cao mở; quyền truy cập đã chuyển và đối chiếu; hóa đơn cuối đã phát hành; biên bản nghiệm thu có chữ ký hai bên.
- Sau khi đóng: lưu hồ sơ theo thời hạn hợp đồng, viết bài học kinh nghiệm vào `knowledge`, và xóa dữ liệu khách khỏi hệ thống của ta theo cam kết (xem `privacy-compliance`).

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Danh mục bàn giao đầy đủ và được theo dõi từ đầu dự án
- [ ] Mã nguồn, lịch sử git và tag phát hành nằm trong kho của khách
- [ ] Người của khách dựng lại được môi trường trong ≤ 1 ngày chỉ bằng tài liệu
- [ ] IaC và pipeline chạy được trong tổ chức của khách
- [ ] Runbook, ADR, nợ kỹ thuật và rủi ro còn lại đã ghi rõ
- [ ] Tối thiểu 3 buổi chuyển giao tri thức có ghi hình
- [ ] Khách đã tự làm trọn một thay đổi thật ra production
- [ ] Tài khoản, tên miền, cloud và hóa đơn đã chuyển quyền sở hữu
- [ ] Bí mật đã xoay vòng; quyền truy cập bên gia công đã thu hồi và đối chiếu
- [ ] Phạm vi và thời hạn bảo hành ghi rõ; biên bản nghiệm thu có chữ ký hai bên

## Ví dụ tốt
Dự án CRM kết thúc 30/09: danh mục 42 mục theo dõi từ sprint 1, hoàn thành 100% trước ngày ký. Kỹ sư của khách dựng môi trường từ `docs/setup.md` trong 5 giờ và chạy 918 test xanh. Ba buổi chuyển giao ghi hình; ngày 22/09 khách tự phát hành bản 1.9.1 lên production, ta chỉ quan sát. 17 tài khoản chuyển sang pháp nhân khách, 31 bí mật xoay vòng, quyền của 6 kỹ sư gia công thu hồi ngày 03/10. Bảo hành 90 ngày với 2 lỗi được sửa, kết thúc 29/12 và đóng hợp đồng.

## Ví dụ xấu
Tuần cuối mới bắt đầu viết tài liệu; kho mã vẫn nằm trong tổ chức của bên gia công và khách chỉ được cấp quyền đọc; hạ tầng dựng tay nên không ai dựng lại được; khóa API vẫn là khóa cũ mà 6 người đã nghỉ vẫn biết; "bảo hành" không ghi phạm vi nên khách yêu cầu thêm tính năng suốt 8 tháng miễn phí; không có biên bản nghiệm thu nên tranh chấp hóa đơn cuối kéo dài.
