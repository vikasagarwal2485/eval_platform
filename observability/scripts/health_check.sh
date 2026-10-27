#!/usr/bin/env bash
# Health check for the observability stack's three services (tasks.md 1.1/1.3).
# Usage: observability/scripts/health_check.sh [collector_base_url] [tempo_base_url] [grafana_base_url]
set -euo pipefail

COLLECTOR_URL="${1:-http://localhost:13133}"
TEMPO_URL="${2:-http://localhost:3200}"
GRAFANA_URL="${3:-http://localhost:3000}"

check() {
  local name="$1" url="$2"
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" "$url" || echo "000")
  if [ "$status" = "200" ]; then
    echo "healthy: ${name} at ${url} (HTTP ${status})"
    return 0
  else
    echo "unhealthy: ${name} at ${url} (HTTP ${status})" >&2
    return 1
  fi
}

ok=0
check "otel-collector" "${COLLECTOR_URL}" || ok=1
check "tempo" "${TEMPO_URL}/ready" || ok=1
check "grafana" "${GRAFANA_URL}/api/health" || ok=1

exit "$ok"
