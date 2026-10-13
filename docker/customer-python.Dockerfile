# ADR gốc 0010/S2: lệnh uv của khách chạy trong image riêng, không dùng venv của orchestrator.
FROM ghcr.io/astral-sh/uv:0.9.9@sha256:f6e3549ed287fee0ddde2460a2a74a2d74366f84b04aaa34c1f19fec40da8652 AS uv
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/tmp/uv-cache UV_PROJECT_ENVIRONMENT=/tmp/xagents-venv
WORKDIR /w
