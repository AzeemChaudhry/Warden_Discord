# Tracks the latest uv so it can always read uv.lock.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY warden ./warden
RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 1000 warden \
    && mkdir /data && chown warden /data
USER warden

ENV PATH="/app/.venv/bin:$PATH" \
    DATABASE_PATH=/data/warden.db
VOLUME ["/data"]

CMD ["python", "-m", "warden"]
