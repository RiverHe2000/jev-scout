# Optional Linux-only recipe: run with --network host to preserve localhost.
# Ordinary -p port mapping cannot reach a server bound to container loopback.
FROM node:24-bookworm-slim AS frontend
WORKDIR /web
RUN npm install --global pnpm@11.19.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JEV_SCOUT_HOST=127.0.0.1 \
    JEV_SCOUT_PORT=8765 \
    JEV_SCOUT_DATA_DIR=/app/runtime
WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY data/ ./data/
COPY artifacts/evaluation/report.json ./artifacts/evaluation/report.json
COPY --from=frontend /web/dist/ ./frontend/dist/
RUN python -m pip install --no-cache-dir --no-deps --editable . \
    && groupadd --gid 10001 scout \
    && useradd --uid 10001 --gid scout --no-create-home scout \
    && mkdir -p /app/runtime \
    && chown -R scout:scout /app/runtime
USER scout
VOLUME ["/app/runtime"]
HEALTHCHECK --interval=20s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2)"]
CMD ["jev-scout", "serve"]
