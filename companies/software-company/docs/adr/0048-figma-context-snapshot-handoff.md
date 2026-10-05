# ADR-0048: Figma context crosses the handoff as a verified artifact

Trạng thái: Accepted · Ngày: 2026-10-05 · Quyết định theo yêu cầu tích hợp Figma của chủ dự án.

## Bối cảnh

`GLips/Figma-Context-MCP` cung cấp cây layout/style/text và tải asset từ Figma. Tích hợp trực tiếp server này vào vòng tool của `company` sẽ phá giới hạn của ADR-0024: `claude -p` chỉ được gọi toolbox của công ty, mọi thao tác vẫn qua allowlist, sandbox, audit và bộ đếm lượt. Handoff projects-template hiện pin spec, nhưng chưa pin design snapshot.

## Quyết định

1. Coding client chạy Figma MCP tùy chọn bên ngoài orchestrator; X-Agents không giữ Figma token và không spawn MCP server bên thứ ba.
2. `DeliveryContract` nhận `figma_contexts` tùy chọn gồm URL Figma HTTPS, node ID, artifact path tương đối và SHA-256. Profile có thể giữ cùng manifest trong `DesignBrief` để product/builder dùng chung đúng frame.
3. `company.template_handoff` xác minh lại bytes trong evidence root trước khi trả native contract. Path traversal, symlink escape, digest sai, URL/node ID sai hoặc artifact không hợp lệ bị từ chối.
4. Context là dữ liệu không tin cậy, không là approval, acceptance criteria hay command. Khi không dùng Figma, trường vẫn rỗng và serialization hiện hữu không đổi.

## Hệ quả

Snapshot là bất biến cho mỗi lần handoff; refresh thiết kế tạo bytes/digest và approval mới. Kích thước mỗi snapshot tối đa 1 MiB, tối đa tám frame mỗi contract. Không có Figma token thì các workflow offline vẫn dùng như trước. Không tự tải ảnh hay gọi Figma trong CI.

## Liên quan

- Nguồn: `../../docs/reports/2026-10-05-figma-context-mcp.md` và projects-template `docs/reports/2026-10-05-figma-context-mcp-review.md`.
- Mã: `delivery_contract.py`, `template_handoff.py`; test trong `tests/test_template_handoff.py`.
- ADR-0024 tiếp tục giữ ranh giới MCP bridge nội bộ.
