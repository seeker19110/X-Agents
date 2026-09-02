---
name: legacy-modernization
version: 1
standards: [Strangler Fig (Martin Fowler), Branch by Abstraction, Parallel Run / Dark Launch, Anti-Corruption Layer (DDD), Working Effectively with Legacy Code (Feathers)]
---
# Skill: legacy-modernization

## Tiêu chuẩn tham chiếu
- Strangler Fig: dựng hệ mới bao quanh hệ cũ, cắt dần từng khả năng, không viết lại toàn bộ một lần
- Branch by Abstraction: chèn lớp trừu tượng để hai hiện thực cùng tồn tại trên nhánh chính
- Anti-Corruption Layer (DDD): dịch mô hình cũ sang mô hình mới, chặn ngữ nghĩa cũ rò vào hệ mới
- Parallel Run / dark launch: chạy song song cũ–mới, đối chiếu kết quả trước khi tin hệ mới
- Feathers: đặt seam và test đặc tả (characterization test) trước khi động vào code không có test

## Quy trình (làm đúng thứ tự)
Lập bản đồ khả năng và luồng dữ liệu của hệ cũ (xem `codebase-analysis`) → chọn lát cắt nhỏ nhất có giá trị kinh doanh → viết characterization test khóa hành vi hiện tại → dựng facade định tuyến trước hệ cũ → hiện thực lát cắt ở hệ mới sau Anti-Corruption Layer → chạy song song và đối chiếu kết quả → cắt lưu lượng theo phần trăm tăng dần → xác nhận ổn định rồi xóa code cũ của lát cắt → lặp lại cho lát tiếp theo.
Không bao giờ viết lại toàn bộ ("big bang"): rủi ro và chi phí tăng phi tuyến còn giá trị chỉ đến ở cuối.

## Quy tắc — cắt lát và chống tham chiếu vòng
- Mỗi lát cắt ≤ 4 tuần công và tự phát hành được; lát nào không cắt nhỏ được thì chưa hiểu đủ, quay lại phân tích.
- Chiều phụ thuộc chỉ một hướng: mới → cũ qua Anti-Corruption Layer. Hệ cũ gọi ngược hệ mới là tham chiếu vòng, cấm; cần thì đảo bằng sự kiện hoặc webhook một chiều.
- Không chia sẻ bảng dữ liệu giữa cũ và mới ở trạng thái ghi kép lâu dài: chọn một bên là nguồn sự thật cho mỗi thực thể và ghi rõ trong ADR.
- Giai đoạn ghi kép (nếu bắt buộc) phải có ngày hết hạn trong ticket và cơ chế đối soát chênh lệch hằng ngày.
- Facade/định tuyến nằm ở một chỗ duy nhất (gateway hoặc reverse proxy), có cấu hình khai báo, đổi được mà không phát hành lại.
- Không mang nợ kỹ thuật của hệ cũ sang hệ mới chỉ để "giống cũ": hành vi sai đã biết được ghi thành ticket và quyết định giữ hay sửa, có người ký.

## Quy tắc — chạy song song và đối chiếu
- Parallel run: hệ mới xử lý bản sao lưu lượng thật ở chế độ chỉ đọc/không tác dụng phụ, kết quả ghi lại và so với hệ cũ.
- Đối chiếu định lượng theo trường, không so chuỗi thô: khai báo trước danh sách khác biệt chấp nhận được (làm tròn, thứ tự, timestamp).
- Ngưỡng cắt lưu lượng: tỉ lệ khớp ≥ 99.9% trên ≥ 10.000 mẫu thật liên tiếp trong ≥ 7 ngày, và không có khác biệt nào chạm tiền hoặc quyền.
- Nấc cắt lưu lượng: 1% → 5% → 25% → 50% → 100%, mỗi nấc giữ tối thiểu 24h và qua ít nhất một chu kỳ tải cao điểm.
- Định tuyến ổn định theo khóa người dùng/tenant (hashing), không random mỗi request, để lỗi tái hiện được và trải nghiệm không nhảy qua lại.
- Mọi tác dụng phụ (email, thanh toán, webhook ra ngoài) bị chặn ở nhánh song song bằng cờ, kiểm chứng bằng test trước khi bật.

## Quy tắc — tiêu chí dừng và rút lui
- Mỗi nấc có tiêu chí dừng khai báo trước: lỗi 5xx tăng > 0.1 điểm phần trăm, p95 xấu đi > 20%, hoặc bất kỳ sai lệch dữ liệu tiền tệ → rút lui ngay.
- Rút lui là đổi cấu hình định tuyến về 0%, hoàn tất trong ≤ 5 phút, đã diễn tập ít nhất một lần trước nấc đầu tiên.
- Chỉ xóa code và dữ liệu cũ sau ≥ 30 ngày ở 100% không sự cố, và sau khi xác nhận không còn tiêu thụ nào (đo bằng metric truy cập, không đoán bằng grep).
- Dự án có mốc "burn-down" công khai: số khả năng đã cắt / tổng, cập nhật mỗi sprint, báo khách (xem `project-management`).

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Có bản đồ khả năng hệ cũ và lát cắt hiện tại ≤ 4 tuần công
- [ ] Characterization test khóa hành vi cũ trước khi sửa
- [ ] Anti-Corruption Layer tồn tại; không có tham chiếu vòng cũ ← mới
- [ ] Nguồn sự thật cho mỗi thực thể được khai báo trong ADR
- [ ] Chạy song song đạt tỉ lệ khớp ≥ 99.9% trên ≥ 10.000 mẫu, ≥ 7 ngày
- [ ] Tác dụng phụ bị chặn ở nhánh song song
- [ ] Cắt lưu lượng theo nấc 1/5/25/50/100%, định tuyến ổn định theo khóa
- [ ] Tiêu chí dừng khai báo trước; rút lui ≤ 5 phút và đã diễn tập
- [ ] Code cũ chỉ xóa sau 30 ngày ổn định và đã đo không còn tiêu thụ

## Ví dụ tốt
Cắt module tính giá khỏi monolith PHP: 42 characterization test khóa hành vi từ log thật. Dịch vụ mới sau ACL, đọc bảng giá cũ ở chế độ chỉ đọc. Parallel run 9 ngày, 14.300 mẫu, khớp 99.96%; 6 khác biệt đều do làm tròn đã khai báo. Cắt 1% ngày 12/08, 100% ngày 27/08; rollback đã diễn tập, mất 90 giây. Xóa code cũ 30/09 sau khi metric `legacy_pricing_calls` bằng 0 suốt 31 ngày.

## Ví dụ xấu
Viết lại toàn bộ trong 9 tháng, phát hành một lần vào cuối tuần; không có test đặc tả nên không ai biết hệ mới có giữ đúng hành vi không; hệ cũ gọi ngược API mới để "tạm thời" dùng chung phiên; ghi kép hai cơ sở dữ liệu không đối soát, ba tháng sau phát hiện lệch 1.200 đơn; rollback chỉ tồn tại trên giấy.
