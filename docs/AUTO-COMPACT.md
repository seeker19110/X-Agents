# Auto-compact 500k cho phiên Claude Code

Quyết định của chủ dự án ngày 2026-09-26: dùng cơ chế native với cửa sổ 300000 token mỗi phiên; ngày 2026-10-10
nâng lên **500000 token mỗi phiên**.
Đây là mốc vận hành được chọn, chưa phải ngưỡng tối ưu đã đo trên X-Agents. Không xây bộ tóm tắt mới,
không tạo slash command che `/compact` hoặc `/autocompact`.

## Cấu hình đã tích hợp

`.claude/settings.json` giữ nguyên permissions và hooks cũ, thêm:

```json
{
  "autoCompactEnabled": true,
  "env": {
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "500000"
  }
}
```

Phạm vi là phiên Claude Code nạp cấu hình dự án này, không phải cấu hình toàn máy và không phải mọi provider
của X-Agents. Phiên CLI chạy ở repo khách khác hoặc bỏ qua project settings phải kiểm tra riêng; không suy
rằng nó tự nhận cấu hình này. Không sửa cấu hình bí mật hoặc hồ sơ cá nhân của người vận hành.

Theo tài liệu Claude Code, biến môi trường nhận số nguyên viết đầy đủ; `500k` không hợp lệ với nghĩa mong
muốn. Biến này ưu tiên hơn `/autocompact`, `--autocompact` và `autoCompactWindow`. Cửa sổ hiệu lực bị chặn bởi
context window của model: model 200k không trở thành model 500k. Nhịp compact có thể sớm hơn do cơ chế native;
không cam kết nó xảy ra đúng token thứ 500000. Không khai giả `CLAUDE_CODE_MAX_CONTEXT_TOKENS` để ép đạt mốc.

Cấu hình local/managed có thể ghi đè cấu hình dự án; `DISABLE_AUTO_COMPACT` hoặc `DISABLE_COMPACT` trong môi
trường có thể tắt cơ chế này. Repo không tự xoá cờ cá nhân/chính sách quản trị. Số phần trăm trên status line
đo theo cửa sổ model, không nhất thiết theo cửa sổ compact 500k.

## Không đổi các hàng rào hiện có

`company.runner.DEFAULT_MAX_INPUT_CHARS = 120_000` vẫn là **ký tự**, không phải token. `context.fit()` và
`_prune()` giữ nguyên: vòng tool tiếp tục giữ toàn văn kết quả của ba lượt gần nhất. Ngân sách đầu ra của
ticket, quyền tool, sandbox, gate và execution journal không thay đổi. Không áp mốc 500k cho mọi agent,
không cộng token của nhiều phiên để quyết compact một phiên.

## Giữ trạng thái và tiếp tục công việc

`CLAUDE.md` có mục `Compact Instructions` mà Claude đọc cùng luật dự án. Giữ mục tiêu/spec, quyết định kiến
trúc, giới hạn quyền/ngân sách, task dở, bước kế tiếp, branch/worktree/HEAD, file đổi, PR và bằng chứng test.
Đưa log/diff dài vào artifact phù hợp; tóm tắt chỉ giữ tham chiếu, không giữ bí mật hoặc dữ liệu khách thật.

Cập nhật hồ sơ `docs/thi-hanh/<mã>.md` và nhật ký phiên ở mỗi mốc công việc, không đợi auto-compact. Sau
compact, đọc lại đúng hồ sơ, luật package và trạng thái thực tế. Nếu task có execution journal/bus thì đối
chiếu chúng trước khi hành động; không chỉ tin bản tóm tắt. Compact không xác nhận hoàn thành, không duyệt
spec, không cấp quyền mới và không cho phép thực hiện lại tác dụng phụ đã hoàn tất.

Đây là hướng dẫn duy trì ngữ cảnh, không phải đảm bảo không mất thông tin. PR này không thêm hook
PreCompact/SessionStart, không tự chụp transcript hay ghi đè bus, và không thay cơ chế checkpoint đang có.

## Kiểm tra trên máy chạy thật

Mở phiên mới trong checkout/nhánh chứa thay đổi để tránh nhầm cấu hình đang được nạp. Không đổi gói/model
hay mua thêm context chỉ để đạt 500k.

1. Ghi `claude --version` trước khi mở phiên. Trong phiên, xem `/config` để xác nhận auto-compact bật,
   `/autocompact` để xem cửa sổ/override hiệu lực, và `/context` để xem ngữ cảnh đang dùng.
2. Xác nhận cửa sổ 500000 hoặc cửa sổ nhỏ hơn do model/chính sách. Khi lệch, kiểm tra settings local/managed
   và hai biến tắt compact; không chỉ đọc JSON của repo rồi kết luận CLI đã áp dụng.
3. Trên một việc thử không nhạy cảm, ghi trạng thái bền rồi dùng `/compact` để kiểm tra nội dung được giữ.
   Đọc lại trạng thái, xác nhận đúng HEAD/task/bước tiếp theo và không thực hiện lại việc đã xong.
4. Trong phiên dài thực tế, lưu bằng chứng auto-compact tự kích hoạt cùng model/version/cửa sổ hiệu lực.
   Thử thủ công ở bước 3 không chứng minh ngưỡng tự động. Không bơm token trả phí chỉ để làm đẹp báo cáo.

CLI không nhận `/autocompact` hoặc không báo override: kiểm tra phiên bản có hỗ trợ theo tài liệu hiện hành;
chưa xác nhận được thì ghi rõ chưa xác nhận, không báo auto-compact 500k đã hoạt động.

## Kiểm thử và hoàn tác

Kiểm tra cấu hình riêng, offline:

```bash
cd platform/console
uv run pytest -q tests/test_auto_compact_config.py
```

Cổng đầy đủ trước khi merge: `scripts/dev-task.sh gate console` từ gốc repo, rồi CI của PR. Các test mới
chỉ kiểm cấu hình/tài liệu/hàng rào; không giả lập token rồi tuyên bố đã đo Claude Code thật. Không thay
ngưỡng coverage hay giảm kiểm tra CI để thêm cấu hình này.

Hoàn tác: bỏ hai mục được thêm (`autoCompactEnabled`, `env.CLAUDE_CODE_AUTO_COMPACT_WINDOW`) qua PR; giữ các
biến env, permissions và hooks khác. Mở lại Claude Code vì xoá env trong file không gỡ biến khỏi phiên đang
chạy. Quay về mặc định native không xoá execution journal, bus hoặc tài liệu thi hành.

## Nguồn chính thức

Đối chiếu ngày 2026-09-26:

- [Biến môi trường Claude Code](https://code.claude.com/docs/en/env-vars): cửa sổ, đơn vị, thứ tự ưu tiên và cờ tắt.
- [Model và cửa sổ auto-compact](https://code.claude.com/docs/en/model-config#context-window-and-auto-compaction): giới hạn model và cách kiểm tra.
- [Phạm vi settings](https://code.claude.com/docs/en/settings): cấu hình dự án, local, managed.
- [Quản lý ngữ cảnh](https://code.claude.com/docs/en/best-practices#manage-context-aggressively): giữ chỉ dẫn compact trong CLAUDE.md.
