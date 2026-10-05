# Figma Context MCP trong X-Agents — 2026-10-05

Nguồn: `GLips/Figma-Context-MCP` (MIT, `c083d65c7e002923e7cb98f4e3bdafb105e90f6d`). Repo upstream chuyển file/node Figma thành layout/style/text/component context cô đọng qua `get_figma_data`; `download_figma_images` riêng, có giới hạn thư mục. Upstream build/type-check xanh; 250 test pass, 1 integration test skip.

| Đã có sâu hơn | Còn thiếu cụ thể | Quyết định |
| --- | --- | --- |
| ADR-0024 chỉ cho Claude CLI gọi toolbox X-Agents qua sandbox, allowlist, audit và trần lượt; handoff projects-template đã pin spec/policy và approval ngoài luồng | Contract chưa có manifest cho frame và bytes context chính xác được dùng | Không đưa Figma MCP vào orchestrator. Nối context bằng `figma_contexts` gồm HTTPS URL, node ID, đường dẫn và SHA-256; `template_handoff` xác minh snapshot trong evidence root. |
| `DesignBrief` đã giữ mục tiêu, states, accessibility và validation | Nguồn Figma chỉ có thể nằm lẫn trong prose | Giữ DesignBrief native, tham chiếu manifest vào `research_basis`; snapshot Figma là dữ liệu không tin cậy, không là lệnh hay approval. |

Integration sử dụng `npx figma-developer-mcp@0.13.2 --stdio --no-telemetry` ở coding client theo docs của projects-template. Token đọc-only ở secret store client, không đi qua X-Agents. Không gọi API hoặc phụ thuộc token trong CI. Chi tiết schema/hành vi: [ADR-0048](../../companies/software-company/docs/adr/0048-figma-context-snapshot-handoff.md) và [`companies/software-company/docs/integrations/figma-context-mcp.md`](../../companies/software-company/docs/integrations/figma-context-mcp.md).
