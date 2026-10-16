# Câu trả lời cố định của người vận hành — lượt đo DHCB-B1

Người vận hành **không thẩm định, không gợi ý kỹ thuật**. Mỗi lần khung cần người, chỉ dán đúng một câu dưới đây
và ghi một dòng `--can-thiep "<phút>:<việc>"` (`README.md` §5). Câu nào không có ở đây thì không trả lời, mà ghi
việc đó vào `ghi_chu` của lượt. Đổi một câu là đổi phiên bản phép đo, giống như đổi đề bài.

| Tình huống | Câu trả lời / lệnh |
|---|---|
| Câu hỏi làm rõ (X-Agents `product[intake]`; X-Templates nếu hỏi) | `Đề bài DE-BAI.md là toàn bộ thông tin khách có. Điều đề bài không nêu: chọn phương án đơn giản nhất mà vẫn an toàn, và ghi lại giả định.` |
| X-Agents: gate `spec`, `release`, `acceptance` | `gate_cli approve <subject> --by human:do --reason "root_cause: lượt đo hai khung, người vận hành không thẩm định; decision: approve theo kịch bản đo; hint: không có — làm theo DE-BAI.md"` |
| X-Agents: gate `escalation` lần đầu của một subject | `approve`, cùng lý do như dòng trên |
| X-Agents: gate `escalation` lần hai của cùng subject | `reject` với lý do `root_cause: lượt đo, escalation lặp; decision: reject theo kịch bản đo; hint: không có`; ghi lượt là `ket_cuc=kẹt` nếu dự án dừng hẳn |
| X-Agents: change request | `decide-change <cid> deferred --by human:do`, lý do `lượt đo: không đổi phạm vi so với DE-BAI.md` |
| X-Agents: DPIA / dữ liệu cá nhân | approve, lý do `root_cause: đề bài chỉ dùng dữ liệu giả, chạy cục bộ; decision: approve theo kịch bản đo; hint: không có` |
| X-Templates: `loop defer` / `done-pending-human` | Dán vào phiên: `Lượt đo: không có người xử lý. Việc đề bài không đòi thì bỏ; việc đề bài đòi thì tự chọn phương án tự host an toàn.` rồi `loop resume --reason "lượt đo"` |
| X-Templates: `blocked` | Không gỡ. Lượt kết thúc với `ket_cuc=blocked` |
| Hỏi quyền (phiên lỡ mở ở chế độ hỏi) | Cho phép nếu lệnh chỉ chạm thư mục lượt đo; từ chối nếu chạm ngoài. Mỗi lần là một can thiệp |

Không bao giờ: sửa code tay, `takeover`, `comment` vào ticket, viết `hint` kỹ thuật, chạy lại một bước thay khung,
bật `reviewer:tu-dong` (lượt duyệt của nó không ghi token — `do_hai_khung.py` sẽ báo `day_du: false`).
