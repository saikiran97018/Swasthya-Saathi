# One image for the whole product: the web app (React) is built first, then served by the API (FastAPI) itself.
# Build:  docker build -t swasthya-saathi .       Run:  docker run -p 10000:10000 --env-file backend/.env swasthya-saathi

# ---- 1. build the web app ------------------------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. the API, with the built web app next to it -----------------------------------------------------
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/static
ENV STATIC_DIR=/app/static

# A non-root user: the app only needs to read its own files and talk to the network.
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 10000
# Render gives the port in $PORT. Migrations run on every start (a no-op when the database is current).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
