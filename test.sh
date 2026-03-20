#!/bin/bash
set -euo pipefail

# Unit tests only — no network or Docker required.
# CVE scanning (pip-audit) runs in the parent repo's test-integration.sh.

echo "[unit] Running Python planner tests..."
(cd planner && python -m pytest plan_server_test.py plan_mcp_test.py -v --tb=short 2>&1 | grep -E '(PASSED|FAILED|ERROR|test_|===)')
