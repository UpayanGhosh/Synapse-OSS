FROM python:3.11-slim

LABEL maintainer="Upayan Ghosh <upayan1231@gmail.com>"
LABEL description="Synapse-OSS API Gateway"

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY workspace/ ./workspace/
# NOTE: Do NOT bake .env into the image. Use docker-compose env_file or -e flags at runtime.

EXPOSE 8000

WORKDIR /app/workspace

CMD ["python", "-m", "uvicorn", "sci_fi_dashboard.api_gateway:app", \
     "--host", "0.0.0.0", "--port", "8000"]
