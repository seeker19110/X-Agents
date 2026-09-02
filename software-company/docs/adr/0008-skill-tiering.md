# ADR-0008: Chia skill hai mức — đầy đủ và rút gọn

Trạng thái: Accepted · Ngày: 2026-09-02 · Bổ sung ADR-0004

## Bối cảnh
Sau khi nâng 38 skill lên mức master, system prompt của cả công ty phình lên ~524.000 ký tự
(~175.000 token). Nguyên nhân không phải số agent mà là nhân bản skill: `testing` nằm trong 8 agent,
`security` trong 6, `observability` trong 9 — mỗi lượt chạy gửi lại toàn văn. Một ticket đi qua 6 agent
tốn ~60.000 token system prompt trước khi đọc dòng dữ liệu nào.

Phương án "để agent tự đọc phần sâu khi cần" không dùng được: runner gọi model đúng một lượt cho mỗi
envelope (`AgentRunner.generate`), không có vòng lặp tool nên agent không thể tự lấy thêm tài liệu.

## Quyết định
Mỗi skill giữ nguyên một file, nhưng được nạp ở hai mức:

| Mức | Nội dung nạp | Khai báo |
|---|---|---|
| Đầy đủ | toàn văn: tiêu chuẩn tham chiếu, quy trình, mọi quy tắc, ví dụ tốt/xấu | `skills: [...]` |
| Rút gọn | H1 + `## Quy trình` + `## Checklist` (~23% độ dài) | `skills_core: [...]` |

Quy tắc gán: agent **chủ quản** một lĩnh vực nạp đầy đủ; agent chỉ phải **tuân thủ** lĩnh vực đó nạp
rút gọn. Ví dụ backend nạp đầy đủ `engineering-common`, `backend`, `api-contract`; `testing`, `security`,
`database` chỉ ở mức rút gọn vì qa-debugger, security-engineer và database mới là chủ quản.

Phần rút gọn được gắn nhãn rõ trong prompt: agent phải đạt checklist nhưng không tự quyết phần chuyên sâu —
cần chi tiết thì hỏi qua topic. Điều này biến giới hạn token thành ranh giới trách nhiệm rõ hơn.

Đồng thời bỏ trùng lặp: skill đã được `engineering-common` phủ ở mức nguyên tắc (test trước khi merge,
không secret trong code, validate biên, timeout) không còn nạp đầy đủ ở agent kỹ thuật.

Bất biến: mọi skill phải có `## Quy trình` và `## Checklist` (`load_skill` ném lỗi nếu thiếu);
một skill không được vừa đầy đủ vừa rút gọn ở cùng agent; mỗi agent có ít nhất một skill mức đầy đủ.

## Hệ quả
- Tổng system prompt 524.024 → 283.030 ký tự (~175.000 → ~94.000 token), giảm 46% mà không xóa nội dung nào.
- Front matter agent thêm `skills_core`; `registry.json` golden thêm trường tương ứng; version mọi agent +1.
- Chi phí thật giảm nhiều hơn con số trên khi bật prompt cache, vì phần cắt đi là phần lặp lại giữa các agent.
- Đổi mục lõi của một skill nay ảnh hưởng mọi agent nạp nó ở mức rút gọn — golden test bắt được.
