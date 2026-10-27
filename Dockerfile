FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS python-builder
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
RUN uv sync --frozen --extra sync --no-dev

FROM python:3.12-slim-bookworm
ARG VERSION=0.0.7
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="Sillage" \
      org.opencontainers.image.description="A focused, self-hosted subtitle translation studio" \
      org.opencontainers.image.source="https://github.com/lucas-lepajollec/sillage" \
      org.opencontainers.image.url="https://github.com/lucas-lepajollec/sillage" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$VCS_REF
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg mkvtoolnix tini gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 sillage && useradd -u 1000 -g sillage -m sillage
WORKDIR /app
COPY --from=python-builder /app/.venv /app/.venv
COPY --from=python-builder /app/backend /app/backend
COPY --from=frontend /build/dist /app/frontend/dist
COPY scripts/entrypoint.sh /usr/local/bin/sillage-entrypoint
COPY LICENSE THIRD_PARTY_NOTICES.md /app/licenses/
ENV PATH="/app/.venv/bin:$PATH" CONFIG_DIR=/config MEDIA_ROOTS=/media PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 2511
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:2511/api/health', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/sillage-entrypoint"]
CMD ["uvicorn", "sillage.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "2511", "--no-access-log"]
