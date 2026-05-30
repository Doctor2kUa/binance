FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Hermes Agent CLI via npm
RUN npm install -g hermes-agent

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

EXPOSE ${API_PORT}

CMD ["python", "/app/src/main.py"]
