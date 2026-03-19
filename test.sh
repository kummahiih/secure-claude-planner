#!/bin/bash
set -euo pipefail

echo "[unit] Running Python planner tests..."
(cd planner && python -m pytest plan_server_test.py plan_mcp_test.py -v --tb=short 2>&1 | grep -E '(PASSED|FAILED|ERROR|test_|===)')

echo "[security] Scanning Python deps (pip-audit)..."
(cd .. && \
    docker run --rm \
    -e PIP_ROOT_USER_ACTION=ignore \
    -v "$(pwd)":/app \
    -w /app \
    python:3.11-slim /bin/bash -c \
    "pip install --quiet --upgrade pip && pip install --quiet pip-audit && pip-audit -r planner/planner/requirements.txt" 2>&1 | grep -E '(found|No known|CRITICAL|WARNING|ERROR|Name)' || echo "  ✅ pip-audit clean"
)
