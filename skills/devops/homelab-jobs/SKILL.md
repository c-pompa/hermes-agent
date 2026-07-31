---
name: homelab-jobs
description: Inventory and management of every scheduled/background job in the homelab (launchd on the Macs, Scheduled Tasks on Windows, hermes cron on the mini). Use when asked what jobs exist, to pause/resume/remove a job, to audit job health, or when a scheduled job stops working.
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [DevOps, Jobs, Cron, Launchd, Scheduled Tasks, Homelab, Audit]
---

# Homelab jobs — inventory + management

Single source of truth for every recurring background job in the homelab, what
runs it, and how to manage it. Keep this file updated whenever a job is added,
moved, paused, or retired. Job DEFINITIONS (scripts/plists) live in git:
`cpompa/hermes-agent` (fork delta) and `cpompa/hermes-desktop-iac` (`macos/`,
`windows/`).

## Rules of the road

1. **Execution stays close to the machine.** System jobs run under launchd
   (macOS) / Scheduled Tasks (Windows) — they must survive reboots and must not
   depend on Hermes being up. Agent-prompt jobs use **hermes cron** on the mini.
   Ephemeral reminders use the chat CLI's session cron (dies with the session —
   never for infra).
2. **The mini cannot push/fetch gitlab over SSH** (osxkeychain locked in
   non-interactive sessions, `-25308`). Git operations on the mini's checkout
   are relayed from the MBP.
3. **Never let a job reference a skill/file that isn't in git.** The cautionary
   tale: `hermes-update-monitor` (d6a5e09b5cb2) sat paused 6 weeks pointing at
   a deleted skill; removed 2026-07-31.

## MacBook Pro (`cpompa-mac`, this machine) — launchd, `~/Library/LaunchAgents/`

| Label | Purpose | Schedule |
|---|---|---|
| `com.cpompa.hermes-fork-sync` | Daily hermes-agent fork sync: fetch upstream, build candidate snapshot in `/tmp/hermes-vendor`, run tests, write `~/.hermes/fork-update-status.json` + macOS notification. **Never commits/pushes.** Script: `~/.hermes/hermes-agent/scripts/fork-auto-update.sh` (in fork delta). Plist source: `hermes-desktop-iac/macos/` | Daily 05:40 |
| `com.cpompa.hermes-tunnel` | Keep-alive SSH tunnel `127.0.0.1:9119 → mini:9119` (Desktop dashboard) | KeepAlive |
| `com.cpompa.hermes-mini-sync` | Mini sync helper (`~/.hermes/bin/hermes-mini-sync.sh`) | periodic |
| `com.cpompa.hermes-model-router` | Local model-router service | KeepAlive |
| `ai.hermes.desktop-env` | **DISABLED 2026-07-21** (split-brain remote/local Desktop). Parked in `~/Library/LaunchAgents/disabled/`. Do NOT re-enable | — |
| LM Studio caffeinate agent | Holds `caffeinate` while LM Studio serves (see `hermes-desktop-iac/macos/install-lmstudio-caffeinate.sh`) | KeepAlive |

Manage: `launchctl print gui/$(id -u)/<label>` ·
`launchctl kickstart -k gui/$(id -u)/<label>` ·
`launchctl bootout gui/$(id -u)/<label>` (then bootstrap to re-add).

## Mac mini (`christianpompa@10.88.1.208`) — launchd

| Label | Purpose | Port |
|---|---|---|
| `ai.hermes.gateway` | Hermes gateway (OpenAI-compatible api_server) | :8642 |
| `ai.hermes.dashboard` | Main Hermes dashboard (loopback, SSH-tunneled) | :9119 |
| `ai.hermes.dashboard.hitl-v1` | hitl-v1 profile dashboard | :9121 |
| `ai.hermes.dashboard.homelab` | homelab profile dashboard | :9122 |
| `ai.hermes.metricsdash` | Metrics dashboard (`~/hermes-metrics-dash/app.py`, **Python 3.9** — no `\|` type unions) | :8899 |
| `ai.hermes.metricsfwd` | Metrics forwarder (jsonl → metricsdash) | — |
| `ai.hermes.hitlfwd` | hitl-v1 SSE → metricsdash forwarder (`:8010/api/events` → `:8899/ingest`) | — |
| `ai.hermes.healthdigest` | Health digest | — |

Also on the mini, **hitl-v1** (document OCR, `:8010`,
`/Volumes/SSD_2/XCode_Repos/myprojects/hitl-v1`) runs **nohup via sshd**, NOT
launchd — macOS TCC denies launchd agents access to `/Volumes/SSD_2`
(`PermissionError` on `.venv/pyvenv.cfg`; tried 2026-07-31). It does not
survive a mini reboot: restart with
`cd /Volumes/SSD_2/XCode_Repos/myprojects/hitl-v1 && nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8010 >> /tmp/hitl-8010.log 2>&1 &`.
Its `data/hitl.db` was found wiped twice (2026-07-27/28) — audit step 5
watches for a third time.

Logs: `~/.hermes/logs/`. Verify: `curl -s -o/dev/null -w '%{http_code}' http://127.0.0.1:<port>/health` (or `/`).

## Mac mini — hermes cron (`~/.hermes/cron/jobs.json`)

Agent-prompt jobs run by the gateway's scheduler. Manage ONLY via the CLI:
`hermes cron list` · `hermes cron pause|resume <id>` · `hermes cron remove <id>`.
Known jobs include the weekly **homelab jobs audit** (created 2026-07-31,
runs this skill's audit checklist). When creating jobs, verify the referenced
skill exists in the checkout (`ls ~/.hermes/hermes-agent/skills/...`) — jobs
outliving their skills is a recurring failure mode.

## Pomps-PC (`pompa@10.88.1.235`, Windows) — Scheduled Tasks

| Task | Purpose |
|---|---|
| `HermesDesktopTunnel` | Keep-alive SSH tunnel `127.0.0.1:9119 → mini:9119` (S4U) |
| `HermesMetricsForwarder` | Metrics forwarder → mini :8899 |

Manage over SSH: `schtasks /query /tn <name> /v /fo list` ·
`schtasks /run|/end /tn <name>`. Repos/apps: hermes-agent checkout +
Hermes Desktop at `%LOCALAPPDATA%\hermes\hermes-agent` (updated via git
bundle from the MBP — Windows sshd cmd quoting breaks direct `git push`;
use `git bundle` + scp + `git fetch <bundle>`).

## Audit checklist (weekly cron + on demand)

1. `launchctl print` every label above on both Macs — expect `state = running`
   (or `not running` + recent successful exit for calendar jobs).
2. `schtasks /query` on Pomps-PC — both tasks Ready/Running; tunnel port
   answering: `curl -m6 http://127.0.0.1:9119/` → 200.
3. `hermes cron list` on the mini — every enabled job's skill exists; no job
   with `last_status = error`; paused jobs still have a reason to exist.
4. Freshness: `~/.hermes/fork-update-status.json` (MBP) is < 48h old;
   `metrics.db` hitl_events/records advancing; gateway `requests.jsonl`
   advancing.
5. Data sanity: hitl-v1 `data/hitl.db` document count > 0 (it was found
   wiped twice — 2026-07-27/28; treat 0 rows as an incident, backups in
   `data/`).
6. Report drift to the user; do not silently re-create or delete jobs.
