# ADR gốc 0010/S2: lệnh uv của khách chạy trong image riêng, không dùng venv của orchestrator.
FROM ghcr.io/astral-sh/uv:0.9.9 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/tmp/uv-cache UV_PROJECT_ENVIRONMENT=/tmp/xagents-venv
WORKDIR /w
