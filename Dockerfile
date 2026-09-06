# --- Construction multi-stage : frontend (node) puis backend (python) ---
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY . .
COPY --from=frontend /fe/dist ./frontend/dist

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

EXPOSE 8000

# Migrations + seed (idempotent) + API (frontend servi par FastAPI)
CMD alembic upgrade head && (python -m app.seed || true) && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
