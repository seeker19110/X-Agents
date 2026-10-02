---
name: ecc-agent-harness-construction
description: Design and optimize AI agent action spaces, tool definitions, and observation formatting for higher completion rates. Use when defining or revising an agent's tool set, action space, or observation format.
metadata:
  origin: ECC
---

<!-- Sinh bởi scripts/ecc_vendor.py từ affaan-m/ECC@c70874fae9eb0e5ad0365beb7e2955899fd1d30f (skills/agent-harness-construction/SKILL.md) — không sửa tay; đổi thì sửa docs/integrations/ecc.lock.json rồi chạy lại (ADR-0028). -->
> **ECC (MIT), vendor vào X-Agents.** Luật ở `AGENTS.md` thắng khi trùng: coverage `fail_under = 100` (không phải 80%), test đỏ trước khi code, nhánh → PR theo `docs/QUY-TRINH-GIT.md`, không xoá code ngoài yêu cầu. Mục ECC được nhắc tới mà không có tệp `ecc-<tên>` trong `.claude/` thì repo không vendor — dùng `/gate`, `/debug`, `/adr`, `/thi-hanh` hoặc bỏ qua.

# Agent Harness Construction

Use this skill when you are improving how an agent plans, calls tools, recovers from errors, and converges on completion.

## Core Model

Agent output quality is constrained by:
1. Action space quality
2. Observation quality
3. Recovery quality
4. Context budget quality

## Action Space Design

1. Use stable, explicit tool names.
2. Keep inputs schema-first and narrow.
3. Return deterministic output shapes.
4. Avoid catch-all tools unless isolation is impossible.

## Granularity Rules

- Use micro-tools for high-risk operations (deploy, migration, permissions).
- Use medium tools for common edit/read/search loops.
- Use macro-tools only when round-trip overhead is the dominant cost.

## Observation Design

Every tool response should include:
- `status`: success|warning|error
- `summary`: one-line result
- `next_actions`: actionable follow-ups
- `artifacts`: file paths / IDs

## Error Recovery Contract

For every error path, include:
- root cause hint
- safe retry instruction
- explicit stop condition

## Context Budgeting

1. Keep system prompt minimal and invariant.
2. Move large guidance into skills loaded on demand.
3. Prefer references to files over inlining long documents.
4. Compact at phase boundaries, not arbitrary token thresholds.

## Architecture Pattern Guidance

- ReAct: best for exploratory tasks with uncertain path.
- Function-calling: best for structured deterministic flows.
- Hybrid (recommended): ReAct planning + typed tool execution.

## Benchmarking

Track:
- completion rate
- retries per task
- pass@1 and pass@3
- cost per successful task

## Anti-Patterns

- Too many tools with overlapping semantics.
- Opaque tool output with no recovery hints.
- Error-only output without next steps.
- Context overloading with irrelevant references.
