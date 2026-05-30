#!/bin/bash
# Debug script - run main.py with full output
cd /app
echo "=== DEBUG START ==="
echo "Python version: $(python --version)"
echo "Files: $(ls -la /app/src/)"
echo "Env API_PORT: $API_PORT"
echo "=== RUNNING MAIN.PY ==="
python -u /app/src/main.py 2>&1
echo "=== EXIT CODE: $? ==="
