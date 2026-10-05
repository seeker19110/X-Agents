# Container hoá hub (console + orchestrator) — ADR-0013. Không đóng gói sản phẩm khách: repo khách mount
# từ ngoài (xem docker-compose.yml). docker-cli ở đây chỉ là CLIENT — orchestrator gọi `docker compose` cho
# khách qua socket passthrough (/var/run/docker.sock mount từ host), không có dockerd trong image này
# (ADR-0039 quyết định 7: nhốt daemon-client vào container là vô nghĩa, nó gọi ra quyền cao nhất của host).
FROM python:3.13-slim

# git: orchestrator tạo/merge worktree cho ticket khách (workspace.py). gh: mở PR thật lên repo khách
# (github_pr.py). docker-cli (không có dockerd): gọi `docker compose` cho khách (deploy.py, ADR-0039).
# curl: cài gh CLI qua repo chính thức của GitHub.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates gnupg \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy manifest trước để tận dụng cache layer khi chỉ sửa code, không sửa dependency.
COPY pyproject.toml uv.lock ./
COPY platform/console/pyproject.toml platform/console/pyproject.toml
COPY platform/gateway/pyproject.toml platform/gateway/pyproject.toml
COPY platform/xagents-core/pyproject.toml platform/xagents-core/pyproject.toml
COPY companies/keeper/pyproject.toml companies/keeper/pyproject.toml
COPY companies/software-company/pyproject.toml companies/software-company/pyproject.toml

COPY . .

# --locked: dùng đúng uv.lock đã commit, không tự nâng version lúc build (khớp CI, ADR-0011 workspace).
RUN uv sync --locked

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8200

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
