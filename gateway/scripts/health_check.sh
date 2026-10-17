#!/usr/bin/env bash
# Health check for the LiteLLM Proxy gateway (tasks.md 1.3).
# Usage: gateway/scripts/health_check.sh [base_url]
set -euo pipefail

BASE_URL="${1:-http://localhost:4000}"

status=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health/liveliness" || echo "000")

if [ "$status" = "200" ]; then
  echo "healthy: ${BASE_URL} (HTTP ${status})"
  exit 0
else
  echo "unhealthy: ${BASE_URL} (HTTP ${status})" >&2
  exit 1
fi
