FROM python:3.11-slim

# Install curl (needed for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps for analysis
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Agent source code
WORKDIR /app
COPY src/ /app/src/
COPY SKILL.md /app/SKILL.md

# Environment defaults (override via K8s secrets)
ENV HERMES_PROVIDER=openrouter
ENV HERMES_MODEL=openrouter/owl-alpha
ENV API_HOST=0.0.0.0
ENV API_PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:${API_PORT}/health || exit 1

EXPOSE 8000

# Run with stderr redirected to stdout for better logging
CMD ["sh", "-c", "python -u /app/src/main.py 2>&1"]
