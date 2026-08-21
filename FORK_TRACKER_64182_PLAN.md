# Fork ↔ upstream plugin-interface tracker plan (issue #64182)

Reference plan, created 2026-08-03. Informational; no code changes implied.
Upstream tracker: https://github.com/NousResearch/hermes-agent/issues/64182
Comment draft to post: `FORK_TRACKER_64182_COMMENT_DRAFT.md` (same directory).

## Context

Upstream's #64182 is the plan of record for expanding the plugin interface so
contributors with long-queued PRs (and forks like ours) can ship features as
plugins instead of patching core. Maintainer's suggestion to us: register what
our local patches *do* on the tracker so they get absorbed into official
surfaces — then our delta shrinks and sync conflicts mostly disappear.

Ground rules that matter to us:

1. Additive-only plugin API changes (old plugins keep working).
2. Prompt caching is sacred — no mid-conversation system-prompt mutation.
3. Observer-first hooks (mutation designed separately).
4. Fail-closed on security-adjacent surfaces.
5. Desktop chat GUI plugin surface is OUT OF SCOPE (separate design lane).

Key consequence: **we do not push our fork anywhere.** The tracker wants patch
*intents* registered as a comment; a few fixes are salvage candidates as small
PRs against specific sub-issues. Our vendored-snapshot fork structure
(`scripts/fork-sync.sh`, `FORK_CHANGELOG.md`) stays as-is.

## Delta inventory → tracker mapping

Source: `FORK_CHANGELOG.md` fork delta + `PATCH_FILES` in `scripts/fork-sync.sh`.

### Bucket A — tracker-native (register on #64182)

| Patch | Files | Tracker item | Action when it lands |
| --- | --- | --- | --- |
| Shell-hook registration in dashboard + TUI slash-worker | `hermes_cli/web_server.py`, `tui_gateway/slash_worker.py` | #64178 (hook delivery parity), bug #50776 | Verify hooks fire in slash-worker/dashboard, then drop patch from PATCH_FILES |
| API-error surfacing: error-frame enrichment half | `tui_gateway/server.py`, `tui_gateway/compute_host.py` | #64231 batch: #56720 (`turn_failed`), #58524 (`classify_api_error`) | Re-implement enrichment as plugin on the new hooks; drop patch |
| API-error surfacing: store/router half | `hermes_cli/observability/*`, `hermes_cli/web_routers/errors.py` | already plugin-shaped today (existing `api_request_error` hook + `/api/plugins/...` route mounting, per metrics-dashboard precedent) | Optional refactor into a plugin at our own pace |
| MoA per-reference timing/stats + metrics-lite | `agent/moa_loop.py`, `agent/moa_trace.py`, `run_agent.py` | #64231 batch / RFC #58548 (plugin observability hooks) | Re-point forwarder at the new observer hook; drop patch |

### Bucket B — plain upstream bugs (normal PR lane, NOT the tracker)

Ordered by value to us:

1. `gateway/run.py` terminal-env per-turn re-bridge — our only recurring sync
   conflict (conflicted again in the 2026-08-02 sync). Upstream PR = permanent
   deletion of the patch. PR first.
2. Leading-user-turn invariant (`agent/agent_runtime_helpers.py`,
   `agent/conversation_loop.py`) — correctness fix for resumed/compacted
   lineages (Anthropic + Qwen-template 400s).
3. `agent/tool_guardrails.py` no-progress guard for all tools — must explain
   difference vs upstream's newer per-turn `LoopCapConfig`.
4. `tui_gateway/ws.py` SO_KEEPALIVE (dead-peer detection).
5. `tools/session_search_tool.py` compaction-summary anchor demotion.
6. `tools/file_tools.py` read_file dedup re-serve — reference upstream #15759.
7. `agent/auxiliary_client.py` NIM `reasoning` extra_body skip — provider
   quirk fix (HTTP 400 on integrate.api.nvidia.com).

### Bucket C — stays fork-local (no action)

- Homelab skills: `skills/mlops/models/comfyui/`, `skills/creative/i2v-landscape-animation/`,
  `skills/devops/homelab-jobs/`, additive files on `skills/creative/comfyui/`.
