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

**Last sync:** 2026-07-20 — vendored upstream `134c2ed8b`
(**0.18.2 / 2026.7.7.2+**, 2,196 commits since `a9b55989`). Patch outcomes
this sync: the **MoA multimodal-content fix is DROPPED** (upstream fixed it:
`8582f35d9` flatten structured content in the advisory view, plus
`b4c2c4f92`/`b013ed03e`); terminal-bridge + MoA observability patches
**ported** onto upstream's refactored code (upstream's versions win, our
behavior worked around them — details per item below); hooks registration +
metrics-lite applied **clean**; **leading-user-turn invariant added** to the
delta (was committed 2026-07-10 on the old base, first carried here).

Remote naming differs per machine:
- **mini** (gateway, `~/.hermes/hermes-agent`): `origin` = gitlab, `upstream` = GitHub
- **Mac** (`~/.hermes/hermes-agent`): `origin` = GitHub, `gitlab` = gitlab

## Fork delta (re-apply after each upstream sync)

### Core code patches (⚠ upstream-owned files — check first on every sync)
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
  (2026-07-10; ported 2026-07-20).** `_reload_runtime_env_preserving_config_authority()` reloads
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

### Skills — only ours (drop-in, low conflict risk)
- `skills/mlops/models/comfyui/` — remote ComfyUI skill: `queue_workflow.py`,
  `upload_model.sh`, `SKILL.md`, plus realistic + anime example workflows.
- `skills/creative/i2v-landscape-animation/` — I2V landscape skill + the
  `i2v_landscape.py` convenience script.

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

### Agent code — ours, but bundled with a vendored sync ⚠
- `agent/image_routing.py` — sniff magic bytes for image MIME, ignore a
  misleading file suffix. Landed in commit `79c1408c6`, which also carried a
  vendored upstream sync — isolate this hunk when re-applying.

## Source commits (ahead of upstream/main, oldest → newest)

- `4949b5929` feat(skills): add ComfyUI remote skill (mlops/models/comfyui)
- `76a929e82` feat(skills/comfyui): bundle realistic + anime example workflows
- `64e456c3e` feat(skills): add i2v-landscape-animation skill + i2v_landscape script
- `1afb2f88e` feat(skills/creative/comfyui): add I2V landscape animation workflows
- `c21ee5968` chore(skills/creative/comfyui): metadata filter + I2V workflow corrections
- `0f92bd954` chore: post-merge cleanup — HERMES.md persistence rule + CI scope + port fix
- `79c1408c6` fix(image-routing): sniff magic bytes for image MIME, ignore misleading suffix
- `dc514f1db` feat: upgrade agent to v0.17.0 and vendor hermes-desktop v1.2.0 (vendored snapshot)
