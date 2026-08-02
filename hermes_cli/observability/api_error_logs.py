"""Log-tail API error source (dashboard /errors source B).

Parses the tail of ``~/.hermes/logs/agent.log`` for the error lines the agent
already emits and returns row dicts in the SAME shape as
:mod:`hermes_cli.observability.api_error_store` ``list_errors`` rows, so the
``/api/errors`` route can serve either source interchangeably.

Recognized lines (see ``agent/conversation_loop.py`` /
``agent/chat_completion_helpers.py``)::

    ... WARNING [session_id] agent.conversation_loop: API call failed (attempt n/m) error_type=... thread=... provider=... base_url=... model=... summary=...
    ... ERROR [session_id] agent.conversation_loop: Non-retryable client error: Error code: 401 - {...}
    ... INFO [session_id] agent.chat_completion_helpers: Fallback activated: X → Y (provider)

Trade-offs vs the store source: works retroactively on old logs and even when
the hook consumer missed a process, but is coupled to the log wording (breaks
if upstream rewords these lines), only has the fields present in the log
text, and re-parses the log tail on every poll (more I/O). Reads are bounded:
only the last ~2 MiB of the log is scanned, and unparseable lines are skipped.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

_TAIL_BYTES = 2 * 1024 * 1024
_MAX_ROWS = 1000

_TS_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}\s")
_SESSION_RE = re.compile(r"\[([^\]]+)\]")

_API_CALL_FAILED_RE = re.compile(
    r"API call failed \(attempt (\d+)/(\d+)\)"
    r" error_type=(\S+)"
    r"(?:.*?)\bprovider=(\S+)"
    r" base_url=(\S+)"
    r" model=(\S+)"
    r" summary=(.*)$"
)
_NON_RETRYABLE_RE = re.compile(r"Non-retryable client error:\s*(.*)$")
_ERROR_CODE_RE = re.compile(r"Error code:\s*(\d{3})\s*-\s*(.*)$")
_FALLBACK_RE = re.compile(r"Fallback activated:\s*(.+?)\s*→\s*(.+?)\s*\(([^)]*)\)\s*$")
_HTTP_STATUS_RE = re.compile(r"HTTP (\d{3})")


def _log_path() -> Path:
    return get_hermes_home() / "logs" / "agent.log"


def _parse_ts(line: str) -> Optional[str]:
    match = _TS_PREFIX_RE.match(line)
    if not match:
        return None
    try:
        parsed = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat()


def _parse_session_id(line: str) -> str:
    match = _SESSION_RE.search(line)
    return match.group(1) if match else ""


def _row(
    *,
    ts: Optional[str],
    session_id: str = "",
    provider: str = "",
    base_url: str = "",
    model: str = "",
    status_code: Optional[int] = None,
    reason: str = "",
    retryable: Optional[bool] = None,
    retry_count: Optional[int] = None,
    max_retries: Optional[int] = None,
    error_type: str = "",
    error_message: str = "",
) -> Dict[str, Any]:
    """Row shape identical to api_error_store.list_errors rows."""
    return {
        "id": None,
        "ts": ts,
        "session_id": session_id,
        "turn_id": "",
        "platform": "",
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "status_code": status_code,
        "reason": reason,
        "retryable": retryable,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "error_type": error_type,
        "error_message": error_message,
    }


def _parse_line(line: str) -> Optional[Dict[str, Any]]:
    if "API call failed" in line:
        match = _API_CALL_FAILED_RE.search(line)
        if not match:
            return None
        attempt, max_retries, error_type, provider, base_url, model, summary = (
            match.groups()
        )
        status_match = _HTTP_STATUS_RE.search(summary)
        return _row(
            ts=_parse_ts(line),
            session_id=_parse_session_id(line),
            provider=provider,
            base_url=base_url,
            model=model,
            status_code=int(status_match.group(1)) if status_match else None,
            retryable=True,
            retry_count=int(attempt),
            max_retries=int(max_retries),
            error_type=error_type,
            error_message=summary.strip(),
        )
    if "Non-retryable client error" in line:
        match = _NON_RETRYABLE_RE.search(line)
        if not match:
            return None
        detail = match.group(1).strip()
        status_code = None
        code_match = _ERROR_CODE_RE.match(detail)
        if code_match:
            status_code = int(code_match.group(1))
        return _row(
            ts=_parse_ts(line),
            session_id=_parse_session_id(line),
            status_code=status_code,
            reason="non_retryable",
            retryable=False,
            error_type="NonRetryableClientError",
            error_message=detail,
        )
    if "Fallback activated" in line:
        match = _FALLBACK_RE.search(line)
        if not match:
            return None
        from_model, to_model, provider = match.groups()
        return _row(
            ts=_parse_ts(line),
            session_id=_parse_session_id(line),
            provider=provider.strip(),
            model=to_model.strip(),
            reason="fallback_activated",
            error_type="FallbackActivated",
            error_message=f"{from_model.strip()} → {to_model.strip()}",
        )
    return None


def _tail_lines(path: Path, tail_bytes: int) -> List[str]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    try:
        with path.open("rb") as handle:
            if size > tail_bytes:
                handle.seek(-tail_bytes, 2)
            data = handle.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if size > tail_bytes and lines:
        # The first line of a tail window is likely sliced mid-record.
        lines = lines[1:]
    return lines


def list_errors(
    *,
    limit: int = 100,
    since_ts: Optional[str] = None,
    provider: Optional[str] = None,
    session_id: Optional[str] = None,
    status_code: Optional[int] = None,
    log_path: Optional[Path] = None,
    tail_bytes: int = _TAIL_BYTES,
) -> List[Dict[str, Any]]:
    """Parse the log tail and return error rows, newest first.

    Filters match the store's ``list_errors`` semantics; ``since_ts`` compares
    against the ISO timestamps parsed from log line prefixes (rows without a
    parseable timestamp are kept only when no ``since_ts`` filter is set).
    """
    path = Path(log_path) if log_path is not None else _log_path()
    rows: List[Dict[str, Any]] = []
    for line in _tail_lines(path, tail_bytes):
        row = _parse_line(line)
        if row is None:
            continue
        if since_ts and (row["ts"] is None or row["ts"] < since_ts):
            continue
        if provider and row["provider"] != provider:
            continue
        if session_id and row["session_id"] != session_id:
            continue
        if status_code is not None and row["status_code"] != int(status_code):
            continue
        rows.append(row)
    rows.reverse()  # log order is oldest-first; store rows are newest-first
    limit = max(1, min(int(limit or 100), _MAX_ROWS))
    return rows[:limit]


def summary(since_ts: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    """Aggregate counts over parsed rows (same shape as the store summary)."""
    rows = list_errors(limit=_MAX_ROWS, since_ts=since_ts, **kwargs)
    by_provider: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    grouped: Dict[tuple, int] = {}
    terminal = 0
    for row in rows:
        by_provider[row["provider"] or "unknown"] = (
            by_provider.get(row["provider"] or "unknown", 0) + 1
        )
        status_key = (
            str(row["status_code"]) if row["status_code"] is not None else "none"
        )
        by_status[status_key] = by_status.get(status_key, 0) + 1
        error_type = row["error_type"] or "unknown"
        by_type[error_type] = by_type.get(error_type, 0) + 1
        key = (row["provider"], row["status_code"], row.get("reason"))
        grouped[key] = grouped.get(key, 0) + 1
        if row["retryable"] is False:
            terminal += 1
    return {
        "total": len(rows),
        "terminal": terminal,
        "by_provider": by_provider,
        "by_status_code": by_status,
        "by_error_type": by_type,
        # Dashboard chips contract: [{provider, status_code, reason, count}]
        "groups": [
            {"provider": p, "status_code": s, "reason": r, "count": c}
            for (p, s, r), c in sorted(grouped.items(), key=lambda kv: -kv[1])
        ],
    }
