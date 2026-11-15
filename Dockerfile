# syntax=docker/dockerfile:1

FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS frontend-build
WORKDIR /workspace/stitch_aesthetic_markdown_reader

COPY stitch_aesthetic_markdown_reader/package.json ./
COPY stitch_aesthetic_markdown_reader/package-lock.json ./
RUN npm ci

COPY stitch_aesthetic_markdown_reader/ ./
RUN npm run build

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS runtime
ARG APP_REVISION=local

LABEL org.opencontainers.image.title="FODS Research Agent" \
      org.opencontainers.image.description="Research-to-brief application with React frontend" \
      org.opencontainers.image.revision="${APP_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    RLA_DATA_DIR=/app/data

WORKDIR /app

COPY requirements-docker.lock ./requirements-docker.lock
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    -r requirements-docker.lock

COPY --chown=10001:10001 src/ ./src/
COPY --chown=10001:10001 --from=frontend-build \
    /workspace/src/fods/web/dist/ ./src/fods/web/dist/

RUN adduser --disabled-password --gecos "" --uid 10001 app \
    && mkdir -p /app/data \
    && chown -R app:app /app/data

USER app
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)" || exit 1

CMD ["python", "-m", "fods.cli", "serve", "--host", "0.0.0.0", "--port", "8765"]
