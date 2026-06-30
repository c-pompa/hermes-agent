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

Remote naming differs per machine:
- **mini** (gateway, `~/.hermes/hermes-agent`): `origin` = gitlab, `upstream` = GitHub
- **Mac** (`~/.hermes/hermes-agent`): `origin` = GitHub, `gitlab` = gitlab

## Fork delta (re-apply after each upstream sync)

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
