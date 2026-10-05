# Figma context từ projects-template

Coding client có thể dùng `figma-developer-mcp@0.13.2` tùy chọn theo hướng dẫn trong projects-template `docs/framework/figma-context-mcp.md`. Token đọc-only nằm trong secret store của coding client; không truyền vào X-Agents, `llm.yaml`, task, bus hoặc prompt.

Khi một dự án dùng Figma, lưu snapshot context tối thiểu trong checkout dự án, thêm manifest vào `DeliveryContract.figma_contexts`, và dẫn nguồn trong `DesignBrief.research_basis` để product/builder hiểu snapshot gắn với quyết định thiết kế nào:

```json
{
  "source_url": "https://www.figma.com/design/FILE_KEY/App?node-id=12-34",
  "node_id": "12:34",
  "artifact_ref": "docs/design/figma/checkout-12-34.md",
  "artifact_sha256": "<64 lowercase hex characters>"
}
```

`artifact_ref` phải nằm trong evidence root và trỏ tới snapshot bytes đã hash. `company.template_handoff` xác minh file, SHA-256, URL HTTPS ở `figma.com` và cú pháp node ID trước khi tạo native delivery contract. Bundle và policy vẫn phải được pin độc lập; chuẩn bị thành công không chứng thực approval, không chạy lệnh và không đánh dấu completion.

Context Figma được coi là input ngoài không tin cậy. Product/builder dùng nó làm bằng chứng về bố cục và component, rồi ghi quyết định, states, accessibility và tiêu chí nghiệm thu vào artifacts native. X-Agents không gọi API Figma và không nới quyền MCP bridge.
