#!/usr/bin/env bash
# fork-sync.sh — build a new fork snapshot of upstream hermes-agent with the
# homelab delta re-applied. Companion to FORK_UPDATE_RUNBOOK.md (§3–§4).
#
# Run on the Mac from anywhere; it operates on the fork checkout (default
# ~/.hermes/hermes-agent). It does NOT commit or push — it leaves a prepared
# worktree for review/testing, then you run the commit-tree + push manually
# (deliberate checkpoint: tests must pass first).
#
# Usage:
#   scripts/fork-sync.sh [TARGET] [BASE]
#     TARGET   upstream ref to snapshot (default: origin/main = HEAD)
#     BASE     upstream sha the CURRENT fork main was vendored from
#              (default: parsed from the last "vendor upstream <sha>" message)
set -euo pipefail

REPO="${HERMES_FORK_REPO:-$HOME/.hermes/hermes-agent}"
WT="${FORK_SYNC_WT:-/tmp/hermes-vendor}"
UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}" # upstream = GitHub (unified 2026-07-23)
FORK_REMOTE="${FORK_REMOTE:-origin}"           # origin = gitlab, our fork
TARGET="${1:-$UPSTREAM_REMOTE/main}"

# Additive delta files (ours only) — keep in sync with FORK_UPDATE_RUNBOOK.md §3.
ADDITIVE=(
  FORK_UPDATE_RUNBOOK.md FORK_CHANGELOG.md HERMES.md .gitlab-ci.yml
  skills/mlops/models/comfyui
  skills/creative/i2v-landscape-animation
  skills/creative/comfyui/scripts/i2v_landscape.py
  skills/creative/comfyui/workflows/animate_diff-i2v-landscape.md.json
  skills/creative/comfyui/workflows/animate_diff-i2v-landscape.meta.json
  skills/creative/comfyui/workflows/wanvideo-i2v-landscape.md.json
  skills/creative/comfyui/workflows/wanvideo-i2v-landscape.meta.json
  scripts/fork-sync.sh
)
# Upstream-owned files carrying our code patches (see FORK_CHANGELOG.md §"Core
# code patches"). Re-applied by 3-way apply; conflicts resolve upstream-first.
PATCH_FILES=(
  gateway/run.py
  agent/moa_loop.py agent/moa_trace.py run_agent.py
  hermes_cli/web_server.py tui_gateway/slash_worker.py
  agent/agent_runtime_helpers.py agent/conversation_loop.py
  tests/run_agent/test_message_sequence_repair.py
  hermes_cli/main.py
  apps/desktop/electron/main.ts apps/desktop/electron/preload.ts
  apps/desktop/src/store/session.ts apps/desktop/src/global.d.ts
  apps/desktop/src/contrib/runtime-loader.ts
  apps/desktop/src/app/settings/plugins-settings.tsx
)

cd "$REPO"
echo "== remotes =="; git remote -v | grep -E "^($UPSTREAM_REMOTE|$FORK_REMOTE)\b"
git fetch "$UPSTREAM_REMOTE" --tags --prune --quiet
git fetch "$FORK_REMOTE" --quiet

BASE="${2:-}"
if [ -z "$BASE" ]; then
  BASE=$(git log -1 --format=%B "$FORK_REMOTE/main" \
    | grep -oE 'vendor upstream ([0-9a-f]{40})' | grep -oE '[0-9a-f]{40}' || true)
fi
[ -n "$BASE" ] || { echo "ERROR: cannot determine BASE — pass it as arg 2"; exit 1; }
NEW=$(git rev-parse "$TARGET")
[ "$NEW" != "$BASE" ] || { echo "Fork main is already at $TARGET — nothing to do."; exit 0; }

echo "== upstream delta =="
echo "BASE=$BASE"; echo "NEW=$NEW"
git rev-list --count "$BASE..$NEW" | xargs echo "new upstream commits:"
git log --oneline -15 "$BASE..$NEW"

echo "== collision check (additive files vs NEW upstream) =="
COLLIDE=0
for f in "${ADDITIVE[@]}"; do
  if git cat-file -e "$NEW:$f" 2>/dev/null; then echo "COLLISION: $f"; COLLIDE=1; fi
done
[ "$COLLIDE" -eq 0 ] || { echo "Resolve collisions before proceeding (runbook §4 step 2)."; exit 1; }
echo "no collisions"

echo "== build worktree at NEW =="
case "$WT" in /tmp/*|"$TMPDIR"*) ;; *) echo "ERROR: WT must be under /tmp"; exit 1;; esac
rm -rf "$WT"
git worktree add --detach "$WT" "$NEW" >/dev/null
for f in "${ADDITIVE[@]}"; do
  if git cat-file -e "$FORK_REMOTE/main:$f" 2>/dev/null; then
    git -C "$WT" checkout "$FORK_REMOTE/main" -- "$f"
  else
    echo "WARN: $f not in $FORK_REMOTE/main — skipping (new file? add it to the worktree manually)"
  fi
done

echo "== re-apply code patches (3-way) =="
PATCH=$(mktemp /tmp/fork-delta.XXXXXX.patch)
git diff "$BASE" "$FORK_REMOTE/main" -- "${PATCH_FILES[@]}" > "$PATCH"
if [ -s "$PATCH" ]; then
  if ! git -C "$WT" apply --3way "$PATCH"; then
    echo "PATCH CONFLICTS — resolve in $WT (upstream's version wins, port our"
    echo "hunks around it per FORK_CHANGELOG.md), then: git -C $WT add -A"
    echo "and continue with the test + commit-tree steps in runbook §4 step 5."
    exit 2
  fi
else
  echo "(no code-patch diff — delta is additive-only)"
fi

echo
echo "Worktree ready: $WT"
git -C "$WT" status -s | head -30
echo
echo "Next: review, then in $WT run tests (runbook §4), then commit-tree + push:"
echo "  TREE=\$(git -C $WT write-tree)"
echo "  COMMIT=\$(git -C $WT commit-tree \"\$TREE\" -p $FORK_REMOTE/main -m \"feat: vendor upstream \$NEW, re-apply homelab delta\")"
echo "  git -C $WT diff --stat \"\$COMMIT\" $NEW   # must list ONLY delta files"
echo "  git -C $WT push $FORK_REMOTE \"\$COMMIT:main\""
