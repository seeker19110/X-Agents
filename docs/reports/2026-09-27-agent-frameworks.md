# Đối chiếu 15 repo agent → X-Agents

Ngày 2026-09-27. Đọc README của 15 repo trong ảnh người dùng cung cấp, rồi đối chiếu `AGENTS.md`, `ARCHITECTURE.md`, `CODEMAP.md`, mã `xagents_core` và tên test/cổng CI hiện hành. Phạm vi nghiên cứu là kiến trúc và điểm tích hợp; **không** coi README là bằng chứng một tính năng chạy được trong X-Agents. Không vendor SDK, không thay ngầm provider hay tăng quyền tool.

## Quyết định cho từng nguồn

| Nguồn | Ý tưởng đáng giữ | Tình trạng tại X-Agents / quyết định |
|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | Chạy bền, checkpoint, human interrupt | Execution journal/rehydrate và HumanGate đã có; dùng test gián đoạn hiện tại làm baseline. |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Handoff, guardrails, sessions, tracing | Registry/bus/runner/guard/trace đã làm việc này theo contract nội bộ; không thêm agent loop thứ hai. |
| [Google ADK](https://github.com/google/adk-python) | Workflow xác định, tool, nhiều agent | Orchestrator FSM + model quyết định/code hành động; không buộc Gemini ở lõi. |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | Structured output và eval | Schema topic và eval recording/replay đã có; đo trên payload thật trước khi đổi validator. |
| [Semantic Kernel](https://github.com/microsoft/semantic-kernel) | Plugin/provider | README chuyển hướng sang [Microsoft Agent Framework](https://github.com/microsoft/agent-framework); giữ adapter provider hiện hữu. |
| [smolagents](https://github.com/huggingface/smolagents) | Sandbox cho code agent | Sandbox tiến trình/container đã có; chỉ cấp quyền cần dùng. |
| [AgentScope](https://github.com/agentscope-ai/agentscope) | Quan sát nhiều agent | Audit log và trace có actor/model/tool/cost; không cần thêm nền telemetry trước khi có ca không quan sát được. |
| [Mastra](https://github.com/mastra-ai/mastra) | Workflow resume, memory | TS SDK không hợp lõi Python; áp ý tưởng thử resume bằng journal. |
| [browser-use](https://github.com/browser-use/browser-use) | Agent web | Chưa có tác vụ web/ca lỗi cụ thể chứng minh cần dependency này; chỉ thử adapter có giới hạn khi ticket thật yêu cầu. |
| [Mem0](https://github.com/mem0ai/mem0) | Truy hồi ký ức | Blackboard/context là ngữ cảnh công việc; chưa coi đó là long-term user memory. Cần retention/xóa/quyền trước khi thêm memory. |
| [Letta](https://github.com/letta-ai/letta) | Trạng thái bền | README chuyển mã đang phát triển sang [letta-code](https://github.com/letta-ai/letta-code); journal là nguồn state hiện tại. |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | Đánh giá coding agent trên repo thật | README khuyên [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent); giữ eval replay + gate trên worktree thật. |
| [OpenHands](https://github.com/OpenHands/OpenHands) | Self-hosted coding control center | `All-Hands-AI/OpenHands` trong ảnh đã chuyển tên; console/gateway hiện đảm nhiệm một phần, không fork giao diện. |
| [MCP reference servers](https://github.com/modelcontextprotocol/servers) | Kết nối tool và ranh giới quyền | `mcp_bridge.py` đã có; upstream ghi rõ các server là reference, phải đánh giá riêng trước production. |
| [CAMEL](https://github.com/camel-ai/camel) | Hợp tác nhiều agent | Bus/registry/role sẵn có; chỉ tách việc độc lập, không tăng số agent vì một benchmark nghiên cứu. |

## Ba cột và đường nghiệm thu

| Đã có và sâu hơn | Bằng chứng code/test hiện hành |
|---|---|
| State bền và resume theo event, không dựa lịch sử chat | `platform/xagents-core/src/xagents_core/execution.py`, `tests/test_execution_atomic.py`, `test_execution_reopen.py`; `company/orch/rehydrate.py`. |
| Gate người và ranh giới tool | `xagents_core/gates.py`, `guard.py`, `sandbox.py`; `test_gates.py`, `test_sandbox.py`, `company/tests/test_gate_trust.py`. |
| Eval, audit, trace, ngân sách | `xagents_core/evals.py`, `trace.py`, `context.py`; `test_evals.py`, `test_trace.py`, `test_context.py`; CI `quality`. |

| Đã có nhưng cần làm rõ | Tích hợp trong đợt này |
|---|---|
| Có nhiều module cùng chức năng nên danh sách repo dễ dẫn tới cài một SDK thứ hai | Bản đồ quyết định và đường test trong tài liệu này; tiêu chí mở rộng dưới đây áp trước khi thêm dependency. |
| “Memory” thường trộn lẫn journal, blackboard và thông tin người dùng xuyên phiên | Ghi rõ ba loại và điều kiện quyền/xóa/retention trong tài liệu này. |

| Chưa có / chưa cần | Điều kiện xem lại |
|---|---|
| Browser controller; vector DB ký ức; ACP/A2A bridge; workflow engine khác | Chỉ mở khi ticket có ca thực, test đỏ tại biên hiện tại, lợi ích đo được, threat model và chủ dữ liệu rõ. |
| Import reference MCP server vào production | Chỉ sau kiểm quyền, xác thực, timeout, lọc dữ liệu và thử mất kết nối với server cụ thể. |

## Hợp đồng tích hợp khi có ticket thật

1. Ghi nhu cầu và ca lỗi đo được: input, tác dụng phụ, phạm vi quyền, ngân sách token/thời gian, cách hủy hoặc resume. Phân biệt **journal** (sự thật sự kiện), **blackboard** (artifact công việc) và **ký ức người dùng** (dữ liệu riêng có vòng đời).
2. Viết test đỏ trước theo `AGENTS.md`: dừng giữa ghi rồi resume đúng một lần; input tool sai bị từ chối; model không thể tự duyệt gate; log không lộ bí mật; replay eval so baseline. Chọn đúng test theo loại tích hợp, không giả vờ mọi dự án đều cần đủ năm.
3. Đặt adapter ở ranh giới hiện hữu (`llm`, `tools`, `mcp_bridge`, `sandbox` hoặc `context`), không tạo bus/runner/gate song song; schema và quyền là code xác định. Không dùng tài liệu/response ngoài như lệnh cho agent.
4. Nêu rõ chi phí, license, dữ liệu gửi đi, kế hoạch rollback và chủ bảo trì; thực hiện ADR khi đổi kiến trúc. Chạy `scripts/dev-task.sh gate <gói>` và eval replay phù hợp, ghi output thật trong PR.

**Giới hạn:** đây là tích hợp phương pháp và đường nghiệm thu vào kiến trúc hiện tại, chưa thêm browser/memory/SDK runtime. Không có phép đo hiện tại chứng minh một thư viện trong ảnh sẽ cải thiện chất lượng X-Agents. Các repo được khảo sát ở README hiện hành; API, release, license và tính năng cụ thể phải kiểm ở commit được chốt trước khi cài.
