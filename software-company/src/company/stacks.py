"""Nhận diện stack của repo khách và lệnh lint/test tương ứng (ADR-0013).

`run_checks` trước đây cứng `ruff` + `pytest`, nên PR của frontend, mobile, platform và data mang
`local_checks.lint/tests` do một lệnh không liên quan đến code của họ sinh ra: bằng chứng hình thức, không có giá trị.
Ở đây mỗi stack tự khai dấu hiệu nhận biết và argv của lint/test; argv do CODE ghép, model chỉ chọn tên lệnh,
nên ranh giới tin cậy của ADR-0010 không đổi. Không nhận ra stack nào → `local_checks` nói thẳng là không chạy được,
thay vì báo pass giả."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Stack:
    name: str
    lint: list[str] | None
    test: list[str] | None

    def commands(self) -> dict[str, list[str]]:
        return {k: v for k, v in (("lint", self.lint), ("test", self.test)) if v}


PY = Stack("python", [sys.executable, "-m", "ruff", "check"], [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
NODE = Stack("node", ["npm", "run", "--if-present", "lint"], ["npm", "test", "--if-present"])
GO = Stack("go", ["go", "vet", "./..."], ["go", "test", "./..."])
RUST = Stack("rust", ["cargo", "clippy", "--quiet"], ["cargo", "test", "--quiet"])
GRADLE = Stack("gradle", ["./gradlew", "lint"], ["./gradlew", "test"])
MAVEN = Stack("maven", ["mvn", "-q", "checkstyle:check"], ["mvn", "-q", "test"])
UNKNOWN = Stack("unknown", None, None)

# Thứ tự có ý nghĩa: file dấu hiệu đầu tiên khớp thì thắng (repo đa ngôn ngữ lấy stack của gốc repo).
MARKERS: tuple[tuple[str, Stack], ...] = (
    ("pyproject.toml", PY), ("setup.cfg", PY), ("requirements.txt", PY),
    ("package.json", NODE), ("go.mod", GO), ("Cargo.toml", RUST),
    ("build.gradle", GRADLE), ("build.gradle.kts", GRADLE), ("pom.xml", MAVEN),
)


def detect(root: Path) -> Stack:
    """Stack của một worktree theo file dấu hiệu ở gốc. Node có script lint/test hay không thì `--if-present` lo."""
    for marker, stack in MARKERS:
        if (root / marker).exists():
            if stack is NODE:
                return _node_stack(root / marker)
            return stack
    return UNKNOWN


def _node_stack(pkg: Path) -> Stack:
    """Chỉ khai lệnh khi package.json thật sự có script tương ứng — tránh `npm test` mặc định thoát lỗi."""
    try:
        scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}
    except (OSError, json.JSONDecodeError):
        scripts = {}
    return Stack("node", ["npm", "run", "lint"] if "lint" in scripts else None,
                 ["npm", "test", "--", "--watch=false"] if "test" in scripts else None)
