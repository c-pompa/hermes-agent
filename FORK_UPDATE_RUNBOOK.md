# Hermes Agent — Homelab Update Runbook

**Audience:** AI agents (and humans) updating the `cpompa/hermes-agent` fork to a
newer upstream release **while preserving our homelab customizations**, then
deploying to the gateway server (Mac mini) and client machines.

**Companion docs:** [`FORK_CHANGELOG.md`](FORK_CHANGELOG.md) (what our delta is)
and [`HERMES.md`](HERMES.md) (per-machine git rules). Read those first if you
haven't.

---

## 1. Mental model — read before touching anything

1. **This fork VENDORS upstream as squashed snapshots; it does NOT merge.**
   Each release is one commit whose *tree* = upstream's tree + our delta files,
   and whose *parent* = the previous fork `main`. The two histories are
   structurally divergent (`git status` reports "ahead N / behind M" at once).
   **Never `git pull` / `git merge` from the upstream remote** — it will conflict
   on thousands of files. Always build a fresh snapshot (Section 4).

2. **Remote names differ per machine — always `git remote -v` first.**

   | Machine | gitlab.cpompa.com (our fork) | GitHub NousResearch (upstream) |
   |---------|------------------------------|--------------------------------|
   | **Mac** (`~/.hermes/hermes-agent`) | `gitlab` | `origin` |
   | **mini** (`~/.hermes/hermes-agent`, gateway) | `origin` | `upstream` |

3. **The homelab delta is a small, fixed set of additive files** overlaid on
   every snapshot. Source of truth is whatever `git diff --name-only` reports
   between an upstream base and our fork `main` (Section 3). As of this writing
   it is **13 files** (12 skill/CI/doc files + this runbook).

4. **The mini CANNOT push/fetch gitlab over SSH.** Its credential lives in the
   macOS login keychain (`osxkeychain`), which is locked in non-interactive SSH
   sessions → git fails with `-25308` / "could not read Username". So all
   gitlab network ops happen **from the Mac** (its login keychain is unlocked),
   and code reaches the mini via a **Mac→mini SSH relay** (Section 5), never by
   the mini pulling gitlab.

---

## 2. Coordinates / environment

- **Mac checkout:** `~/.hermes/hermes-agent` — has working gitlab push creds.
  May be running `hermes --tui`; keep its working tree undisturbed (do snapshot
  builds in a throwaway `git worktree`).
- **mini (gateway server):** host `christianpompa@10.88.1.208`,
  checkout `/Users/christianpompa/.hermes/hermes-agent`.
  - Gateway: launchd label `ai.hermes.gateway`, OpenAI-compatible API on
    **`:8642`** (`/health` is open; `/v1/*` needs the api_server key).
  - Dashboard: launchd label `ai.hermes.dashboard`, **loopback** `:9119`
    (token-gated; reached from clients via SSH tunnel).
  - Install: **editable** (`pip install -e`), Python **3.11**, `uv` at
    `~/.local/bin/uv`, venv at `<repo>/venv` (no `pip` inside — use `uv`).
- **Rollback tags** live on gitlab as `backup/pre-update-YYYYMMDD`.

---

## 3. The homelab delta (what must survive every update)

Recompute the authoritative list any time with:

```bash
# on the Mac, BASE = the upstream commit the CURRENT fork main was snapshotted from
git -C ~/.hermes/hermes-agent diff --name-only <BASE> gitlab/main
```

Current set (all **additive** — none overwrite upstream files):

```
FORK_UPDATE_RUNBOOK.md                                         # this file
FORK_CHANGELOG.md
HERMES.md
.gitlab-ci.yml
skills/mlops/models/comfyui/                                   # whole dir (ours only)
skills/creative/i2v-landscape-animation/                       # whole dir (ours only)
skills/creative/comfyui/scripts/i2v_landscape.py              # 3 i2v files added to an
skills/creative/comfyui/workflows/animate_diff-i2v-landscape.md.json   #  upstream-owned skill
skills/creative/comfyui/workflows/wanvideo-i2v-landscape.md.json
```

**Dropped on purpose:** our old `agent/image_routing.py` magic-byte fix (now
native upstream). **Taken from upstream:** `skills/creative/comfyui`'s
`run_workflow.py` / `_common.py` / `SKILL.md` (I2V reconciliation against the
new upstream scripts is a tracked follow-up in `FORK_CHANGELOG.md`).

> ⚠️ Before each update, **collision-check** the delta against the *new*
> upstream (Section 4 step 2). If upstream starts shipping a path we also
> overlay, stop and reconcile — blindly overlaying would clobber upstream's
> version.

