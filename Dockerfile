# Stage 1: Build React dashboard
FROM node:20-alpine AS frontend
WORKDIR /app/dashboard_ui
COPY dashboard_ui/package*.json ./
RUN npm ci --silent
COPY dashboard_ui/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.13-slim AS runtime

# uv: provides reproducible, locked dependency installs
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies into the system environment so `python main.py`
# works without activating a venv.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

# Dependency layer — cached unless pyproject.toml or uv.lock change.
# --no-install-project installs only third-party deps (the project source
# is not present yet).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy source
COPY config/ config/
COPY core/ core/
COPY data/ data/
COPY scanner/ scanner/
COPY sentiment/ sentiment/
COPY analysis/ analysis/
COPY broker/ broker/
COPY telegram_bot/ telegram_bot/
COPY dashboard/ dashboard/
COPY db/ db/
COPY stats/ stats/
COPY news/ news/
COPY main.py ./

# Install the project itself now that the source is present.
# --no-editable installs it as a real copied package (correct for an
# immutable image).
RUN uv sync --frozen --no-editable

# Copy built React frontend from stage 1
COPY --from=frontend /app/dashboard/static/ dashboard/static/

EXPOSE 8000

CMD ["python", "main.py"]
