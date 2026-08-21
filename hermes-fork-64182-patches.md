# Fork patch excerpts supporting the #64182 registration comment

Excerpts from our fork's `FORK_CHANGELOG.md` (the per-patch verification
record we re-apply after each upstream sync). These are the three patches
registered in the tracker comment. Internal infrastructure references have
been scrubbed; everything else is verbatim.

---

## Item 1 — Shell-hook registration for dashboard + TUI-worker processes (2026-07-12)

`hermes_cli/web_server.py` (`start_server`) + `tui_gateway/slash_worker.py`
(`main`). Upstream only registers declarative shell hooks in the CLI agent
commands and `gateway run` entry points; dashboard chat sessions and TUI
slash workers run full agent turns WITHOUT hooks, so
`post_api_request`/`subagent_stop` observability silently never fires for
them (our metrics pipeline showed only cron/CLI traffic). Both now call
`register_from_config(load_config(), accept_hooks=False)` at startup,
mirroring `gateway/run.py` (consent via `hooks_auto_accept`/env).

---

## Item 2 — MoA per-reference call timing + provider stats passthrough (2026-07-10/12)

`agent/moa_loop.py` + `agent/moa_trace.py` + `run_agent.py`. `_RefAccounting`
gains `duration_s` and `stats` slots, `_run_reference()` wraps its `call_llm`
in a `time.monotonic()` timer and captures a non-empty response-root `stats`
dict (local inference servers report tokens/sec, TTFT, speculative-draft
counts), and `moa_trace._slot_trace()` writes both into each reference's
trace record. `run_agent._usage_summary_for_api_request_hook()` likewise
attaches a non-empty `response.stats` as `summary["stats"]` so the
`post_api_request` hook payload carries it. With `moa.save_traces: true` this
gives per-proposer wall-clock duration (→ tokens/sec) per MoA turn in
`~/.hermes/moa-traces/<session_id>.jsonl`. The aggregator's acting call needs
no patch — it is already timed by the `post_api_request` hook
(`api_duration`). Also (2026-07-12): `moa_trace._save_moa_metrics()` writes a
metrics-lite record (per-proposer usage/duration/stats, NO message bodies) to
`<hermes_home>/metrics/moa-refs.jsonl` on EVERY MoA turn, **independent of
`moa.save_traces`** — preset editors (`hermes moa` / dashboard MoA panel)
rewrite the `moa:` block and drop `save_traces`, which used to silently kill
proposer observability. Small, additive.

Port note (2026-07-20): `_run_reference()` was refactored upstream (advisory
system prompt + cache-control decoration); the `time.monotonic()` wrap now
starts before the `try:` (covers failures) and the success/failure
`_RefAccounting` constructors both take `duration_s`. `moa_trace.py` was
untouched upstream → applied clean.

---

## Item 3 — API error surfacing (2026-08-02)

Turns that failed showed a bare `request failed` in the desktop/TUI while the
rich detail (provider, base_url, model, HTTP status, summary, fallback chain)
only reached `logs/agent.log`. Parts:

- NEW `hermes_cli/observability/api_error_store.py` — sqlite
  `~/.hermes/api_errors.db` (WAL/busy_timeout/always-close pattern copied
  from `agent/verification_evidence.py`; `agent.redact` on messages; the
  hook's `request` payload is never persisted).
- NEW `hermes_cli/observability/api_errors.py` — consumer of the existing
  `api_request_error` lifecycle hook; `hermes_cli/observability/__init__.py`
  wires it via the codebase's own `_safe_observe` (3 lines).
- NEW `hermes_cli/observability/api_error_logs.py` — alternate log-tail
  source (parses `agent.log` failure lines into the same row shape).
- NEW `hermes_cli/web_routers/errors.py` — `GET /api/errors[/summary|/meta]`;
  one `include_router` in `hermes_cli/web_server.py`. Source toggle:
  `observability.errors_source: store|logs` (default store) or `?source=`.
- NEW dashboard page with Store/Logs toggle, summary chips, filters, 15s poll.
- `tui_gateway/server.py` + `tui_gateway/compute_host.py` — empty/generic
  turn-error frames now carry the classified summary instead of surfacing as
  a bare `request failed`.
- Tests: `test_api_error_store.py`, `test_api_error_logs.py`,
  `test_web_router_errors.py`, `test_observability_api_errors.py`.
