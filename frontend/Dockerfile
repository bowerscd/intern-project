# Stage 1: Compile TypeScript → static/dist/
FROM node:22-slim AS ts-builder
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY tsconfig.json ./
COPY src/ts/ src/ts/
RUN npx tsc -p tsconfig.json

# Stage 2: Python application
FROM python:3.14-slim

WORKDIR /app

# Create non-root user
RUN groupadd --system appgroup && useradd --system --gid appgroup appuser

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Overwrite static/dist/ with freshly compiled output (the local copy
# is gitignored and may be stale or absent).
COPY --from=ts-builder /build/static/dist/ static/dist/

# Switch to non-root user
USER appuser

EXPOSE 5000

CMD ["gunicorn", "app:app", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "60", \
     "--access-logfile", "-"]
