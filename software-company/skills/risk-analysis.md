---
name: risk-analysis
version: 2
standards: [ISO 31000, FMEA (RPN), STRIDE, Pre-mortem, Risk register]
---
# Skill: risk-analysis

## Tiêu chuẩn tham chiếu
- ISO 31000: nhận diện → phân tích → đánh giá → xử lý → theo dõi
- FMEA: RPN = mức nghiêm trọng × khả năng xảy ra × khó phát hiện (thang 1–5 hoặc 1–10, khai báo rõ)
- STRIDE cho rủi ro bảo mật của mọi luồng dữ liệu nhạy cảm (chi tiết ở `threat-modeling`)
- Pre-mortem: giả định dự án đã thất bại, hỏi vì sao — cách hiệu quả nhất để lộ rủi ro bị bỏ qua
- Sổ rủi ro (risk register) sống, có chủ sở hữu và trạng thái

## Quy trình (làm đúng thứ tự)
Pre-mortem với các bên liên quan → liệt kê rủi ro theo nhóm (kỹ thuật, dữ liệu, bảo mật, pháp lý, vận hành, phụ thuộc bên ngoài, con người, chi phí) → chấm điểm nhất quán → chọn cách xử lý (tránh / giảm / chuyển / chấp nhận) → gán chủ sở hữu và tín hiệu cảnh báo sớm → đưa hành động giảm nhẹ vào ticket thật → rà lại mỗi sprint và khi kiến trúc đổi.
Rủi ro không có hành động và chủ sở hữu chỉ là một câu than phiền được viết đẹp.

## Quy tắc — nhận diện
- Nhìn đủ nhóm, không chỉ nhóm kỹ thuật: pháp lý và dữ liệu cá nhân, phụ thuộc vào khách và bên thứ ba, năng lực đội, chi phí vận hành, và rủi ro vận hành sau khi bàn giao.
- Rủi ro viết dưới dạng nhân quả cụ thể: "vì X nên có thể xảy ra Y dẫn tới hậu quả Z", không viết "rủi ro bảo mật".
- Điều chưa biết (unknown) là một loại rủi ro: xử lý bằng ticket khảo sát có timebox, không bằng lời hứa.
- Giả định trong spec là nguồn rủi ro hàng đầu; mỗi giả định chưa xác nhận nên có một dòng trong sổ rủi ro.

## Quy tắc — chấm điểm và xử lý
- Thang điểm khai báo trước và dùng nhất quán; hai người chấm cùng rủi ro phải ra kết quả gần nhau. Ghi lý do cho từng thành phần điểm.
- Khó phát hiện là thành phần hay bị xem nhẹ: rủi ro nhỏ nhưng âm thầm thường tốn kém hơn rủi ro lớn mà thấy ngay.
- Mọi rủi ro High/Critical phải có hành động giảm nhẹ, chủ sở hữu, hạn, và ticket thật; không được ở trạng thái "đang theo dõi" vô thời hạn.
- Chấp nhận rủi ro là một quyết định có người ký, có ADR, và có điều kiện xem lại — không phải im lặng bỏ qua.
- Ưu tiên xử lý theo tích số ảnh hưởng và chi phí xử lý; nêu rõ khi cách rẻ nhất là cắt phạm vi hoặc lùi lịch.
- Mỗi rủi ro nên có tín hiệu cảnh báo sớm đo được (chỉ số, mốc thời gian, sự kiện) để biết nó đang thành hiện thực trước khi quá muộn.

## Quy tắc — duy trì
- Sổ rủi ro sống: rà mỗi sprint, đóng rủi ro đã hết, mở rủi ro mới khi phạm vi hoặc kiến trúc đổi.
- Rủi ro đã thành hiện thực thì đối chiếu: đã dự đoán chưa, giảm nhẹ có tác dụng không — ghi vào `knowledge` để lần sau chấm điểm sát hơn.
- Không thổi phồng để an toàn: chấm mọi thứ ở mức cao làm mất khả năng phân biệt và khiến không ai đọc sổ rủi ro nữa.
- Rủi ro bảo mật chi tiết chuyển sang `threat-modeling`; rủi ro riêng tư chuyển sang `privacy-compliance`; sổ rủi ro giữ liên kết, không chép lại.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Đã rà đủ các nhóm rủi ro, không chỉ kỹ thuật
- [ ] Mỗi rủi ro viết dạng nhân quả cụ thể, có nguồn
- [ ] Thang điểm khai báo và dùng nhất quán, có lý do cho điểm
- [ ] Không rủi ro High/Critical nào thiếu hành động giảm nhẹ
- [ ] Mỗi rủi ro có chủ sở hữu, hạn và ticket thật
- [ ] Rủi ro được chấp nhận có ADR và người ký
- [ ] Có tín hiệu cảnh báo sớm đo được cho rủi ro quan trọng
- [ ] Sổ rủi ro được rà mỗi sprint; rủi ro đã xảy ra được đối chiếu và ghi bài học

## Ví dụ tốt
RISK-3 (Bảo mật, High, RPN 45 = 5×3×3): vì token lưu ở `localStorage` nên một lỗ XSS bất kỳ có thể dẫn tới chiếm phiên của toàn bộ người dùng đăng nhập. Giảm nhẹ: chuyển sang cookie `HttpOnly` + `SameSite` và bật CSP không `unsafe-inline`; chủ sở hữu: frontend; ticket TCK-58; hạn 12/09. Cảnh báo sớm: số vi phạm CSP báo về máy chủ > 0.

## Ví dụ xấu
"Có thể có rủi ro bảo mật." Không nguyên nhân, không hậu quả, không điểm, không ai chịu trách nhiệm; toàn bộ 14 rủi ro đều chấm High; sổ rủi ro viết một lần lúc khởi động và không ai mở lại.
