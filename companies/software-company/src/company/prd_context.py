"""Cắt PRD Markdown theo mục để tiêu chí nghiệm thu không biến mất giữa hai nửa văn bản."""

from __future__ import annotations

import re

from .context import cut_middle

_SECTION = re.compile(r"(?m)^##\s+.+$")
_ACCEPTANCE = re.compile(r"nghiệm thu|acceptance|tiêu chí", re.IGNORECASE)
_STORY = re.compile(r"user story|câu chuyện người dùng", re.IGNORECASE)
_NFR = re.compile(r"phi chức năng|non.functional|nfr", re.IGNORECASE)


def cut_prd_sections(namespace: str, content: str, limit: int, note: str) -> str:
    """Giữ trọn mục quan trọng nếu vừa chỗ; các mục bị bỏ có nhãn và đường đọc bản gốc."""
    headings = list(_SECTION.finditer(content)) if namespace == "prd" else []
    if len(content) <= limit:
        return content
    if not headings:
        return cut_middle(content, limit, note=note)
    prefix = content[:headings[0].start()][:80]
    sections = [content[m.start():headings[i + 1].start() if i + 1 < len(headings) else len(content)]
                for i, m in enumerate(headings)]

    def priority(section: str) -> int:
        title = section.splitlines()[0]
        if _ACCEPTANCE.search(title): return 0
        if _STORY.search(title): return 1
        if _NFR.search(title): return 2
        return 3

    room = max(0, limit - len(prefix) - len(note) - 70)
    chosen: dict[int, str] = {}
    for i in sorted(range(len(sections)), key=lambda i: (priority(sections[i]), i)):
        section = sections[i]
        if len(section) <= room:
            chosen[i] = section
            room -= len(section)
        elif priority(section) < 3 and not chosen:
            chosen[i] = cut_middle(section, room, note=note)
            room = 0
    if not chosen:
        first = min(range(len(sections)), key=lambda i: (priority(sections[i]), i))
        chosen[first] = cut_middle(sections[first], room, note=note)
    omitted = [sections[i].splitlines()[0].removeprefix("## ") for i in range(len(sections)) if i not in chosen]
    marker = f"\n… (bỏ {len(omitted)} mục; {note}: {', '.join(omitted)}) …" if omitted else ""
    selected = prefix + "".join(chosen[i] for i in sorted(chosen))
    return selected + marker[:max(0, limit - len(selected))]
