#!/usr/bin/env bash
# fork-verify-fleet.sh — post-update / daily smoke verification of the homelab
# Hermes fleet. Companion to FORK_UPDATE_RUNBOOK.md (§6) and fork-auto-update.sh.
#
# Checks (run from the MBP; mini is 10.88.1.208):
#   gateway :8642/health, loopback dashboards :9119/:9121/:9122 (via ssh),
#   metrics dashboard :8899 API surface — overview (about/usage-map/recent/
#   session-names), benchmark (marks/best/samples), events (hitl-events),
#   findings, env-mode — plus data-freshness (requests.jsonl advancing,
#   hitl-v1 documents present).
#
# Exit 0 = all pass, 1 = one or more failures. Prints PASS/FAIL/WARN per check.

set -uo pipefail

MINI_SSH="${MINI_SSH:-christianpompa@10.88.1.208}"
# metricsdash binds loopback since 2026-08-15 (tailnet-only exposure via
# `tailscale serve`); reach it over the tailnet, not the LAN IP.
MINI_HTTP="${MINI_HTTP:-http://christians-mini.tailf1af7f.ts.net}"
GATEWAY_HTTP="${GATEWAY_HTTP:-http://hermes-serv.cpompa.com:8642}"
FAILS=0

pass() { echo "PASS  $1"; }
warn() { echo "WARN  $1"; }
fail() { echo "FAIL  $1"; FAILS=$((FAILS+1)); }

# $1=name $2=url — expect HTTP 200 and no top-level "error" key in JSON body
check_http() {
  local code body
  code=$(curl -s -m8 -o /tmp/fvf-body.$$ -w "%{http_code}" "$2" 2>/dev/null)
  body=$(head -c 300 /tmp/fvf-body.$$ 2>/dev/null); rm -f /tmp/fvf-body.$$
  if [ "$code" != "200" ]; then fail "$1 -> HTTP $code ($2)"; return; fi
  case "$body" in
    *'"error"'*) fail "$1 -> error payload: ${body:0:120}" ;;
    *) pass "$1" ;;
  esac
}

echo "== fleet verify $(date '+%Y-%m-%d %H:%M:%S') =="

# Gateway (LAN endpoint)
check_http "gateway :8642/health" "$GATEWAY_HTTP/health"

# Loopback dashboards on the mini (need ssh)
for p in 9119 9121 9122; do
  code=$(ssh -o BatchMode=yes -o ConnectTimeout=6 "$MINI_SSH" \
    "curl -s -m6 -o/dev/null -w '%{http_code}' http://127.0.0.1:$p/" 2>/dev/null)
  [ "$code" = "200" ] && pass "dashboard :$p" || fail "dashboard :$p -> HTTP $code"
done

# Metrics dashboard :8899 — feature surfaces
check_http "metrics /health"                "$MINI_HTTP:8899/health"
check_http "overview /api/about"            "$MINI_HTTP:8899/api/about"
check_http "overview /api/usage-map"        "$MINI_HTTP:8899/api/usage-map"
check_http "overview /api/session-names"    "$MINI_HTTP:8899/api/session-names"
check_http "overview /api/recent"           "$MINI_HTTP:8899/api/recent"
check_http "benchmark /api/benchmark/marks"  "$MINI_HTTP:8899/api/benchmark/marks"
check_http "benchmark /api/benchmark/best"   "$MINI_HTTP:8899/api/benchmark/best"
check_http "benchmark /api/benchmark/samples" "$MINI_HTTP:8899/api/benchmark/samples"
check_http "events /api/hitl-events"        "$MINI_HTTP:8899/api/hitl-events?since_h=720&limit=50"
check_http "findings /api/findings"         "$MINI_HTTP:8899/api/findings"
check_http "env-mode /api/env-mode"         "$MINI_HTTP:8899/api/env-mode"

# Data freshness on the mini
fresh=$(ssh -o BatchMode=yes -o ConnectTimeout=6 "$MINI_SSH" '
  now=$(date +%s)
  f=~/.hermes/metrics/requests.jsonl
  if [ -f "$f" ]; then m=$(stat -f %m "$f"); echo $((now - m)); else echo -1; fi' 2>/dev/null)
if [ "$fresh" = "-1" ] || [ -z "$fresh" ]; then warn "requests.jsonl missing on mini"
elif [ "$fresh" -gt 86400 ]; then warn "requests.jsonl stale (${fresh}s > 24h) — compression/memory pipelines may be idle"
else pass "requests.jsonl advancing (${fresh}s old)"; fi

# hitl-v1 historical data present (db was found wiped twice 2026-07-27/28)
docs=$(ssh -o BatchMode=yes -o ConnectTimeout=6 "$MINI_SSH" \
  'sqlite3 /Volumes/SSD_2/XCode_Repos/myprojects/hitl-v1/data/hitl.db "SELECT count(*) FROM documents;" 2>/dev/null' )
case "$docs" in
  ""|*Error*) warn "hitl-v1 documents count unreadable" ;;
  0) fail "hitl-v1 hitl.db documents = 0 (db wiped? backups in data/)" ;;
  *) pass "hitl-v1 documents = $docs" ;;
esac

echo "== $FAILS failure(s) =="
exit $([ "$FAILS" -eq 0 ] && echo 0 || echo 1)
