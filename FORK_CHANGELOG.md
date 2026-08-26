# Fork changelog — `cpompa/hermes-agent`

Homelab-specific changes that live **only** in this fork (gitlab.cpompa.com)
and are **not** in upstream `NousResearch/hermes-agent`. This file is the
recipe for re-applying our delta after taking a fresh upstream snapshot.

## How this fork tracks upstream

This fork **vendors** upstream as squashed snapshot commits rather than
merging upstream history. As a result the two histories are structurally
divergent (`git status` shows "ahead N / behind M" simultaneously) and a
direct `git pull upstream main` will conflict heavily.

**Update procedure:** take a fresh `upstream/main` snapshot, then re-apply
the "Fork delta" items below on top. Verify each still applies cleanly —
items touching upstream-owned files (marked ⚠) are the ones to check first.

**Last sync:** 2026-08-25 — vendored upstream `34041faea8`
(585 commits since `7a54ab22e6`). Two 3-way conflicts, same files as recent
cycles, both resolved upstream-first: `hermes_cli/web_server.py` (kept
upstream's trusted-public-hosts `should_require_dashboard_auth()` gate;
fork's shell-hook registration hunk ported ahead of it),
`tests/run_agent/test_message_sequence_repair.py` (kept upstream's
sibling/composite-id dedup tests; fork's ensure_user_leads + Pass-3 tests
appended). Targeted tests green in the vendor worktree: **377 passed**.
Published as `c896b5854` and deployed same day (mini + this Mac + desktop
rebuild). Two deploy-path bugs found and fixed in the fork-upgrader plugin
(lives outside the repo): the drain probe's recursive `~/.hermes/**` glob
hung on the mini's 7.2G tree past the 60s ssh timeout — now targeted
root + `profiles/*` globs; and a racing desktop session's
`uv venv --clear` on the mini deadlocked the deploy's pip install — venv
rebuilt serially, services restarted, health green.
**Fleet-script fix bundled:** `fork-verify-fleet.sh` defaults moved off
stale names — `MINI_SSH`/`MINI_HTTP` now Tailscale-canonical
`100.73.11.35` (was the pre-rename MagicDNS name
`christians-mini.tailf1af7f.ts.net`), `GATEWAY_HTTP` now
`http://100.73.11.35:8642` (was `hermes-serv.cpompa.com`, whose DNS still
answers the retired LAN IP `10.88.1.208`). Fleet verify 0 failures after.

**Previous sync:** 2026-08-22 — vendored upstream `7a54ab22e6`
(234 commits since `a86569bd1`; v0.20.4 → v0.20.5; also backfills the
missing entry for `47c2d42c4`, the 2026-08-21 vendor of `a86569bd1`).
Patch verdicts: **zero dropped, zero absorbed** this cycle. Three 3-way
conflicts, all in the cron delivery-targets area, all resolved keep-both:
`cron/scheduler.py` (upstream added per-profile Bot Chat targets to
`cron_delivery_targets()`; our per-channel Discord entries appended after
them), `tools/cronjob_tools.py` (`deliver` docstring now documents both
upstream's `'bot-chat[:<profile>]'` and our `'discord:<channel_id>'`),
`tests/cron/test_scheduler.py` (both sides' assertions kept; three of our
Discord tests ported to filter on `t.get("kind")` because Bot Chat entries
carry no `kind`). Remaining 60 patched files applied cleanly.
`agent/auxiliary_client.py` NIM `reasoning`-skip re-verified still needed.
All 6 tracker PRs (#77973/#77977/#77979/#77984/#77990/#77991) still
unmerged upstream — patches stay. Gates green in the vendor worktree:
targeted pytest **320 passed** (scheduler, discord_channels,
message-sequence-repair, tool_guardrails, session_search, file_read_guards,
moa_observability_bridge, api-errors suite), web/desktop/electron `tsc`
clean, vitest cron suites **26 + 28 passed**. Upstream security work now
included: gateway control-socket hardening (#92447), authenticated browser
control broker + permission gates, skills_guard DNS-exfiltration FP fix,
atomic state backups, `hermes update --plan` fork-aware updater.

**Previous sync:** 2026-08-20 — vendored upstream `45f11263b`
(667 commits since `5de09f7b0`; v2026.8.18+513). Patch verdicts:
**one patch DROPPED** — `gateway/run.py` terminal-env per-turn re-bridge:
upstream's `e471c7165` loader-level fix (`load_hermes_dotenv` →
`apply_terminal_config_to_env`, `hermes_cli/env_loader.py:578`) now
re-asserts config.yaml's `terminal.*` over the reloaded .env on EVERY
load, including the gateway per-turn reload — strictly superior to our
gateway-only hoist. `gateway/run.py` is byte-identical to upstream and
leaves `PATCH_FILES`; gate test
`tests/gateway/test_runtime_env_reload_config_authority.py` green on the
pristine upstream file. Two 3-way conflicts, both resolved
upstream-first: `agent/tool_guardrails.py` (upstream added the
`agent.stall_guards` identical-call notice — `STALL_GUARD_*` /
`observe_identical_call` kept; our all-tools no-progress patch already
merged cleanly in the check paths, so the conflicted regions were
exactly the dead idempotent/mutating taxonomy + `_is_idempotent`, now
dropped), `apps/desktop/src/hermes.ts` (upstream split the monolith into
an `src/api/*` barrel — taken wholesale; our two cron-Discord functions
ported into `src/api/cron.ts` on the new `hermesApi`/`connectionScoped`
conventions, type re-exports added to the barrel). Everything else
applied cleanly. `agent/auxiliary_client.py` NIM `reasoning`-skip
re-verified still needed (upstream's new reasoning→Responses-API
translation does not gate the NIM route). All 6 tracker PRs
(#77973/#77977/#77979/#77984/#77990/#77991) still unmerged — patches
stay. Desktop typecheck clean (tsc ×3). Targeted tests green in the
vendor worktree: **354 passed** (message-sequence-repair,
tool_guardrails, session_search, file_read_guards, gateway
env-reload authority, cron scheduler + discord_channels, api-errors
suite, dashboard admin endpoints, moa_observability_bridge).
**Sync-script fix bundled:** `fork-sync.sh` `mktemp` template moved the
X's to the end (`/tmp/fork-delta-XXXXXXXX`) — BSD mktemp never
substituted mid-name X's, so every second run died with
`mkstemp failed … File exists` on the stale literal file.
**Previous sync:** 2026-08-17 — vendored upstream `5de09f7b0`
(1,689 commits since `76d832d38`; v2026.8.16.2+5). Patch verdicts:
**one patch ABSORBED upstream** — `slot_metrics` in `agent/moa_trace.py`
is now native upstream (identical semantics: `_slot_trace` minus
`input_messages`); our copy dropped, only our `_save_moa_metrics`
(metrics-dashboard feed, ungated) kept alongside it. Five 3-way
conflicts, all resolved upstream-first: `agent/conversation_loop.py`
(upstream now routes appends through `message_metadata.append_message`;
our empty-content+reasoning `_INTERRUPTED_PLACEHOLDER` write-side fix
ported on top), `agent/moa_trace.py` (see above),
`web/src/lib/cron-job.ts` (upstream absorbed the `context_from`/"self"
continuity normalization — ours dropped; our Discord deliver split
`composeDeliver`/`extractDiscordChannelTarget` ported),
`apps/desktop/src/app/cron/index.tsx` (upstream added the
`mutateAndRefreshCronJobs` wrapper on create — kept; our
`composeDeliver(values.deliver, values.discordChannelId)` ported into
it), `tests/run_agent/test_message_sequence_repair.py` (upstream added
dedup assertions; our leading-user-invariant Pass 3 /
`ensure_user_leads_api_messages` tests appended — still absent upstream).
Everything else applied cleanly. Targeted tests green in the vendor
worktree: **204 passed** (message-sequence-repair, tool_guardrails,
session_search, moa_observability_bridge, cron scheduler).
**Previous sync:** 2026-08-02 (candidate prepared) — vendoring upstream `a6defd4f1`
(635 commits since `126ff7071`; v2026.7.30+497). Patch verdicts:
**one patch DROPPED** — `agent/image_routing.py` (2026-06, magic-byte MIME
sniffing) is now native upstream in identical form
(`_sniff_mime_from_bytes`, "magic-byte sniffing wins (authoritative)") —
byte-identical to our version, zero-loss drop, removed from the delta.
Everything else **still needed**; one 3-way conflict
(`gateway/run.py` terminal-env bridge — resolved theirs: our hoisted
`_bridge_terminal_env_from_config` call; upstream's map is unchanged except
the new `docker_shm_size` key, which was ADDED to our hoisted
`_TERMINAL_CONFIG_ENV_MAP` to match). **Sync-script gap found + fixed:**
`tools/file_tools.py` + `tests/tools/test_file_read_guards.py` (the
2026-08-01 read_file re-serve patch) were missing from `PATCH_FILES` in
`fork-sync.sh` and would have been silently dropped — added, patch applied
cleanly to the candidate. Our test expectations ported to upstream's new
read_file default limit (500→2000: `lines 1-2000` / `next_offset=2001`).
Upstream-active regions verified non-overlapping with our hunks:
`agent/auxiliary_client.py` (upstream's new NIM branch is attribution
headers only — our `reasoning` extra_body skip stays), dashboard/TUI
hook registration (upstream still CLI/gateway-only), MoA timing
(`duration_s` still absent upstream), leading-user-turn guard, ws
keepalive, session-search demotion — all 0 upstream hits. Targeted tests
green in the vendor worktree: **108 passed** (message-sequence-repair,
tool_guardrails, session_search, file_read_guards).
**New upstream capabilities to adopt after deploy:** session watchdog +
stall/compress timeout keys (`agent.session_stall_timeout` — addresses the
2026-07-27 stall class), outbound webhooks (`feat(hooks)` — signed
lifecycle events to external HTTP; candidate future transport for the
metrics pipeline, could retire `forwarder.py`), A2A protocol plugin
(#514), native kanban desktop plugin (backend already live), Node 26
required (installers heal automatically), `docker_shm_size` default 1g,
recoverable terminal truncation (spills full output to disk).

**Previous sync:** 2026-07-31 — vendored upstream `126ff7071`
(1,867 commits since `78c06525e`; v2026.7.30+8). Patch verdicts:
**one patch DROPPED** — the local desktop-plugins door (2026-07-21) is
now native upstream in a superior form (#66899, `e614876c6` +
`eaecca4a7`: always-local, profile-aware `hermes:fs:desktopPluginsRoot`);
`preload.ts`, `runtime-loader.ts`, `plugins-settings.tsx` are
byte-identical to upstream again. Everything else **still needed**;
three areas needed conflict ports (upstream touched ALL 19 patched
files): tool_guardrails (upstream added its own orthogonal per-turn
`LoopCapConfig` loop caps — both kept; restored the `dataclasses.field`
import our hunk dropped; upstream's old-behavior test replaced with our
3 regression tests), gateway/run.py (upstream's new `vercel_runtime`
map key folded into our hoisted `_TERMINAL_CONFIG_ENV_MAP`), and the
session_search/message-sequence test files (upstream test-prune waves
had deleted our hunks' anchor tests — ported our tests only, did NOT
resurrect pruned upstream tests). fork-sync.sh `PATCH_FILES` was
extended first with the post-2026-07-25 patch files (tool_guardrails,
session_search, ws) that it would otherwise have silently dropped.
Targeted tests green in the vendor worktree: **406 passed**
(message-sequence-repair, tool_guardrails, session_search, moa-trace,
shell-hooks, tui_gateway ws + slash-worker suites). No LM
Studio-relevant upstream changes except `8c12fa7cf` (respect applied
runtime context) — no action needed.

**Previous sync:** 2026-07-25 (second same day) — vendored upstream `78c06525e`
(5 commits since `32fd9d65c`, all Desktop renderer fixes: stale
action-handler routing in memoized surfaces / latest-actions adapters).
Patch verdicts: **all patches still needed**; upstream's changes touch only
`apps/desktop/src/app/{contrib,session/hooks}` — zero overlap with our
patched files — and the whole delta applied clean via 3-way
(`scripts/fork-sync.sh`). No Python or dashboard/LM Studio-relevant changes.

**Previous sync:** 2026-07-25 — vendored upstream `32fd9d65c`
(647 commits since `de5ece994`). Patch verdicts: **all patches still
needed** (now including the 2026-07-25 preview-browser-fallback Desktop
patch, committed to the delta just before this sync). One 3-way conflict:
the `agent/moa_loop.py` import block (upstream added `re`/`threading`/
`_futures_wait` alongside a large reference-accounting rework) — resolved
by unioning imports; the `duration_s`/stats accounting + `_save_moa_metrics`
hunks landed intact around upstream's interrupted-reference and
context-trim changes. Upstream still does NOT register shell hooks in the
dashboard/slash-worker paths and has none of the Desktop patch symbols —
nothing dropped. No new Python deps (only a `requires_wal` pytest marker);
no LM Studio-related upstream changes. Targeted tests green in the vendor
worktree (message-sequence-repair + shell-hooks 102, moa 83).

**Previous sync:** 2026-07-23 — vendored upstream `de5ece994`
(597 commits since `d7b36070e`). Patch verdicts: **all patches still
needed** (now including the two 2026-07-21 Desktop patches, committed to the
delta just before this sync). One 3-way conflict: upstream added a
persistent-MoA prepare block in `agent/conversation_loop.py` at our
leading-user-turn guard's insertion point — resolved upstream-first, guard
re-placed AFTER the MoA block (mutating the rebased `api_messages` also
fixes the prepared MoA request in place). Everything else applied clean
via `scripts/fork-sync.sh`. MoA multimodal fix remains dropped (upstream
flattening intact); no LM Studio-related upstream changes.

**Previous sync:** 2026-07-20 — vendored upstream `d7b36070e`
(**0.19.0 / v2026.7.20 + 28**, 152 commits since `134c2ed8b`). Patch verdicts:
**all six patches still needed** (upstream untouched in every patched area);
the whole delta applied clean via 3-way (`scripts/fork-sync.sh`). MoA
multimodal fix remains dropped (upstream flattening intact).

**Previous sync:** 2026-07-20 (earlier same day) — vendored upstream
`134c2ed8b` (0.18.2 / 2026.7.7.2+, 2,196 commits since `a9b55989`). The MoA
multimodal-content fix was DROPPED there (upstream fixed it: `8582f35d9`,
`b4c2c4f92`, `b013ed03e`); terminal-bridge + MoA observability patches were
ported onto upstream's refactored code (upstream's versions win, our behavior
worked around them — details per item below); hooks registration +
metrics-lite applied clean; leading-user-turn invariant added to the delta.

Remote naming (unified 2026-07-23, both Mac and mini):
- `origin` = gitlab.cpompa.com (our fork), `upstream` = GitHub NousResearch.
- Before 2026-07-23 the Mac had `origin` = GitHub, `gitlab` = gitlab — that
  reversed naming also made the Mac's update banner count `HEAD..origin/main`
  against upstream's divergent history ("9863 new changes available").

## Fork delta (re-apply after each upstream sync)

### Core code patches (⚠ upstream-owned files — check first on every sync)
- ⚠ `hermes_cli/web_server.py` (lifespan) — **cron ticker for isolated
  profile dashboards (2026-08-12).** The dashboard cron ticker was gated on
  `HERMES_DESKTOP=1`, so launchd-started `hermes -p <name> dashboard`
  backends (home = `profiles/<name>`) never ticked: profile cron jobs (e.g.
  hitl-v1's `cursor-transcript-sync`) only fired while the Desktop app had
  that profile open. The ticker now also starts when `get_hermes_home()` is
  a profile home; the `cron/.tick.lock` file lock keeps it at-most-once next
  to a real gateway. Tests: `test_profile_dashboard_lifespan_starts_cron_ticker`
  / `test_non_profile_dashboard_lifespan_skips_cron_ticker` in ⚠
  `tests/hermes_cli/test_dashboard_admin_endpoints.py`.
- **Cron per-job Discord results channel (2026-08-12).** A cron job can opt
  into ALSO posting its results to a per-job Discord text channel
  (`cron-<slug>`), strictly additive to its existing `deliver` targets —
  local file output and the base delivery always happen; a Discord-side
  failure (e.g. reset bot token) is recorded as `last_delivery_error` and
  never fails the job (guaranteed by the existing `_deliver_result` /
  `mark_job_run` isolation — no scheduler delivery changes). Parts:
  - NEW `cron/discord_channels.py` — channel-name slugifier + Discord REST
    provisioning (`list_guilds`, live `list_guild_text_channels` /
    `list_all_text_channels`, `create_results_channel`); bot token via
    profile-scoped `get_secret("DISCORD_BOT_TOKEN")`; 401 → DiscordAuthError,
    403 → Manage Channels hint. `list_text_channels` reads the cached
    channel_directory.json (never raises) for feed builders.
  - ⚠ `hermes_cli/web_routers/cron.py` + `hermes_cli/web_server.py` +
    `hermes_cli/web_models.py` — `GET/POST /api/cron/discord-channels`
    (late-bound `_list/_create_cron_discord_channel_sync` workers;
    `_run_cron_async` threadpool→asyncio bridge; `DiscordChannelCreate`
    model; auth/permission errors → 502, guild-resolution errors → 400).
  - ⚠ `cron/scheduler.py` (`cron_delivery_targets`) — appends per-channel
    entries (`kind: "channel"`, id `discord:<channel_id>`) after platform
    entries; silently degrades when the directory is unreadable.
  - ⚠ `tools/cronjob_tools.py` — `deliver` schema doc text only.
  - ⚠ Desktop cron editor (`apps/desktop/src/app/cron/*`, `hermes.ts`,
    `types/hermes.ts`, `i18n/*`) and ⚠ web CronPage (`web/src/pages/
    CronPage.tsx`, `web/src/lib/cron-job*.ts`) — "Discord results channel"
    block: toggle + channel picker + Create/Use `cron-<slug>` button;
    `composeDeliver` appends `discord:<id>`, strips only the managed entry,
    never touches non-Discord targets.
  - `apps/desktop/src/plugins/gateway-pill/plugin.tsx` — our `defaultEnabled:
    false` patch (2026-08-12) was DROPPED in the 2026-08-12 sync: upstream
    deleted the dogfood gateway-pill plugin outright (the native statusbar
    item is the only one now). Removed from fork-sync PATCH_FILES.
  - Tests: `tests/cron/test_discord_channels.py`,
    `tests/hermes_cli/test_cron_discord_channels.py` (both NEW/additive),
    ⚠ `tests/cron/test_scheduler.py`, ⚠ desktop/web cron test files.
  - ⚠ `apps/desktop/src/api/cron.ts` joined `PATCH_FILES` (2026-08-22):
    upstream's `aa20dbe73` refactor split `hermes.ts` into `src/api/*` domain
    modules and our `getCronDiscordChannels` / `createCronDiscordChannel`
    moved with it, but the file was never listed — the 2026-08-21 vendor
    (`a86569bd1`) silently dropped both functions while `app/cron/index.tsx`
    kept importing them, breaking the desktop build ("App build out of date"
    warning could not be rebuilt away). Hunk restored from the last good
    build (`ccc4229e7`); listed so the 3-way re-apply carries it forward.
- ⚠ `hermes_cli/main.py` (`cmd_dashboard`) — **register outbound webhooks for
  `serve`/`dashboard` backends (2026-08-03).** `_prepare_agent_startup()`
  (which wires `hooks.outbound`) only runs for `_AGENT_COMMANDS`
  (`chat`/`acp`/`rl`/`gateway run`/`cron`/`mcp serve`) — but desktop-spawned
  `hermes serve` backends serve agent turns too, so desktop turns never fired
  `post_api_request` webhooks (metrics pipeline gap: CLI turns recorded,
  desktop turns invisible). Patch: `register_from_config(load_config())` early
  in `cmd_dashboard`, after the --status/--stop exits. Idempotent per process
  (`_registered` dedup). main.py is already in fork-sync `PATCH_FILES`.
- **API error surfacing for the dashboard (2026-08-02)** — turns that failed
  showed a bare `request failed` in the desktop/TUI while the rich detail
  (provider, base_url, model, HTTP status, summary, fallback chain) only
  reached `logs/agent.log`. Parts:
  - NEW `hermes_cli/observability/api_error_store.py` — sqlite
    `~/.hermes/api_errors.db` (WAL/busy_timeout/always-close pattern copied
    from `agent/verification_evidence.py`; `agent.redact` on messages; the
    hook's `request` payload is never persisted).
  - NEW `hermes_cli/observability/api_errors.py` — consumer of the existing
    `api_request_error` lifecycle hook; ⚠ `hermes_cli/observability/__init__.py`
    wires it via the codebase's own `_safe_observe` (3 lines).
  - NEW `hermes_cli/observability/api_error_logs.py` — alternate log-tail
    source (parses `agent.log` failure lines into the same row shape).
  - NEW `hermes_cli/web_routers/errors.py` — `GET /api/errors[/summary|/meta]`;
    ⚠ one `include_router` in `hermes_cli/web_server.py`. Source toggle:
    `observability.errors_source: store|logs` (default store) or `?source=`.
  - NEW `web/src/pages/ErrorsPage.tsx` (+ ⚠ edits `web/src/App.tsx`,
    `web/src/lib/api.ts`, `web/src/lib/resolve-page-title.ts`, `web/src/i18n/*`)
    — dashboard `/errors` page with Store/Logs toggle (Logs shows its cons),
    summary chips, filters, 15s poll.
  - ⚠ `tui_gateway/server.py` + `tui_gateway/compute_host.py` — empty/generic
    turn-error frames now carry the classified summary + `— details:
    dashboard /errors` instead of surfacing as a bare `request failed`.
  - Tests: `tests/hermes_cli/test_api_error_{store,logs}.py`,
    `test_web_router_errors.py`, `test_observability_api_errors.py`.
- `agent/auxiliary_client.py` (`_build_call_kwargs`) — **never emit the
  `reasoning` extra_body for NVIDIA NIM (2026-08-02).** Every model on
  `integrate.api.nvidia.com` rejects the parameter outright (HTTP 400
  "Unsupported parameter(s): `reasoning`"), including
  `{"enabled": false}` — so a MoA aggregator/advisor on NIM could never
  succeed whenever any reasoning_config resolved (e.g. global
  `agent.reasoning_effort: medium` flows into the MoA aggregator via
  `_aggregator_reasoning_config`). The generic reasoning emit is now
  skipped when the base URL contains `integrate.api.nvidia.com`. Pair
  with `reasoning_effort: none` on NIM MoA slots (set on the `nvidia`
  preset aggregator in config.yaml).
- `hermes_cli/web_server.py` (`start_server`) + `tui_gateway/slash_worker.py`
  (`main`) — **shell-hook registration for dashboard + TUI-worker processes
  (2026-07-12).** Upstream only registers declarative shell hooks in the CLI
  agent commands and `gateway run` entry points; dashboard chat sessions and
  TUI slash workers run full agent turns WITHOUT hooks, so
  `post_api_request`/`subagent_stop` observability silently never fires for
  them (metrics dashboard showed only cron/CLI traffic). Both now call
  `register_from_config(load_config(), accept_hooks=False)` at startup,
  mirroring `gateway/run.py` (consent via `hooks_auto_accept`/env).
- `gateway/run.py` — **per-turn .env reload clobbering terminal config fix
  (2026-07-10; ported 2026-07-20) — DROPPED 2026-08-20 (fixed upstream).**
  Upstream's `e471c7165` made `load_hermes_dotenv()` re-apply config.yaml's
  explicit `terminal.*` keys over the reloaded .env on every load
  (`hermes_cli/env_loader.py:578` → `hermes_cli/config.py:3474`
  `apply_terminal_config_to_env`) — loader-level, so it covers the gateway
  per-turn reload AND cron/batch_runner. Verified: pristine upstream
  `gateway/run.py` passes
  `tests/gateway/test_runtime_env_reload_config_authority.py` in this
  snapshot. Our `_TERMINAL_CONFIG_ENV_MAP` /
  `_bridge_terminal_env_from_config` hoist is gone; `gateway/run.py`
  removed from `PATCH_FILES`. Do NOT re-apply; verify on each sync that
  the loader re-assert remains. Original patch notes below for the record: `_reload_runtime_env_preserving_config_authority()` reloads
  `~/.hermes/.env` with `override=True` every turn (via
  `_current_max_iterations()`) but only re-bridged `agent.max_turns` — so a
  stale `TERMINAL_ENV=docker` in `.env` silently overrode config.yaml's
  `terminal.backend: local` after the first turn (sessions reported
  deployment "docker" while the gateway showed "local"). Fix: hoisted the
  startup bridge's terminal map/loop into module-level
  `_TERMINAL_CONFIG_ENV_MAP` + `_bridge_terminal_env_from_config(home, cfg=None)`,
  called from both the startup bridge (passing the loaded `_cfg`) and the
  per-turn reload (loads config.yaml fresh, mirrors
  `_bridge_max_turns_from_config`). Verified: with `.env` `TERMINAL_ENV=docker`
  + config `backend: local`, `TERMINAL_ENV` stays `local` across
  `_current_max_iterations()` calls (pre-fix it flipped to `docker`).
  Check on every upstream snapshot until upstream fixes the reload to
  re-assert the full terminal bridge.
  **2026-07-20 port note:** upstream added its own inline startup bridge
  (with `docker_network` in the map and SSH-tilde-aware cwd handling via
  `tools.terminal_tool._is_ssh_remote_tilde_cwd`) but still does NOT
  re-bridge on the per-turn reload. Our hoist now uses upstream's map +
  loop body verbatim; only the hoisting + per-turn call are ours.
- `agent/moa_loop.py` + `agent/moa_trace.py` + `run_agent.py` — **MoA
  per-reference call timing + provider stats passthrough (2026-07-10/12).**
  `_RefAccounting` gains `duration_s` and `stats` slots, `_run_reference()`
  wraps its `call_llm` in a `time.monotonic()` timer and captures a non-empty
  response-root `stats` dict (LM Studio: tokens/sec, TTFT, speculative-draft
  counts — empty `{}` in 0.4.x REST but populated in some builds), and
  `moa_trace._slot_trace()` writes both into each reference's trace record.
  `run_agent._usage_summary_for_api_request_hook()` likewise attaches a
  non-empty `response.stats` as `summary["stats"]` so the `post_api_request`
  hook payload carries it. With `moa.save_traces: true` this gives
  per-proposer wall-clock duration (→ tokens/sec) per MoA turn in
  `~/.hermes/moa-traces/<session_id>.jsonl`, consumed by the metrics
  dashboard's forwarder. The aggregator's acting call needs no patch — it is
  already timed by the `post_api_request` hook (`api_duration`). Also
  (2026-07-12): `moa_trace._save_moa_metrics()` writes a metrics-lite record
  (per-proposer usage/duration/stats, NO message bodies) to
  `<hermes_home>/metrics/moa-refs.jsonl` on EVERY MoA turn, **independent of
  `moa.save_traces`** — preset editors (`hermes moa` / dashboard MoA panel)
  rewrite the `moa:` block and drop `save_traces`, which used to silently
  kill proposer observability. Small, additive; re-apply on upstream sync.
  **2026-07-20 port note:** `_run_reference()` was refactored upstream
  (advisory system prompt + `_maybe_apply_moa_cache_control` decoration);
  the `time.monotonic()` wrap now starts before the `try:` (covers failures)
  and the success/failure `_RefAccounting` constructors both take
  `duration_s`. `moa_trace.py` was untouched upstream → applied clean.
- `agent/agent_runtime_helpers.py` + `agent/conversation_loop.py` +
  `tests/run_agent/test_message_sequence_repair.py` — **leading-user-turn
  invariant (2026-07-10; ported 2026-07-20).** A resumed lineage whose
  history begins with a context-compaction summary merged into a leading
  `assistant(tool_calls)` turn produced payloads shaped
  `system → assistant → tool → … → user`; Qwen-derived LM Studio/LMLink
  templates 400 with `"No user query found in messages."` and Anthropic
  rejects non-user-leading payloads. Two guards: `ensure_user_leads_api_messages()`
  (send-time, API copy only, called in `conversation_loop` after surrogate
  sanitization, before the token estimate) and `repair_message_sequence()`
  **Pass 3** (persisted history, normalized once). Both insert a minimal
  `_LEADING_USER_BRIDGE` user turn ahead of the offending turn; no-op on
  well-formed payloads. Port notes: upstream added
  `repair_message_sequence_with_cursor` (delegates to `repair_message_sequence`,
  so Pass 3 stays live on the persistence path) and its own tests at the
  same test-file path — our 9 tests are appended to upstream's file.
- `agent/moa_loop.py` — **MoA reference multimodal-content fix (2026-07-02) —
  DROPPED 2026-07-20 (fixed upstream).** Upstream's `_reference_messages()`
  now flattens structured/list content itself (`8582f35d9` "flatten
  structured message content in the advisory view", plus `b4c2c4f92`
  drop-empty-user-turns and `b013ed03e` placeholder scoping), covering the
  case our `_content_text()` patch handled (list/multimodal user turns
  dropped to `""` → LM Studio 400 `"No user query found in messages."`).
  Do NOT re-apply; verify on each sync that upstream's flattening remains.
- `hermes_cli/main.py` (`cmd_gui`) + `apps/desktop/electron/main.ts` +
  `apps/desktop/src/global.d.ts` + `apps/desktop/src/store/session.ts` —
  **honor `hermes desktop --cwd` on a remote gateway (2026-07-21).** Upstream
  only consults `HERMES_DESKTOP_CWD` via `resolveHermesCwd()` (local-backend
  spawns / dialog defaults); with `HERMES_DESKTOP_REMOTE_URL` set (our
  launchd env override to the mini's dashboard), the boot workspace comes
  from the remembered-per-remote localStorage value, else the gateway's
  `/api/fs/default-cwd` (= mini gateway's own cwd,
  `~/.hermes/hermes-agent`) — and `setCurrentCwd` persists every session
  switch, so the remembered value permanently drifts back to hermes-agent.
  Patch: `cmd_gui` exports `HERMES_DESKTOP_CWD_EXPLICIT=1` only when `--cwd`
  was passed (the implicit shell-cwd default must NOT win); Electron main
  adds `resolveExplicitLaunchCwd()` (validates exists + not install dir) and
  returns it as `explicitLaunchCwd` from the
  `hermes:setting:defaultProjectDir:get` IPC; renderer
  `ensureDefaultWorkspaceCwd()` remote branch seeds
  `explicitLaunchCwd || remembered` (seeding persists it as the new
  remembered value, so subsequent new chats land there too). Requires the
  packaged app rebuild (`hermes desktop --build-only`) after re-applying.
- `apps/desktop/electron/main.ts` + `preload.ts` +
  `apps/desktop/src/contrib/runtime-loader.ts` +
  `apps/desktop/src/app/settings/plugins-settings.tsx` +
  `apps/desktop/src/global.d.ts` — **local desktop-plugins door on a
  remote gateway (2026-07-21) — DROPPED 2026-07-31 (fixed upstream).**
  Upstream shipped a strictly better native fix as #66899 (`e614876c6`
  "resolve local plugin root independent of remote backend" +
  `eaecca4a7` profile-aware follow-up): a main-process
  `hermes:fs:desktopPluginsRoot` IPC that is always-local and
  profile-aware (`profiles/<name>/desktop-plugins`), wired into the
  disk-plugin scanner, `startDirWatch`, and the Settings reveal button,
  with regression tests in `runtime-loader.test.ts`. Our
  `hermes:desktopPluginsDir` IPC + `resolveDiskPluginsDir()` are gone;
  `preload.ts`, `runtime-loader.ts`, and `plugins-settings.tsx` are
  byte-identical to upstream. Do NOT re-apply; verify on each sync that
  upstream's resolver remains.
- `apps/desktop/electron/main.ts` — **preview "open in browser" falls back to
  revealing the file in the file manager (2026-07-25, revised same day).**
  `shell.openExternal(file:…)` resolves through the OS handler for the
  file's *type* and rejects with "No application found to open URL" (macOS
  LaunchServices) when none is registered. A browser can't cover the gap
  (verified: Safari silently no-ops on handler-less file URLs in every
  `open -a` form; Chromium just downloads), so on failure the patch logs
  `[preview] openExternal failed…` to desktop.log and calls
  `shell.showItemInFolder` — deterministic and cross-platform. Requires the
  packaged app rebuild (`hermes desktop --build-only`) after re-applying.
- `apps/desktop/src/app/settings/about-settings.tsx` — **`settings.about`
  plugin contribution slot under the native Updates section (2026-08-20).**
  Renders `<Slot area="settings.about" />` between the automatic-updates
  ListRow and the UninstallSection — null when no plugin contributes, so the
  page is byte-identical in behavior without the plugin. Our `fork-upgrader`
  desktop plugin mounts its fork-upgrade card there (next to the native
  update chip/section, per user request). One import + one component; resolve
  upstream-first on sync conflicts (keep their section layout, re-place the
  Slot at the end of the Updates block). Candidate for a future upstream PR
  in the #64182 lane (same shape as the #66899 desktop-plugins door).
  Requires the packaged app rebuild (`hermes desktop --build-only`) +
  re-sign after re-applying.
- `agent/tool_guardrails.py` + `tests/agent/test_tool_guardrails.py` —
  **no-progress loop guard applies to ALL tools (2026-07-29, commit
  `9a69ed84e`).** Upstream's no-progress detector (identical args +
  identical result) only ran for a hardcoded allowlist of read-only tools,
  so a loop of successful identical terminal commands (same command, same
  exit-0 output) never tripped the guardrail (live incident 2026-07-29,
  session `20260729_184140_4fa3e6`: 45 tool turns before manual abort).
  Patch: track all tools uniformly, drop the idempotent/mutating taxonomy;
  streak still resets on any changed result (legit polling unaffected);
  decision codes renamed `idempotent_no_progress_*` → `no_progress_*`
  (config keys keep the old names for backward compat). **2026-07-31 port
  note:** upstream added its own per-turn `LoopCapConfig` loop caps —
  orthogonal, both kept; upstream also pruned this test file and kept one
  old-behavior test (`..._not_blocked_for_repeated_identical_success_output...`)
  which our 3 regression tests replace. Watch both regions on each sync.
- `tui_gateway/ws.py` + `tools/session_search_tool.py` +
  `tests/tools/test_session_search.py` — **dead-peer detection +
  compaction-summary anchor demotion (2026-07-27, commit `ebf759812`).**
  `ws.py` sets SO_KEEPALIVE (30s idle / 10s interval / 3 probes) on
  websocket sockets: a silently-dropped client (SSH tunnel reset, client
  sleep) left the TCP leg half-open forever, `receive_text()` blocked
  indefinitely, and disconnect teardown (detach, orphan reap, resume
  replay) never ran. `session_search_tool.py` `_summaries_last` demotes
  compaction-summary FTS hits to the end of discovery results — a summary
  recaps the whole session, matches nearly any keyword, and swallowed the
  single per-lineage drill-down anchor so agents never reached the actual
  work messages (demote-not-exclude: summaries still anchor as last
  resort). **2026-07-31 port note:** upstream's test-prune waves deleted
  our tests' anchor context; our tests are appended, pruned upstream tests
  NOT resurrected. Upstream's `_scroll` rework (`b93fd077c`) is adjacent
  but does not cover demotion — patch stays.
- `tools/file_tools.py` + `tests/tools/test_file_read_guards.py` —
  **read_file dedup re-serve instead of hard BLOCK (2026-08-01).** The
  issue-#15759 stub-loop guard escalated the 2nd dedup stub-hit to
  `tool_error("BLOCKED … your earlier result is still current")` — false in
  long sessions, where context hygiene had already trimmed that earlier
  read from the model's prompt. The model needed the content, was told it
  had it, retried, and each BLOCK counted as an exact-failure until
  `tool_loop_guardrails.hard_stop_after.exact_failure` killed the turn
  (live incident: session `20260801_025055_eb38d2`, 7.19M input tokens /
  273 msgs vs 64k ctx). Patch: on `hits >= 2` fall through to the normal
  read path and re-serve the content with `re_served: true` + actionable
  note (region + next offset) in the result JSON. First repeat still
  returns the cheap `unchanged` stub; the consecutive-read block (4+ in a
  row) and the no-progress result-hash guardrail still bound true loops —
  failure-mode changed from "trapped without content" to "has content,
  must move on". `TestDedupStubLoopGuard` rewritten to the new contract
  (re-serve on 3rd read, stub/re-serve cycle bounded by the consecutive
  block). ⚠ Upstream owns both files; check on every sync.

### Skills — only ours (drop-in, low conflict risk)
- `skills/mlops/models/comfyui/` — remote ComfyUI skill: `queue_workflow.py`,
  `upload_model.sh`, `SKILL.md`, plus realistic + anime example workflows.
- `skills/creative/i2v-landscape-animation/` — I2V landscape skill + the
  `i2v_landscape.py` convenience script.
- `skills/devops/homelab-jobs/` — homelab jobs inventory + audit skill
  (launchd/schtasks/hermes-cron across all machines; added 2026-07-31).

### Skills — additive files on an upstream skill (reconciled 2026-06-30)
- `skills/creative/comfyui/` (exists upstream) — our **additive-only** files:
  - I2V landscape workflows: `animate_diff-i2v-landscape.md.json`,
    `wanvideo-i2v-landscape.md.json` (pure ComfyUI API-format)
  - Their metadata sidecars: `animate_diff-i2v-landscape.meta.json`,
    `wanvideo-i2v-landscape.meta.json` (title/description/requirements/defaults)
  - `scripts/i2v_landscape.py` — convenience wrapper around upstream
    `run_workflow.py` (uses `--input-image`; no upstream-script edits needed)
- **Reconciliation note (2026-06-30):** our old fork patched `run_workflow.py`
  (`--image`/`--mode` + LoadImage/start_image injection) and `_common.py`
  (`unwrap_workflow` metadata strip). The v2026.6.19 upgrade reverted those to
  upstream. Verified upstream now covers the need natively: `extract_schema`
  exposes the `LoadImage` `image` input as an `image` param, and
  `i2v_landscape.py`'s bare `--input-image <path>` maps to it. The only break
  was that upstream's `submit()` no longer strips non-node top-level keys, so
  our `.md.json` metadata (`title`/`mode`/`_meta_*`) would be rejected by
  ComfyUI. Fix: stripped that metadata from the workflow JSONs (now pure
  API-format) into `.meta.json` sidecars — **no upstream-script edits, delta
  stays purely additive.** Nothing in code reads the old `_meta_*` keys anymore.

### Infra / repo config — only ours
- `.gitlab-ci.yml` — homelab GitLab CI (project-scoped runner).
- `HERMES.md` — fork rule: in `hermes -w` worktree mode, commit + push to the
  fork remote before session exit (worktree is wiped on exit).
- `FORK_UPDATE_RUNBOOK.md` — step-by-step procedure for updating this fork to a
  newer upstream while re-applying this delta, and deploying to the mini
  (gateway server) + client machines. Read it before doing an update.
- **`fork-upgrader` plugin (2026-08-20, lives OUTSIDE the repo at
  `~/.hermes/plugins/fork-upgrader/` + `~/.hermes/desktop-plugins/fork-upgrader/`)** —
  fork-aware upgrade assistant: backend API (`/api/plugins/fork-upgrader/`:
  status/preview/impact/report read-only; prepare/test/publish/deploy as
  confirm-gated background jobs), agent tools (`fork_upgrade` with
  `preserve_fork=true` default, `fork_upgrade_report`), dashboard "Upgrades"
  tab, and a desktop half (statusbar chip + upgrader pane + a Settings →
  About card via the `settings.about` slot patch above). Wraps
  `fork-sync.sh`/`fork-verify-fleet.sh`; never merges upstream. Fail-closed:
  publish/deploy need `allowed_actions` in `plugins.entries.fork-upgrader`
  plus confirm=true. Enabled in `plugins.enabled` on MBP + mini; synced to
  the mini via rsync (plugin dir is not in the repo) — **automated since
  2026-08-25: every `deploy` rsyncs both halves to `gateway_host` before the
  remote service restarts** (`plugin_sync` in the job result; failure is
  reported, never masks a deploy). Manual rsync only needed if the plugin
  changes and no deploy runs.

### Agent code — ours, but bundled with a vendored sync ⚠
- `agent/image_routing.py` — sniff magic bytes for image MIME, ignore a
  misleading file suffix. **DROPPED 2026-08-02 (native upstream).** Upstream
  now ships `_sniff_mime_from_bytes` with the same semantics
  ("magic-byte sniffing wins (authoritative)") — our file is byte-identical
  to upstream's. Do NOT re-apply; verify on each sync that upstream's
  sniffing remains.

## Environment / ops notes (NOT in the fork repo — re-apply by hand)

- **2026-07-27 — LM Studio 0.4.20 + fleet model policy.** Updating LM Studio
  unloads all models on that host; afterwards reload per the placement policy
  below and verify `lms ps` + `curl 127.0.0.1:8867/router/status`.
  - **One large model per host.** MBP = `qwen3.6-35b-a3b-uncensored-genesis-hermes-v5`
    ONLY. Pomps = cerebras coder first, 27b optionally after. Mini = gemma MLX.
    Two large models resident on the MBP (~39 GB+) caused repeated memory-pressure
    crashes — if the MBP crashes, `lms ps` first: >1 large model on `Local` is
    the smoking gun.
  - **MBP LM Link preferred device = Pomps** (`lms link set-preferred-device
    1e0a90e866f8d3ba629da3c90c735234`). cerebras + the 27b exist on disk on BOTH
    MBP and Pomps; without this, `lms load <model> -y` from the MBP can pick the
    LOCAL copy (it did, mid-incident). Genesis/gemma are single-device and
    unaffected.
  - **cerebras load params:** `lms load cerebras_qwen3-coder-reap-25b-a3b
    --parallel 3 -c 65536` (was 262144 ctx × parallel 4 — KV cache larger than
    the weights). parallel 3 matches `delegation.max_concurrent_children`.
  - **`hermes/moa-ref-b` is unloaded BY POLICY** (cerebras-only on Pomps), not
    by accident — router resolving it to `None` is expected; MoA runs 2 voices.
    Restore with `lms load qwen3.6-27b-uncensored-hauhaucs-aggressive -y`.
- **2026-07-27 — compression threshold fix (mini profiles).** `hitl-v1` and
  `homelab` profile `config.yaml`s: `threshold_tokens` 40000→**60000**,
  `protect_last_n` 10→**6**. The post-compression floor (system prompt + tool
  schemas + summary + protected tail) measured ~41k tokens — above the old 40k
  threshold, so compression could never succeed and was declared "ineffective"
  after 2 tries, then blocked (killed desktop session `20260727_141845_4a560e`:
  context sat at 46–66k, model truncated/thrashed, client gave up mid-stream).
  These profile configs live on the MINI (`~/.hermes/profiles/*/config.yaml`),
  are NOT tracked in the fork, and must be re-applied if the profiles are ever
  rebuilt. Backups: `config.yaml.bak.20260727-threshold` per profile. Restart
  `ai.hermes.dashboard.<profile>` after editing.
- **2026-07-27 — turn budget, delegation + MoA router alignment, tool-output
  trims (mini profiles).** Session `20260727_162450_e2b26b` hard-stopped at
  `api_calls=90/90` mid-tool-loop (per-turn budget, NOT context).
  - `agent.max_turns` 90→**150** in both mini profiles + MBP
    `~/.hermes/config.yaml` (MBP copy applies on next natural restart).
  - **hitl-v1 delegation** pointed at the policy-unloaded 27b (would fail or
    JIT-load it); now `hermes/subagent-coder` via a new `model-router`
    provider (`127.0.0.1:8867/v1`) — the mini runs its own router instance
    with the same role map. Subagents = cerebras @ Pomps; MoA voices stay on
    MBP/mini — the two features never contend.
  - **hitl-v1 MoA** was stale (`default_preset: test`, voices = 27b +
    distilled 35b, both unloaded — the distilled one would JIT-load as a
    SECOND large model on the MBP = crash condition). Added the `lan` preset
    (router roles `hermes/moa-ref-a/b/c`, agg `hermes/moa-agg`, mirrors the
    MBP config) and set `default_preset: lan`. Old test/default presets kept
    for explicit use only. homelab has no `moa:` section — nothing to align.
  - **`tool_output`** (already present with defaults): `max_bytes`
    50000→**30000**, `max_lines` 2000→**800** — slows context growth so the
    150-call budget stretches further.
  - Backups: `config.yaml.bak.20260727-turns` per profile. Verified: both
    dashboards restarted stable; `hermes/subagent-coder`, `hermes/moa-ref-a`,
    `hermes/moa-agg` all HTTP 200 via the mini's router.
- **2026-07-27 — mini MAIN config aligned + metrics dashboard fixes.**
  - Mini `~/.hermes/config.yaml` (gateway/API + cron): `max_turns` 90→150,
    `threshold_tokens: 60000` added (was ratio-only). Backup
    `config.yaml.bak.20260727-mainalign`; gateway + main dashboard restarted.
  - **env_mode (`~/hermes-metrics-dash/env_mode.py` + `scripts/
    env_mode_remote_apply.py`)** was pre-router and dangerous: rewrote
    optimized-moa to drop the `provider: moa` / `moa://local` hack (now just
    enables MoA with `default_preset: lan`, max_tokens 4096,
    protect_last_n 6), SINGLE_MODEL_ID distilled-35b→genesis (single-model
    mode would have JIT-loaded a 2nd large model on the MBP = crash
    condition), max_turns 90/30→150 everywhere, restore fallbacks updated.
    Both files kept in sync per their own NOTE. Backups `*.bak.20260727-dashfix`.
  - **Dashboard Health rules now dynamic:** new `GET /api/compression-config`
    (app.py) reads `threshold_tokens` live from mini main + profile configs;
    `static/compression.html` consumes it (fallback 60000). The old hardcoded
    40000 constant caused false "0 compactions" alarms after the threshold
    change.
  - **Graph colors:** `--s5` slot was purple/light-purple, too close to
    `--s1` blue — changed to yellow/olive (`#7a6d00` light, `#d6c53a` dark)
    in `static/index.html` (all 3 theme blocks).
  - Forwarder topology verified healthy: mini ingests direct, MBP ships via
    `ai.hermes.metricsfwd` (METRICS_DASH_URL http://10.88.1.208:8899).
    Pomps forwarder down since 2026-07-25 — needs restart on the Windows side.
  - **Pomps forwarder fixed (same day, later):** `HermesMetricsForwarder`
    scheduled task (user `pompa@10.88.1.235` — SSH works; ICMP + `:1234` are
    firewalled, use ssh not ping/curl) had died 7/25 at logoff
    (`0xC000013A`) and never restarted — LogonTrigger only, no restart-on-
    failure, and a 72h `ExecutionTimeLimit` that would keep killing it.
    Started the task, set `ExecutionTimeLimit=PT0S` (unlimited) +
    `RestartCount=3`/`RestartInterval=PT1M`. `Pomps` `host_stats` +
    `pool_status` records flowing again. Launcher:
    `%USERPROFILE%\.hermes\logs\run-metricsfwd.cmd` (env:
    METRICS_DASH_URL=http://10.88.1.208:8899, METRICS_HOST_LABEL=Pomps).
- **2026-07-27 (late) — hitl-v1 data recovery + in-place compression.**
  - `hitl.db` (on mini `/Volumes/SSD_2/.../hitl-v1/data/`) was found with ALL
    tables at 0 rows after the multi-tenancy session work (file written
    19:35, cause of deletion unidentified — the ALTER-based tenant migration
    is provably innocent). Rows were still in freelist pages: recovered via
    sqlite `.recover` → `lost_and_found` fragments → rebuilt DB with
    **251 documents** (re-derived from `data/documents/` folders, sha256
    recomputed), **39 templates** (regions JSON intact), **48 extractions**,
    1 default tenant. Backups: `hitl.db.bak.20260727-prerecovery` (original
    damaged file) + `hitl.db.empty-20260727` (the empty schema shell);
    salvage db at `/tmp/hitl_recovered.db` on the mini (ephemeral).
    14 folders lacked original.pdf; 13 recovered extractions reference docs
    no longer on disk.
  - Session work was committed: branch `feat/multi-tenancy-event-pipeline`
    (`21904ee`, 66 files) — had been entirely uncommitted on main. NOTE:
    `tmp/` scratch files (session dumps, uvicorn log) got swept into the
    commit; prune in a follow-up if unwanted. A stale `.git/index.lock`
    (0 bytes, 2026-07-26) was removed to unblock git.
  - **2026-07-31 follow-up:** the rebuilt db never actually landed — live
    `data/hitl.db` was again an empty shell (wiped 07-28 23:31, cause still
    unknown; freelist clean, likely VACUUMed). Rebuilt a second time
    (`/tmp/hitl_rebuild.py`, re-runnable): **3,831 documents** (incl. the
    07-27/28 upload flood lost in the second wipe — 2,810 <1KB stub PDFs,
    635 image uploads saved as `original.jpg/png`, 28 real PDFs; trim with
    `DELETE FROM documents WHERE uploaded_at >= 1785206400;` → 265 docs if
    unwanted), 39 templates + 48 extractions from the prerecovery freelist
    (4/91 rows unrecoverable-corrupt; 3 test extractions with dangling
    refs). Swapped into `data/hitl.db` (empty shell kept as
    `hitl.db.empty-20260731-preswap`), app restarted — documents + history
    back in the UI, and 3,879 events backfilled into metrics-dash
    `hitl_events` so :8899 `#/events` has history. Supervision: launchd
    CANNOT run it (TCC denies launchd agents access to /Volumes/SSD_2 —
    `PermissionError` on `pyvenv.cfg`); runs nohup via sshd context like
    before. Watch: fork-verify-fleet.sh now FAILs if documents count = 0.
  - **Root cause of the "looping branch":** compression handoffs with
    `in_place: false` mint a new session per compression; each successor
    re-derived the same DB hypothesis ("let me dig deeper" ×12) — text-level
    loops are NOT caught by tool-loop guardrails. Fix applied:
    `compression.in_place: true` in BOTH profiles (hitl-v1:161,
    homelab:156) so investigations keep one session and their state;
    dashboards restarted.
  - Reminder: `SSD_2` is a LOCAL drive on the mini; the MBP only sees it via
    SMB — when the MBP mount drops, "missing data" is a display artifact,
    sessions on the mini are unaffected.

## Source commits (ahead of upstream/main, oldest → newest)

- `4949b5929` feat(skills): add ComfyUI remote skill (mlops/models/comfyui)
- `76a929e82` feat(skills/comfyui): bundle realistic + anime example workflows
- `64e456c3e` feat(skills): add i2v-landscape-animation skill + i2v_landscape script
- `1afb2f88e` feat(skills/creative/comfyui): add I2V landscape animation workflows
- `c21ee5968` chore(skills/creative/comfyui): metadata filter + I2V workflow corrections
- `0f92bd954` chore: post-merge cleanup — HERMES.md persistence rule + CI scope + port fix
- `79c1408c6` fix(image-routing): sniff magic bytes for image MIME, ignore misleading suffix
- `dc514f1db` feat: upgrade agent to v0.17.0 and vendor hermes-desktop v1.2.0 (vendored snapshot)
