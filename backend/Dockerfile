FROM python:3.14-slim

LABEL org.opencontainers.image.title="vibe-coded-backend" \
      org.opencontainers.image.description="Backend API for vibe-coded" \
      org.opencontainers.image.source="https://github.com/bowerscd/intern-project"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Create non-root user and writable data directory
RUN groupadd --system appgroup && useradd --system --gid appgroup appuser \
 && mkdir -p /data && chown appuser:appgroup /data

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Switch to non-root user
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

# Run migrations on every start (idempotent), then hand PID 1 to uvicorn.
# In production, set FORWARDED_ALLOW_IPS to the actual proxy IPs.
CMD alembic upgrade head && exec uvicorn app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
