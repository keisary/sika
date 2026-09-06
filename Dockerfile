FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY . .

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

EXPOSE 8000

# Migrations + seed (idempotent) + API
CMD alembic upgrade head && (python -m app.seed || true) && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