---

## 4. Build a new fork snapshot (on the Mac)

```bash
cd ~/.hermes/hermes-agent
git remote -v   # sanity: origin=GitHub, gitlab=gitlab

# 1. Fetch latest upstream and see what's new
git fetch origin --tags --prune
BASE=<upstream-base-of-current-fork-main>     # e.g. the 41c85fb94 from last time
NEW=$(git rev-parse origin/main)
git rev-list --count $BASE..origin/main       # how many new commits
git log --oneline $BASE..origin/main | head   # skim them

# 2. Compute delta + collision-check it against NEW upstream
git diff --name-only $BASE gitlab/main | tee /tmp/delta.txt
while read -r f; do [ -n "$f" ] && git cat-file -e "$NEW:$f" 2>/dev/null \
  && echo "COLLISION: $f"; done < /tmp/delta.txt   # expect NO output

# 3. Tag a rollback (current fork main) and push it
git tag -f backup/pre-update-$(date +%Y%m%d) gitlab/main
git push -f gitlab backup/pre-update-$(date +%Y%m%d)   # date computed by a human/shell, not the agent

# 4. Build the snapshot in a throwaway worktree at NEW upstream
WT=/tmp/hermes-vendor; rm -rf "$WT"
git worktree add --detach "$WT" "$NEW"
#   overlay our delta files from gitlab/main (list them explicitly; xargs is fiddly on BSD)
git -C "$WT" checkout gitlab/main -- \
  FORK_UPDATE_RUNBOOK.md FORK_CHANGELOG.md HERMES.md .gitlab-ci.yml \
  skills/mlops/models/comfyui skills/creative/i2v-landscape-animation \
  skills/creative/comfyui/scripts/i2v_landscape.py \
  skills/creative/comfyui/workflows/animate_diff-i2v-landscape.md.json \
  skills/creative/comfyui/workflows/wanvideo-i2v-landscape.md.json
git -C "$WT" status -s          # MUST be exactly our delta, all "A" (additions)

# 5. Commit with parent = current fork main (linear, clean fast-forward) and push
TREE=$(git -C "$WT" write-tree)
COMMIT=$(git -C "$WT" commit-tree "$TREE" -p gitlab/main -m \
  "feat: vendor upstream $NEW, re-apply homelab delta")
git -C "$WT" rev-parse "$COMMIT^"            # MUST equal current gitlab/main (FF check)
git -C "$WT" diff --stat "$COMMIT" "$NEW"    # MUST list ONLY our delta files
git -C "$WT" push gitlab "$COMMIT:main"      # fast-forward push
git worktree remove --force "$WT"
```

**Why `commit-tree` instead of `checkout`+`commit`:** it lets us set
*tree = new upstream* while *parent = old fork main* in one step, keeping the
fork's history linear so the push is always a clean fast-forward (no force on
`main`, no merge conflicts).

---

## 5. Deploy to the gateway server (the mini)

The mini can't pull gitlab over SSH, so **relay the commit from the Mac** to a
temporary branch, then reset `main` to it.

```bash
# --- from the Mac ---
COMMIT=<the snapshot sha you just pushed>
git push "ssh://christianpompa@10.88.1.208/Users/christianpompa/.hermes/hermes-agent" \
  "$COMMIT:refs/heads/incoming"

# --- on the mini ---
ssh christianpompa@10.88.1.208 'cd ~/.hermes/hermes-agent &&
  git status -s &&                                   # expect clean tree
  git merge-base --is-ancestor main incoming && echo "FF OK" &&
  git checkout -q main && git reset --hard incoming && git branch -D incoming'

# --- config drift check (do NOT auto-edit .env) ---
ssh christianpompa@10.88.1.208 'cd ~/.hermes/hermes-agent &&
  comm -13 <(grep -oE "^[A-Z][A-Z0-9_]+=" .env | sed "s/=.*/=/" | sort -u) \
           <(grep -oE "^#?[[:space:]]*[A-Z][A-Z0-9_]+=" .env.example | sed -E "s/^#?[[:space:]]*//;s/=.*/=/" | sort -u)'
#   ^ lists .env.example keys not set in live .env. New OPTIONAL provider keys
#     are expected and fine; report them, let the user opt in. Required keys
#     changing would be unusual — flag loudly if so.

# --- rebuild venv (editable; gateway keeps running on in-memory code) ---
ssh christianpompa@10.88.1.208 'cd ~/.hermes/hermes-agent &&
  ~/.local/bin/uv pip install -e ".[all]" --python venv/bin/python'
#   check the output for errors; "Installed/Uninstalled N packages" with no
#   error lines = good. (uv re-resolves; most deps are cached so it's fast.)

# --- restart services (brief downtime) ---
ssh christianpompa@10.88.1.208 'U=$(id -u);
  launchctl kickstart -k gui/$U/ai.hermes.gateway;
  launchctl kickstart -k gui/$U/ai.hermes.dashboard'
```

