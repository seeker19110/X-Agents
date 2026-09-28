"""`xagents_core` — lõi chung của các công ty AI trong X-Agents (ADR gốc `docs/adr/0001-loi-chung-xagents-core.md`).

`company` (software-company) và `keeper` import từ đây thay vì tự fork: bus sự kiện, client LLM, runner, chống
prompt injection, human gate, blackboard, sandbox, quan sát được. Mã chuyển vào qua bảy bước K3.1–K3.7 (#198),
mỗi bước một PR để `main` không bao giờ đỏ giữa chừng.

Luật của chỗ này, đọc trước khi thêm bất cứ gì:

1. **Core không biết tên công ty nào.** Mọi điểm khác nhau giữa các công ty đi qua `CoreConfig`.
   Một `if cfg.prefix == "COMPANY"` trong core là fork mọc lại dưới dạng câu điều kiện — nếu thấy mình sắp
   viết nó, thứ đang thiếu là một trường trong `CoreConfig`.
2. **Cơ chế ở core, nghĩa ở package.** Bus/llm/runner/guard là cơ chế. `Topic` Literal, `Task`, `tools_prompt`
   là nghĩa — chúng ở lại package của từng công ty.
3. **Company là gốc** (luật lúc hợp nhất K3, docstring các module còn dẫn tới). Với mỗi module, bản company là bản
   vào core vì đã ăn nhiều sự cố thật; bản của công ty kia (studio, tách sang repo riêng ở #259) được nâng theo,
   đổi hành vi có chủ ý thì ghi CHANGELOG.
"""
from __future__ import annotations

from .config import CoreConfig, TopicACL

__version__ = "0.1.0"
__all__ = ["CoreConfig", "TopicACL", "__version__"]
