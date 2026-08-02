"""API error dashboard routes (/api/errors*).

Serves failed-API-attempt rows from either observability source:

* ``store`` (default) — the sqlite event store written by the
  ``api_request_error`` hook consumer
  (:mod:`hermes_cli.observability.api_error_store`); structured, per-session
  linkable, cheap reads.
* ``logs`` — the ``~/.hermes/logs/agent.log`` tail parser
  (:mod:`hermes_cli.observability.api_error_logs`); works retroactively but
  has fewer fields, is coupled to log wording, and re-parses on every poll.

The default source comes from ``observability.errors_source`` in config.yaml
(default ``store``); an explicit ``?source=store|logs`` query param overrides
it per request (the user-facing toggle). Auth is automatic via the existing
``/api/*`` middleware in web_server.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

_log = logging.getLogger("hermes_cli.web_server")

router = APIRouter()

_SOURCES = ("store", "logs")
_LOGS_CONS_NOTE = (
    "Logs mode parses the agent.log tail on every poll — more I/O, fewer "
    "fields (no turn/platform/duration), and coupled to the log wording: it "
    "breaks if upstream rewords the error lines. Prefer Store mode."
)


def _default_source() -> str:
    try:
        from hermes_cli.config import read_raw_config_readonly

        config = read_raw_config_readonly() or {}
    except Exception:
        return "store"
    observability = config.get("observability") if isinstance(config, dict) else None
    value = (
        observability.get("errors_source") if isinstance(observability, dict) else None
    )
    return value if value in _SOURCES else "store"


def _resolve_source(source: Optional[str]) -> str:
    if source is None:
        return _default_source()
    if source not in _SOURCES:
        raise HTTPException(
            status_code=400,
            detail="source must be one of: store, logs",
        )
    return source


def _since_ts(since_minutes: Optional[float]) -> Optional[str]:
    if since_minutes is None:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(0.0, since_minutes))
    return cutoff.isoformat()


def _backend(source: str):
    if source == "logs":
        from hermes_cli.observability import api_error_logs

        return api_error_logs
    from hermes_cli.observability import api_error_store

    return api_error_store


@router.get("/api/errors")
def get_errors(
    limit: int = 100,
    since_minutes: Optional[float] = None,
    provider: Optional[str] = None,
    session_id: Optional[str] = None,
    status_code: Optional[int] = None,
    source: Optional[str] = None,
):
    """List failed API attempts, newest first, from the selected source."""
    resolved = _resolve_source(source)
    backend = _backend(resolved)
    try:
        rows = backend.list_errors(
            limit=limit,
            since_ts=_since_ts(since_minutes),
            provider=provider or None,
            session_id=session_id or None,
            status_code=status_code,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _log.warning("api/errors list failed (source=%s): %s", resolved, exc)
        raise HTTPException(status_code=500, detail=f"errors source failed: {exc}")
    return {"errors": rows, "source": resolved}


@router.get("/api/errors/summary")
def get_errors_summary(
    since_minutes: float = 1440,
    source: Optional[str] = None,
):
    """Aggregate error counts (by provider/status/type) over the window."""
    resolved = _resolve_source(source)
    backend = _backend(resolved)
    since_ts = _since_ts(since_minutes)
    try:
        result: Dict[str, Any] = backend.summary(since_ts=since_ts)
    except Exception as exc:
        _log.warning("api/errors summary failed (source=%s): %s", resolved, exc)
        raise HTTPException(status_code=500, detail=f"errors source failed: {exc}")
    result["source"] = resolved
    result["since_ts"] = since_ts
    return result


@router.get("/api/errors/meta")
def get_errors_meta():
    """Active default source + the honest cons note for logs mode."""
    return {
        "default_source": _default_source(),
        "sources": list(_SOURCES),
        "logs_cons_note": _LOGS_CONS_NOTE,
    }
