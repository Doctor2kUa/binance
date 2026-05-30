# ═══ Stage 1: Hermes CLI ════════════════════════════════════════════
FROM node:20-slim AS hermes

# Install Hermes Agent CLI
RUN npm install -g hermes-agent --unsafe-perm 2>&1

# ═══ Stage 2: Python + Hermes ════════════════════════════════════════
FROM python:3.11-slim

# Install curl (needed for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Hermes CLI from builder
COPY --from=hermes /usr/local/bin/hermes /usr/local/bin/hermes
COPY --from=hermes /usr/local/bin/hermes-agent /usr/local/bin/hermes-agent
COPY --from=hermes /usr/local/lib/node_modules /usr/local/lib/node_modules

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
