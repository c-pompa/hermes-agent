#!/usr/bin/env bash
# fork-auto-update.sh — daily "prepare + notify" upstream sync for the
# cpompa/hermes-agent fork. Companion to FORK_UPDATE_RUNBOOK.md.
#
# Checks upstream (GitHub NousResearch) for new commits since the last
# vendored snapshot. If there are any, it builds a candidate snapshot in
# /tmp/hermes-vendor via scripts/fork-sync.sh (additive delta overlay +
# 3-way patch re-apply) and runs the targeted test set. It NEVER commits,
# pushes, or deploys — a human/agent reviews the worktree and finishes
# runbook §4 step 5 onward.
#
# Status is written to ~/.hermes/fork-update-status.json and a macOS
# notification is shown when action is needed. Quiet when up to date.
#
# Scheduled via ~/Library/LaunchAgents/com.cpompa.hermes-fork-sync.plist
# (daily, off-peak). Logs to ~/.hermes/logs/fork-auto-update.log.

set -uo pipefail

REPO="${HERMES_FORK_REPO:-$HOME/.hermes/hermes-agent}"
WT="${FORK_SYNC_WT:-/tmp/hermes-vendor}"
STATUS="$HOME/.hermes/fork-update-status.json"
LOG_DIR="$HOME/.hermes/logs"
LOG="$LOG_DIR/fork-auto-update.log"
UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
FORK_REMOTE="${FORK_REMOTE:-origin}"

mkdir -p "$LOG_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

notify() { # $1=subtitle $2=body
  osascript -e "display notification \"$2\" with title \"hermes-agent fork update\" subtitle \"$1\"" \
    >/dev/null 2>&1 || true
}

write_status() { # $1=state $2=extra-json-fields (may be empty)
  cat > "$STATUS" <<EOF
{
  "checked_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "state": "$1",
  "base": "${BASE:-}",
  "upstream": "${NEW:-}",
  "worktree": "$WT"${2:+,
$2}
}
EOF
}

cd "$REPO" || { log "ERROR: repo $REPO missing"; exit 1; }

log "== fork-auto-update start =="
git fetch "$UPSTREAM_REMOTE" --tags --prune --quiet || { log "ERROR: fetch $UPSTREAM_REMOTE failed"; write_status "error" '"detail": "upstream fetch failed"'; exit 1; }
git fetch "$FORK_REMOTE" --quiet || { log "ERROR: fetch $FORK_REMOTE failed"; write_status "error" '"detail": "origin fetch failed"'; exit 1; }

# BASE = upstream sha the current fork main was vendored from. The fork tip
# is often a patch commit, so scan recent history for the vendor message.
BASE=$(git log -50 --format=%B "$FORK_REMOTE/main" \
  | grep -oE 'vendor upstream ([0-9a-f]{40})' | head -1 | grep -oE '[0-9a-f]{40}' || true)
if [ -z "$BASE" ]; then
  log "ERROR: cannot determine BASE from $FORK_REMOTE/main history"
  write_status "error" '"detail": "no vendor-upstream commit found in last 50"'
  notify "error" "cannot determine BASE — manual runbook §4 needed"
  exit 1
fi
NEW=$(git rev-parse "$UPSTREAM_REMOTE/main")

if [ "$NEW" = "$BASE" ]; then
  log "up to date (BASE=$BASE)"
  write_status "up-to-date"
  exit 0
fi

COUNT=$(git rev-list --count "$BASE..$NEW")
log "$COUNT new upstream commits ($BASE..$NEW)"

# Don't clobber a worktree that's still pending human review.
if [ -d "$WT" ]; then
  log "SKIP: $WT already exists (pending review?) — leaving it alone"
  write_status "pending-review-exists" "\"new_commits\": $COUNT"
  exit 0
fi

rm -f /tmp/fork-delta.*.patch 2>/dev/null || true

"$REPO/scripts/fork-sync.sh" "$UPSTREAM_REMOTE/main" "$BASE" >> "$LOG" 2>&1
rc=$?

if [ $rc -eq 2 ]; then
  CONFLICTS=$(git -C "$WT" diff --name-only --diff-filter=U 2>/dev/null | tr '\n' ' ')
  log "PATCH CONFLICTS: $CONFLICTS"
  write_status "needs-manual-resolution" "\"new_commits\": $COUNT,
  \"conflicts\": \"$CONFLICTS\""
  notify "conflicts — manual resolution" "$COUNT new upstream commits; conflicts in: $CONFLICTS"
  exit 0
elif [ $rc -ne 0 ]; then
  log "ERROR: fork-sync.sh exited $rc (see log above)"
  write_status "error" "\"new_commits\": $COUNT,
  \"detail\": \"fork-sync.sh exit $rc\""
  notify "sync error" "fork-sync.sh failed (exit $rc) — see fork-auto-update.log"
  exit 0
fi

# Clean apply — run the targeted test set in a worktree venv.
UV="$HOME/.local/bin/uv"; [ -x "$UV" ] || UV=uv
log "building worktree venv + targeted tests"
TESTS=(
  tests/run_agent/test_message_sequence_repair.py
  tests/agent/test_tool_guardrails.py
  tests/tools/test_session_search.py
)
EXISTING=()
for t in "${TESTS[@]}"; do [ -f "$WT/$t" ] && EXISTING+=("$t"); done

if "$UV" venv "$WT/.venv" >> "$LOG" 2>&1 \
  && "$UV" pip install -e ".[all,dev]" --python "$WT/.venv/bin/python" >> "$LOG" 2>&1; then
  ( cd "$WT" && ./.venv/bin/python -m pytest "${EXISTING[@]}" -q ) >> "$LOG" 2>&1
  trc=$?
else
  trc=99
  log "ERROR: worktree venv build failed"
fi

if [ $trc -eq 0 ]; then
  log "READY: snapshot of $NEW + delta applies clean, targeted tests pass"
  write_status "ready-for-review" "\"new_commits\": $COUNT"
  notify "ready for review" "$COUNT new upstream commits vendored clean in $WT — tests pass. Finish runbook §4 step 5."
else
  log "TESTS FAILED (exit $trc) in $WT"
  write_status "tests-failed" "\"new_commits\": $COUNT,
  \"pytest_exit\": $trc"
  notify "tests failed" "snapshot builds but targeted pytest failed — see fork-auto-update.log"
fi
exit 0
