FROM python:3.11-slim

LABEL maintainer="Upayan Ghosh <upayan1231@gmail.com>"
LABEL description="Synapse-OSS API Gateway"

WORKDIR /app

# Install system build tools (required for sqlite-vec and other native extensions)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install browser binaries for the web browsing feature (crawl4ai uses Playwright)
# This step is optional — remove if you don't need /browse support or want a smaller image
RUN python -m playwright install chromium --with-deps 2>/dev/null || true

COPY workspace/ ./workspace/
# NOTE: Do NOT bake .env into the image. Use docker-compose env_file or -e flags at runtime.

# Create required directories for databases and logs
RUN mkdir -p /root/.openclaw/workspace/db /root/.openclaw/logs

EXPOSE 8000

WORKDIR /app/workspace

CMD ["python", "-m", "uvicorn", "sci_fi_dashboard.api_gateway:app", \
     "--host", "0.0.0.0", "--port", "8000"]
