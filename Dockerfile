# Synapse production image
# Build:  docker build -t synapse:latest .
# Run:    docker run -p 8000:8000 -v synapse-data:/home/synapse/.synapse synapse:latest

FROM python:3.11-slim

# Runtime deps for FastAPI + sqlite-vec + curl for healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       curl \
       libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (synapse_config.py lives in workspace/, not the repo root)
COPY workspace ./workspace

# (Optional) checked-in profiles for first-run convenience.
# These are produced by sibling agents (issue 2.1 demo compose). The COPY is
# guarded by a wildcard so the build does not fail if profiles are absent;
# at least one *.json file is required in the repo root for the glob to match,
# so we touch a placeholder before COPY runs as a last resort.
COPY synapse*.json* ./
RUN [ -f synapse.demo.json ] || echo '{}' > synapse.demo.json \
    && [ -f synapse.local-only.json ] || echo '{}' > synapse.local-only.json

# Non-root user
RUN useradd --create-home --uid 10001 synapse \
    && chown -R synapse:synapse /app
USER synapse

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SYNAPSE_HOME=/home/synapse/.synapse \
    PYTHONPATH=/app/workspace

# uvicorn must run from /app/workspace because api_gateway.py imports
# `from sci_fi_dashboard import _deps` (no `workspace.` prefix). Same
# invocation as workspace/cli/install_home.py (the canonical CLI launcher).
WORKDIR /app/workspace

EXPOSE 8000

# /health is the canonical endpoint (see workspace/sci_fi_dashboard/routes/health.py).
# There is no /healthz route in this codebase.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "sci_fi_dashboard.api_gateway:app", \
     "--host", "0.0.0.0", "--port", "8000"]