---

## 6. Verification checklist (on the mini)

```bash
ssh christianpompa@10.88.1.208 '
  cd ~/.hermes/hermes-agent;
  ./venv/bin/hermes --version;                                   # shows new local sha
  curl -s -m6 -o/dev/null -w "gateway /health -> %{http_code}\n" http://127.0.0.1:8642/health;
  curl -s -m6 -o/dev/null -w "dashboard       -> %{http_code}\n" http://127.0.0.1:9119/;
  tail -8 ~/.hermes/logs/gateway.log;                           # expect clean boot, no traceback
  ls -d skills/mlops/models/comfyui skills/creative/i2v-landscape-animation'  # delta present
```

Pass = both endpoints `200`, gateway PID stable (not crash-looping), boot log
ends with "Gateway running with N platform(s)" / housekeeping started, and the
delta dirs exist. The gateway `error.log` will show a `SIGTERM` + maybe an
`httpx.RemoteProtocolError` from the *old* instance shutting down — that's
expected from the restart, not a failure.

> Note: `hermes --version` prints `upstream <parent> · local <tip> (+N carried
> commit)`. The "upstream" field is just the snapshot's **parent commit** in the
> fork's linear history — it is NOT the upstream release. Trust the
> `git -C "$WT" diff --stat "$COMMIT" "$NEW"` check from Section 4 (= only our
> delta) for "are we really on the new upstream".

---

## 7. Client machines

Clients normally use the **remote gateway**, so they need **no repo update** to
get the new server behavior:

- **Hermes Desktop app** (e.g. MacBook): connects to the dashboard at
  `http://127.0.0.1:9119` through a **persistent SSH tunnel** to the mini
  (LaunchAgent `com.cpompa.hermes-tunnel` runs
  `ssh -N -L 127.0.0.1:9119:127.0.0.1:9119 christianpompa@10.88.1.208`).
  After a server update just **reload the dashboard / relaunch the app**. Keep
  the installed Desktop app version roughly in step with the server when
  upstream changes the dashboard API.
- **A client with its own checkout** (e.g. this Mac, used for `hermes --tui`):
  to update its *local* code, either relay the snapshot to it the same way as
  the mini, or `git pull` from gitlab (the Mac has creds: `gitlab` remote), then
  `uv pip install -e ".[all]"`. This only matters for local TUI use; it does not
  affect the shared gateway.

The shared LAN agent endpoint is `hermes-serv.cpompa.com:8642` (gateway binds
`0.0.0.0`, vanity host OK). The dashboard is loopback-only per machine via its
own tunnel (anti-DNS-rebinding rejects non-loopback Host headers).

---

## 8. Rollback

```bash
# on the mini
ssh christianpompa@10.88.1.208 'U=$(id -u); cd ~/.hermes/hermes-agent &&
  git reset --hard backup/pre-update-<YYYYMMDD> &&
  ~/.local/bin/uv pip install -e ".[all]" --python venv/bin/python &&
  launchctl kickstart -k gui/$U/ai.hermes.gateway &&
  launchctl kickstart -k gui/$U/ai.hermes.dashboard'
```

The `backup/pre-update-*` tag is on gitlab too, so the fork `main` can also be
reset/force-pushed back from the Mac if a bad snapshot was published.

---

## 9. Quick gotcha index

- `-25308` / "could not read Username" on the mini → keychain locked over SSH;
  relay from the Mac instead (Section 5). Never try to push gitlab from a
  non-interactive mini SSH session.
- Massive merge conflicts → you tried to merge/pull upstream. Don't. Build a
  snapshot (Section 4).
- `:8000` is **command-center (jackson_biz)**, not Hermes. Gateway is `:8642`.
- venv has no `pip` → use `uv pip ... --python venv/bin/python`.
- BSD `xargs`/`date` quirks → list delta paths explicitly; let the shell/human
  compute dates (AI sandboxes may block `date`).
- Editable install means a `git reset` makes code live immediately, but the
  **running** gateway only picks it up on restart — always kickstart after.
```
