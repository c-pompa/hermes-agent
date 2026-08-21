# Draft comment for NousResearch/hermes-agent#64182

Paste-ready. Review before posting — written in first person as the fork
maintainer. Everything below is verifiable against our FORK_CHANGELOG.md.

---

## Registration / disposition ask from a downstream fork

Long-time fork maintainer here, taking up the suggestion in the tracker
intro. We run a homelab fork that vendors upstream snapshots and re-applies a
small documented delta (~11 patches) after each sync. Three of those patches
exist only because a plugin/hook surface is missing or silently broken — so
registering them here, mapped to the sub-issues that would let us delete
them. Asking for a disposition on each; happy for these to be folded into the
named sub-issues as requirements, parked, or redirected.

**1. Shell-hook registration in dashboard + TUI slash-worker → #64178 / #50776**

Dashboard chat sessions (`hermes_cli/web_server.py`) and TUI slash workers
(`tui_gateway/slash_worker.py`) run full agent turns without ever calling
`register_from_config()`, so declarative shell hooks
(`post_api_request`, `subagent_stop`, …) silently never fire on those
surfaces — our observability pipeline only saw cron/CLI traffic for weeks
before we noticed. Our patch is two lines: call
`register_from_config(load_config(), accept_hooks=False)` at startup in both
entry points, mirroring `gateway/run.py` (consent still via
`hooks_auto_accept`/env). Happy to send this as a salvage PR against #64178 if
it's useful — it looks like the minimal version of the slash-worker half of
#50776.

**2. MoA per-reference observability → #64231 (RFC #58548 family)**

We patch `agent/moa_loop.py` / `moa_trace.py` / `run_agent.py` to get
per-proposer wall-clock `duration_s` and provider `stats` (tokens/sec, TTFT
from local servers) out of each MoA reference call, plus a metrics-lite
record per MoA turn written **independent of `moa.save_traces`** — preset
editors (`hermes moa`, dashboard MoA panel) rewrite the `moa:` block and drop
`save_traces`, which used to silently kill proposer observability. What we'd
actually want as a plugin: an observer hook (or lifecycle event) emitted per
completed MoA reference with usage/duration/stats, guaranteed independent of
trace-saving config. Observer-only, per ground rule 3 — we don't need any
mutation of the MoA loop. That covers our whole patch; the aggregator side is
already covered by `post_api_request`.

**3. Turn-error surfacing → #64231 batch (#56720 `turn_failed`, #58524 `classify_api_error`)**

When a turn fails, `tui_gateway/server.py` / `compute_host.py` emit a bare
`request failed` while the classified detail (provider, base_url, model, HTTP
status, fallback chain) only reaches the log file. We patch those frames to
carry the classified summary, and built a small dashboard that persists
`api_request_error` hook payloads into sqlite. As plugins: a `turn_failed`
observer with the classified error in the payload would cover the
persistence half, and a `classify_api_error`-style seam would let a plugin
own the enrichment without touching the gateway. Both observer-side; no
delivery-path mutation needed. Note the `api_request_error`
hook + plugin route mounting already got us most of the way — the gap is
specifically the TUI/gateway error-frame path.

Separately, we hold several plain bugfixes that aren't plugin-interface items
(per the tracker's own routing of real bugs to the normal lane) — a per-turn
`.env` reload clobbering terminal config in `gateway/run.py`, a
leading-user-turn invariant for resumed/compacted lineages, a no-progress
tool-loop guard gap, websocket keepalive for dead peers, and an NVIDIA NIM
`reasoning`-param 400. Explicitly **not** asking for tracker homes for those
— I'll send them as individual small PRs rather than expand this comment.

Fork delta is fully documented with per-patch verification notes if any
maintainer wants the gory details on the three items above. Verbatim patch
excerpts from that record (scrubbed of internal infra references):
https://gist.github.com/c-pompa/35d3e58b1a1e377bcaf2ad02579c4714

Happy to open the salvage PR for item 1 against #64178, split this into
per-item comments, or adjust the framing to whatever the maintainers prefer.

---

## Addendum 2026-08-03 — two more salvage PRs, opened (observer-hooks family)

Both implement notify-only observer surfaces, consistent with ground rule 3
(no mutation of agent flow), and both are already running downstream against
our metrics pipeline:

- **#78042** `feat(hooks): add session/host fields to outbound webhook payload`
  — additive `parent_session_id` / `session_title` / `host` on every
  `hooks.outbound` delivery. Motivation: a receiver collecting webhooks from
  multiple machines/sessions cannot attribute events today;
  `parent_session_id` was already in `_TOP_LEVEL_PAYLOAD_KEYS` but never
  emitted. `host` overridable via `hooks.outbound_host_label`.
- **#78043** `feat(hooks): add guardrail_block / guardrail_halt lifecycle
  events` — the tool-loop guardrail controller's stop decisions are
  process-internal today; external tooling must tail `agent.log`. Emits
  observer events (tool_name, decision code, streak count) from a single
  funnel covering all stop-decision sites.

If either fits the official hook-surface shape better under a different name
or kwargs layout, happy to reshape on the PRs.
