FROM python:3.14-slim

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

# In production, set TRUSTED_PROXY_HOSTS to the actual proxy IPs
CMD uvicorn app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