- `.gitlab-ci.yml`, `HERMES.md`, `FORK_UPDATE_RUNBOOK.md`, this plan.
- Desktop/electron patches (`--cwd` on remote gateway, preview openExternal
  fallback) — out of tracker scope (ground rule 5); maintain locally; normal
  PR lane may adopt them (precedent: #66899 absorbed our desktop-plugins door).
- Our plugins `metrics-dashboard`, `model-router` — already plugins; they only
  benefit when #64178 lands.

## Actions

- [x] 1. Post comment on #64182 (draft in `FORK_TRACKER_64182_COMMENT_DRAFT.md`).
      POSTED 2026-08-03: https://github.com/NousResearch/hermes-agent/issues/64182#issuecomment-5170846718
      (gist linked in comment: https://gist.github.com/c-pompa/35d3e58b1a1e377bcaf2ad02579c4714)
      Awaiting maintainer disposition. If item 1 is named a #64178 salvage
      candidate → prep the salvage PR from our patch (2 lines + test).
- [ ] 2. File Bucket B PRs at our own pace, `gateway/run.py` first.
- [ ] 3. Watch #64178, #64229, #64179. When parity + compat suite land: verify
      hook firing on all surfaces, drop the hook-registration patch, consider
      migrating `metrics-dashboard` to the versioned plugin API.
- [ ] 4. (Optional, anytime) Refactor `/errors` store+router into a plugin.
- [ ] 5. Fix `fork-update-status.json` staleness: after a manual resolution is
      pushed, rewrite/clear the status file (or have `fork-verify-fleet.sh` do
      it) so `needs-manual-resolution` cannot outlive its resolution.

## Resolved / historical notes

- 2026-08-02 sync (upstream `a6defd4f`) — COMPLETE. Commit `0f8cfce09` on
  origin/main. `gateway/run.py` conflict resolved theirs-first: upstream map +
  loop body hoisted into `_TERMINAL_CONFIG_ENV_MAP` (incl. upstream's new
  `docker_shm_size` key, gateway/run.py:1812) +
  `_bridge_terminal_env_from_config()`, called at startup (:2055) and per-turn
  (:1745). `fork-update-status.json` still says `needs-manual-resolution` —
  stale (written 31 min before the push); see action 5.
- Dropped patches (no re-apply): `agent/image_routing.py` (native upstream),
  desktop-plugins door (#66899), MoA multimodal fix (upstream flattening).

## If a patch becomes redundant on a future sync

Standard playbook (already proven twice): delete the file(s) from
`PATCH_FILES` in `scripts/fork-sync.sh`, mark the item DROPPED in
`FORK_CHANGELOG.md`, verify upstream's replacement behavior on the next sync.
Nothing is removed before upstream actually ships the replacement.

## Implementation plans (actions 2, 5, 4 — in recommended order)

### Plan B first: status-file staleness fix (action 5) — small, local, ~30 min

Facts established 2026-08-03: `~/.hermes/fork-update-status.json` is written
only by `scripts/fork-auto-update.sh` (`write_status()`, line 37). The daily
job DOES self-heal — once the resolved vendor commit is pushed, the next run
computes `NEW == BASE` and writes `up-to-date` (line 71-77). The real gap is
the window between the manual push and the next daily run (observed: status
said `needs-manual-resolution` 31 min after resolution landed), plus anyone
reading the file in that window acts on stale info.

Implementation:

1. Add a `--mark-resolved` flag to `scripts/fork-auto-update.sh`: parses the
   arg before the main flow, writes `write_status "resolved"
   "\"resolved_upstream\": \"$(git rev-parse upstream/main)\""`, logs, exits 0.
   ~15 lines.
2. Add the step to `FORK_UPDATE_RUNBOOK.md` §4 step 5 (the push step): "after
   pushing the vendor commit, run `scripts/fork-auto-update.sh
   --mark-resolved`".
3. Note it in `FORK_CHANGELOG.md` under infra items.
4. Test: seed a fake `needs-manual-resolution` status file, run the flag,
   verify JSON contents; run the script without the flag and confirm normal
   flow is untouched.

### Plan A: `gateway/run.py` terminal-env upstream PR — SUPERSEDED 2026-08-03 (fixed upstream)

**Outcome: no PR needed.** While preparing the PR we found upstream already
fixed this exact bug in a better shape:

- `e471c7165` "fix(env): make config.yaml authoritative for terminal.backend
  (#29186)" — `load_hermes_dotenv()` now re-applies config.yaml's explicit
  `terminal.*` keys over the reloaded .env on EVERY load, via the shared
  `hermes_cli.config.apply_terminal_config_to_env`. Loader-level, so it
  covers the gateway per-turn reload AND cron/batch_runner — strictly
  superior to our gateway-only re-bridge.
- `a4a91610b` (teknium1, 2026-08-02) adds the regression test driving the
  exact stale-`TERMINAL_ENV=docker` vs `terminal.backend: local` scenario.
- Verified locally 2026-08-03: pristine `upstream/main` (a991dfc25) passes
  both tests in `tests/gateway/test_runtime_env_reload_config_authority.py`
  (2 passed). Neither commit is in our vendored base `a6defd4f` — our patch
  is still needed UNTIL the next sync.

**Next-sync action (replaces the PR):** when the next vendor sync picks up a
snapshot containing `e471c7165`, resolve any `gateway/run.py` conflict fully
"theirs" (drop our hoisted `_TERMINAL_CONFIG_ENV_MAP` /
`_bridge_terminal_env_from_config` + both call sites), remove
`gateway/run.py` from `PATCH_FILES`, mark the patch DROPPED in
`FORK_CHANGELOG.md` noting `e471c7165` as the replacement, and run
`tests/gateway/test_runtime_env_reload_config_authority.py` in the vendor
worktree as the verification gate.

**GitHub-side setup (done, reusable for future Bucket B PRs):** pristine
clone of `NousResearch/hermes-agent` at `~/Documents/github-repos/hermes-agent`
(remote `upstream`, dev venv at `.venv`, on `main` tracking upstream). To PR
the remaining Bucket B fixes later: fork on GitHub (account `c-pompa`),
`git remote add origin git@github.com:c-pompa/hermes-agent.git` — requires
adding `~/.ssh/id_ed25519.pub` to GitHub or `brew install gh` + browser auth
(SSH key exists but is not yet authorized for GitHub, checked 2026-08-03).
The reference-diff trick still applies per file:
`git diff a6defd4f origin/main -- <file>` in the vendored fork.

<details>
<summary>Original PR plan (superseded — kept for the Bucket B template)</summary>

1. Fork `NousResearch/hermes-agent` on GitHub (web UI, account `c-pompa`).
   Clone it to a scratch dir OUTSIDE `~/.hermes/hermes-agent` (never add a
   GitHub remote to the vendored fork — its histories are structurally
   divergent and a mistaken fetch/push there is how banners break):

       mkdir -p ~/Documents/github-repos
       git clone https://github.com/c-pompa/hermes-agent.git \
         ~/Documents/github-repos/hermes-agent
       cd ~/Documents/github-repos/hermes-agent
       git remote add upstream https://github.com/NousResearch/hermes-agent.git
       git fetch upstream
       git checkout -b fix/gateway-terminal-env-rebridge upstream/main

   Nothing is "moved" from GitLab — the fix is re-applied onto a fresh
   GitHub fork; the GitLab repo stays the homelab source of truth.
2. Extract our exact delta as the reference (works because the vendored
   fork's tree = upstream snapshot + delta, so this diff IS the patch):

       cd ~/.hermes/hermes-agent && git fetch upstream
       git diff upstream/main origin/main -- gateway/run.py > /tmp/rebridge.patch

   Try `git apply --3way /tmp/rebridge.patch` in the GitHub clone. If
   upstream drifted since `a6defd4f` and it conflicts, hand-port using
   `~/.hermes/hermes-agent/gateway/run.py` (:1789-1863, :1745, :2055) as the
   reference — the port is small.
3. Port: hoist upstream's terminal map + bridge loop verbatim into
   module-level `_TERMINAL_CONFIG_ENV_MAP` +
   `_bridge_terminal_env_from_config(home, cfg=None)`; call it from the
   startup bridge (passing the loaded cfg) AND from
   `_reload_runtime_env_preserving_config_authority()`'s per-turn path,
   mirroring `_bridge_max_turns_from_config`. Their map (incl.
   `docker_shm_size`) stays authoritative.
4. Regression test (the one from our changelog): `.env` has
   `TERMINAL_ENV=docker`, config.yaml has `terminal.backend: local`; assert
   `TERMINAL_ENV` stays `local` across repeated
   `_current_max_iterations()` calls. Place in their existing gateway test
   layout; run targeted pytest + ruff/ty per their CI before pushing.
5. PR body: problem (per-turn `.env` reload uses `override=True` but only
   re-bridges `agent.max_turns`; a stale `TERMINAL_*` line silently overrides
   config.yaml from turn 2 onward), minimal repro, the fix, the test. One
   line noting we run this in production on a downstream fork. Do NOT
   reference homelab specifics; optionally mention it was flagged in the
   #64182 comment as incoming.
6. Responsive-to-review rule: if maintainers prefer re-asserting the whole
   bridge differently, take their shape — our goal is deletion of the patch,
   not our exact code.
7. After merge: remove `gateway/run.py` from `PATCH_FILES`, mark the item
   DROPPED in `FORK_CHANGELOG.md`, verify on the next vendor sync that
   upstream's reload re-asserts the bridge.

</details>

### Bucket B — upstream verification sweep (2026-08-03, upstream/main a991dfc25)

Checked each remaining fix against current upstream code in the GitHub
clone. Verdicts (all six still needed — only `gateway/run.py` was moot):

| Fix | Upstream state (evidence) | Verdict |
| --- | --- | --- |
| Leading-user-turn invariant | `repair_message_sequence` has Pass 0/1/2 only; no `ensure_user_leads_*` anywhere | **PR SUBMITTED 2026-08-03: https://github.com/NousResearch/hermes-agent/pull/77984** — patch applied clean onto current upstream (Pass 3 + send-time guard + 9 tests). On merge: drop `agent/agent_runtime_helpers.py`, `agent/conversation_loop.py`, `tests/run_agent/test_message_sequence_repair.py` from `PATCH_FILES`, mark DROPPED |
| `tool_guardrails` all-tools no-progress | still gated on `_is_idempotent(tool_name)` (agent/tool_guardrails.py:328); upstream's `LoopCapConfig` is orthogonal | **PR SUBMITTED 2026-08-03: https://github.com/NousResearch/hermes-agent/pull/77991** — all-tools tracking, codes renamed (config keys kept), old-behavior pin replaced by 3 regression tests, LoopCapConfig positioned as orthogonal. On merge: drop `agent/tool_guardrails.py` + `tests/agent/test_tool_guardrails.py` from `PATCH_FILES`, mark DROPPED |
| `ws.py` SO_KEEPALIVE | no keepalive anywhere in `tui_gateway/ws.py` | **PR SUBMITTED 2026-08-03: https://github.com/NousResearch/hermes-agent/pull/77977** — verbatim patch (upstream's `_disable_nagle` unchanged) + fake-socket test. On merge: drop `tui_gateway/ws.py` from `PATCH_FILES`, mark DROPPED |
| `session_search` summary demotion | upstream excludes summaries from *bookends* only (#43175) and demotes *automation sessions* in `_order_for_recall` (#19434) — no demotion of summary FTS hits | **PR SUBMITTED 2026-08-03: https://github.com/NousResearch/hermes-agent/pull/77990** — verbatim patch (region unchanged upstream) + tests. On merge: drop `tools/session_search_tool.py` + `tests/tools/test_session_search.py` from `PATCH_FILES`, mark DROPPED |
| `read_file` dedup re-serve | still hard-BLOCKs at `hits >= 2` (tools/file_tools.py:1403) | **PR SUBMITTED 2026-08-03: https://github.com/NousResearch/hermes-agent/pull/77979** (references #15759) — patch + rewritten TestDedupStubLoopGuard applied clean. On merge: drop `tools/file_tools.py` + `tests/tools/test_file_read_guards.py` from `PATCH_FILES`, mark DROPPED |
| NIM `reasoning` skip | nvidia profile (`plugins/model-providers/nvidia/__init__.py`) is a plain `ProviderProfile` with no `build_api_kwargs_extras` override → `profile_handles_reasoning` False → generic fallback emits `reasoning` extra_body → NIM 400 | **PR SUBMITTED 2026-08-03: https://github.com/NousResearch/hermes-agent/pull/77973** — `NvidiaProfile.build_api_kwargs_extras` override (cloud omits, local NIM keeps fallback) + 8 tests. On merge: drop `agent/auxiliary_client.py` from `PATCH_FILES`, mark DROPPED in FORK_CHANGELOG.md |

Suggested PR order (independent, smallest first): NIM reasoning → ws
keepalive → read_file re-serve → leading-user-turn → session_search
demotion → tool_guardrails (last — needs the LoopCapConfig positioning).

### Plan C: refactor `/errors` backend into a user plugin (action 4, optional)

Wait for the #64182 disposition first — if #56720/#58524 get traction the
design may change. Facts established 2026-08-03: the web server mounts plugin
backend routes from a plugin-declared `api` file exposing a FastAPI `router`
at `/api/plugins/<name>/` (`web_server.py:16977-17081`,
`_mount_plugin_api_routes`); user plugins must be in `plugins.enabled` or
their Python is never imported (security gate, #46435). The
`api_request_error` hook already exists — our `api_errors.py` is just a
consumer. So the backend half is plugin-portable TODAY.

Scope split:

- MOVABLE to a plugin: `api_error_store.py`, `api_error_logs.py`,
  `api_errors.py` (hook consumer), `web_routers/errors.py` (router), the
  `observability/__init__.py` wiring, the `include_router` patch in
  `web_server.py`.
- NOT movable (stays as fork patch until #56720/#58524 land):
  `tui_gateway/server.py` + `compute_host.py` error-frame enrichment.
- FRONTEND — DECIDED 2026-08-03: rebuild as a plugin-shipped **Hermes
  dashboard tab**, exactly how `metrics-dashboard` does it: the plugin's
  `dashboard/manifest.json` declares `tab: {path, position}` + `entry:
  dist/index.js`, and the same `api` file serves the backend
  (`~/.hermes/plugins/metrics-dashboard/dashboard/manifest.json` is the
  working reference). This drops the `web/src/*` + 15 i18n file patches
  ENTIRELY — the fully patch-free option. The tab fetches from
  `/api/plugins/api-errors/...`; the old `/errors` React route and its
  App.tsx/api.ts/title/i18n edits all leave `PATCH_FILES`.

Steps:

1. Create `~/.hermes/plugins/api-errors/` with `plugin.yaml`
   (`provides_hooks: [api_request_error]`, `api:` field → the router file,
   config via `plugins.entries.api-errors.*` for the `errors_source` toggle).
2. Move the four Python files into the plugin package; fix imports (they may
   import core modules like `agent.redact` — allowed; verify no circulars).
3. Replace the `__init__.py` `_safe_observe` wiring with hook registration in
   the plugin's `register(ctx)`.
4. Add `api-errors` to `plugins.enabled` in config.yaml (required — see the
   security gate above).
5. Build the frontend tab: copy `metrics-dashboard`'s `dashboard/` skeleton
   (`manifest.json` with `tab: {path: "/api-errors", position: ...}`,
   `entry: dist/index.js`, same `api` file), port `ErrorsPage.tsx`'s UI
   (Store/Logs toggle, summary chips, filters, 15s poll) into the plugin's
   JS bundle using the same build setup metrics-dashboard uses.
6. Verify: curl `/api/plugins/api-errors/errors[/summary|/meta]`, induce a
   failing turn, confirm a row lands in `api_errors.db` and renders in the
   new tab; confirm the dashboard starts with the plugin disabled
   (fail-quiet); confirm the tab appears after `plugins.enabled` + restart.
7. Remove ALL migrated files from `PATCH_FILES` — the four Python files AND
   `web/src/App.tsx`, `web/src/lib/api.ts`, `web/src/lib/resolve-page-title.ts`,
   `web/src/i18n/*` — mark the patch split in `FORK_CHANGELOG.md` (backend +
   frontend → plugin, error-frame half stays).
8. Move the tests (`test_api_error_*`, `test_web_router_errors`) to a
   plugin-local suite; keep them runnable standalone.

Order rationale: B is tiny and fixes today's misleading status; A has
external review latency so start it early but expect waits; C is the biggest
and benefits from the tracker disposition, so it goes last.
