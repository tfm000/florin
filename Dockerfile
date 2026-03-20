# Stage 1: Build React dashboard
FROM node:20-alpine AS frontend
WORKDIR /app/dashboard_ui
COPY dashboard_ui/package*.json ./
RUN npm ci --silent
COPY dashboard_ui/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime
WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e "." && \
    rm -rf /root/.cache/pip

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
COPY main.py ./
COPY .env.example ./

# Copy built React frontend from stage 1
COPY --from=frontend /app/dashboard/static/ dashboard/static/

EXPOSE 8000

CMD ["python", "main.py"]
