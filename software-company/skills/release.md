---
name: release
version: 2
standards: [Google SRE, GitOps, Blue-green/Canary, SemVer, SLSA, Keep a Changelog]
---
# Skill: release

## Tiêu chuẩn tham chiếu
- Google SRE: phát hành từ từ, quan sát được, và lùi được
- GitOps: trạng thái mong muốn nằm trong git, hệ thống tự hội tụ về đó
- Blue-green và canary với tiêu chí thăng cấp dựa trên SLO
- SemVer cho phiên bản; Keep a Changelog cho ghi chú phát hành
- SLSA: artifact có nguồn gốc và chữ ký (xem `security`)

## Quy trình (làm đúng thứ tự)
Ứng viên phát hành (release candidate) từ trunk → cổng chất lượng (test, bảo mật, hiệu năng, nghiệm thu) → migration DB tương thích ngược đã chạy trước → triển khai canary tỉ lệ nhỏ → quan sát theo tiêu chí SLO trong cửa sổ đủ dài → thăng cấp từng bậc → phát hành đầy đủ → theo dõi sau phát hành → ghi chú phát hành và bài học.
Mỗi bậc thăng cấp là một quyết định có tiêu chí, không phải một thói quen bấm nút.

## Quy tắc — chuẩn bị
- Chỉ phát hành artifact bất biến đã ký, kèm SBOM, được build một lần và đi qua mọi môi trường (xem `devops`).
- Migration DB tách khỏi deploy code và tương thích ngược; phiên bản cũ và mới phải chạy được cùng lúc trong suốt quá trình phát hành (xem `database`).
- Runbook có trước khi nhận traffic: cách xác nhận khỏe mạnh, cách lùi, ai quyết định, và ngưỡng nào thì dừng.
- Ghi chú phát hành nêu thay đổi ảnh hưởng người dùng, thay đổi contract, và việc cần làm phía người vận hành.
- Cửa sổ phát hành tránh thời điểm không có người trực; không phát hành lớn ngay trước kỳ nghỉ trừ khi là bản vá khẩn.
- Mọi thứ rủi ro nằm sau feature flag để có thể tắt mà không cần triển khai lại.

## Quy tắc — canary và thăng cấp
- Canary bắt đầu ở tỉ lệ nhỏ (ví dụ 5%), thời gian đủ để chỉ số có ý nghĩa thống kê, và so với nhóm đối chứng cùng thời điểm — không so với hôm qua.
- Tiêu chí thăng cấp khai báo trước bằng số: tỉ lệ lỗi, độ trễ p95/p99, các chỉ số nghiệp vụ chính (tỉ lệ hoàn tất thanh toán, đăng ký...). Chỉ số nghiệp vụ quan trọng ngang chỉ số kỹ thuật.
- Tự động lùi khi vi phạm ngưỡng; con người có thể lùi bất cứ lúc nào mà không cần xin phép ai.
- Không thăng cấp khi còn cảnh báo đang mở hoặc chỉ số chưa ổn định; "chắc là do nhiễu" không phải lý do hợp lệ.
- Mỗi bản phát hành nhận diện được trong dữ liệu quan sát (nhãn phiên bản trong metric và trace) để so trước/sau.

## Quy tắc — lùi và bản vá
- Khả năng lùi dưới 5 phút phải được diễn tập thật, không chỉ ghi trên giấy; nếu một thay đổi không lùi được (đã đổi dữ liệu), phải nói rõ từ trước và có phương án bù trừ.
- Ưu tiên lùi trước, điều tra sau; không cố "sửa nhanh trên production" khi người dùng đang chịu ảnh hưởng (xem `incident-management`).
- Bản vá khẩn vẫn đi qua pipeline và cổng chất lượng tối thiểu; đường tắt duy nhất là rút ngắn cửa sổ quan sát, không phải bỏ kiểm thử.
- Sau phát hành, theo dõi tối thiểu một chu kỳ tải điển hình (thường là 24h) trước khi coi là ổn định.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi cổng chất lượng pass; artifact đã ký và có SBOM
- [ ] Migration tương thích ngược đã chạy trước; hai phiên bản chạy được cùng lúc
- [ ] Runbook và ghi chú phát hành có sẵn trước khi triển khai
- [ ] Tiêu chí thăng cấp khai báo trước bằng số, gồm cả chỉ số nghiệp vụ
- [ ] Canary có nhóm đối chứng và cửa sổ quan sát đủ dài
- [ ] Tự động lùi hoạt động; khả năng lùi < 5 phút đã được diễn tập
- [ ] SLO được giữ trong suốt canary; không thăng cấp khi còn cảnh báo mở
- [ ] Bản phát hành nhận diện được trong metric và trace
- [ ] Có theo dõi sau phát hành và ghi lại kết quả

## Ví dụ tốt
2.4.0: canary 5% trong 15 phút — tỉ lệ lỗi 0.04% (đối chứng 0.05%), p95 210ms (đối chứng 205ms), tỉ lệ hoàn tất thanh toán không đổi → 25% trong 30 phút → 100%. Feature flag `new_checkout` bật riêng, có thể tắt trong 10 giây. Diễn tập lùi tuần trước: 3 phút 12 giây. Ghi chú phát hành nêu contract lên 1.3.0 (thêm trường optional).

## Ví dụ xấu
Deploy thẳng 100% vào chiều thứ Sáu; migration `DROP COLUMN` chạy cùng lúc với deploy nên không lùi được; tiêu chí thăng cấp là "nhìn thấy ổn"; chỉ số kỹ thuật đẹp nhưng tỉ lệ thanh toán thành công giảm 30% và không ai theo dõi.
