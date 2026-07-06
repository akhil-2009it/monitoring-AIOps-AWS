#!/usr/bin/env bash
# Smoke test for the AIOps Anomaly Scoring API.
#
#   bash scripts/smoke_test.sh --env dev
#   bash scripts/smoke_test.sh --host https://aiops.example.com --token "$JWT"

set -euo pipefail

ENV=""; HOST=""; TOKEN="${MLOPS_TOKEN:-}"; LATENCY_LIMIT_MS=500
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV="$2"; shift 2;;
    --host) HOST="$2"; shift 2;;
    --token) TOKEN="$2"; shift 2;;
    --latency-limit-ms) LATENCY_LIMIT_MS="$2"; shift 2;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

if [[ -z "$HOST" && -n "$ENV" ]]; then
  HOST="https://aiops-${ENV}.monitoring-mlops.example.com"
fi
[[ -n "$HOST" ]] || { echo "Pass --host or --env." >&2; exit 2; }

AUTH_HEADER=()
[[ -n "$TOKEN" ]] && AUTH_HEADER=(-H "Authorization: Bearer $TOKEN")

echo "Smoke test: $HOST"
PASS=0; FAIL=0
check() {
  local label="$1"; shift
  local started=$(python3 -c 'import time;print(time.time())')
  if "$@"; then
    local elapsed_ms=$(python3 -c "import time; print(int((time.time()-$started)*1000))")
    if (( elapsed_ms > LATENCY_LIMIT_MS )); then
      echo "  ⚠ $label took ${elapsed_ms}ms"
    else
      echo "  ✓ $label (${elapsed_ms}ms)"
    fi
    PASS=$((PASS+1))
  else
    echo "  ✗ $label"; FAIL=$((FAIL+1))
  fi
}

check "GET /health" curl -fsS -o /dev/null "${AUTH_HEADER[@]}" "$HOST/health"

PAYLOAD='{"ts":"2026-06-19T10:00:00Z","source":"alb","host":"alb-1","status":500,"latency_ms":420,"src_ip":"203.0.113.1","path":"/api/v1/users","attrs":{}}'
check "POST /score (status=500)" \
  curl -fsS -o /dev/null -X POST -H "Content-Type: application/json" "${AUTH_HEADER[@]}" \
  --data "$PAYLOAD" "$HOST/score"

check "GET /alerts" curl -fsS -o /dev/null "${AUTH_HEADER[@]}" "$HOST/alerts?limit=10"

check "GET /sources" curl -fsS -o /dev/null "${AUTH_HEADER[@]}" "$HOST/sources"

echo
echo "Passed: $PASS    Failed: $FAIL"
[[ "$FAIL" == 0 ]] || exit 1
