"""SQLite-backed API error event store (dashboard /errors source A).

One row per failed API attempt, written by whichever process ran the turn
(gateway / serve / CLI / cron) via the ``api_request_error`` lifecycle hook
and read back by the dashboard's ``/api/errors`` route.

Multi-process safety copies the proven ``agent/verification_evidence.py``
pattern wholesale: ``hermes_state.apply_wal_with_fallback`` +
``PRAGMA busy_timeout=5000`` + an always-close ``_transaction`` (their comment
cites the connection-leak bug #69567 the pattern fixed).

Privacy: the hook payload's ``request`` field is NEVER persisted — only error
metadata — and ``error_message`` is truncated and run through secret redaction
before insert so a provider echoing request headers can't leak a key into the
db or the UI.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from hermes_constants import get_hermes_home


_DB_LOCK = threading.Lock()
_MAX_ERROR_MESSAGE_CHARS = 2000
_DEFAULT_PRUNE_AGE_DAYS = 7
_DEFAULT_MAX_ROWS = 5000
_SCHEMA_VERSION = 1

# Fallback redaction when agent.redact is unavailable: bearer/token-shaped
# secrets (nvapi-..., sk-..., long hex/JWT-ish runs after "Bearer").
_FALLBACK_SECRET_RE = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"
    r"|(nvapi-[A-Za-z0-9._\-]{8,})"
    r"|(sk-[A-Za-z0-9._\-]{8,})"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    return get_hermes_home() / "api_errors.db"


def _connect() -> sqlite3.Connection:
    from hermes_state import apply_wal_with_fallback

    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        apply_wal_with_fallback(conn, db_label="api_errors.db")
        conn.execute("PRAGMA busy_timeout=5000")
        _ensure_schema(conn)
    except Exception:
        # A PRAGMA/DDL failure after a successful connect() must not leak the
        # just-opened connection back to the caller.
        conn.close()
        raise
    return conn


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit/rollback on exit, and ALWAYS close it.

    ``sqlite3.Connection.__enter__``/``__exit__`` only commit or roll back the
    transaction; they do not close the connection. Using ``with _connect()``
    alone therefore leaks a connection — and its WAL/SHM file descriptors — on
    every call, deferring the close to the garbage collector, which over a
    long-running process can exhaust ``RLIMIT_NOFILE`` (the cron-ledger sibling
    of this bug was #69567 / PR #69594).
    """
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            turn_id TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            base_url TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            status_code INTEGER,
            reason TEXT NOT NULL DEFAULT '',
            retryable INTEGER,
            retry_count INTEGER,
            max_retries INTEGER,
            error_type TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_api_errors_ts
        ON api_errors(ts DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_api_errors_session
        ON api_errors(session_id, id DESC)
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(_SCHEMA_VERSION),),
    )
    conn.commit()


def _redact(text: str) -> str:
    """Strip bearer/token-shaped secrets from provider error text."""
    if not text:
        return ""
    try:
        from agent.redact import redact_sensitive_text

        # force=True: this is a persistence boundary — redaction must apply
        # even if the user disabled log redaction in config.
        return redact_sensitive_text(text, force=True)
    except Exception:
        return _FALLBACK_SECRET_RE.sub("«redacted-secret»", text)


def _clean_message(value: Any) -> str:
    text = str(value or "")
    if len(text) > _MAX_ERROR_MESSAGE_CHARS:
        text = text[:_MAX_ERROR_MESSAGE_CHARS]
    return _redact(text)


def _iso_from_epoch(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return _utc_now()


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def record_error(payload: Dict[str, Any]) -> Optional[int]:
    """Persist one ``api_request_error`` hook payload. Returns the row id.

    Only error metadata is read from ``payload`` — the ``request`` field is
    deliberately never touched, so request bodies/headers cannot reach the db.
    """
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        error = {}
    retryable = payload.get("retryable")
    row = (
        _iso_from_epoch(payload.get("ended_at")),
        str(payload.get("session_id") or ""),
        str(payload.get("turn_id") or ""),
        str(payload.get("platform") or ""),
        str(payload.get("provider") or ""),
        str(payload.get("base_url") or ""),
        str(payload.get("model") or ""),
        _as_int(payload.get("status_code")),
        str(payload.get("reason") or ""),
        None if retryable is None else (1 if retryable else 0),
        _as_int(payload.get("retry_count")),
        _as_int(payload.get("max_retries")),
        str(error.get("type") or payload.get("error_type") or ""),
        _clean_message(error.get("message") or payload.get("error_message")),
    )
    with _DB_LOCK:
        with _transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO api_errors (
                    ts, session_id, turn_id, platform, provider, base_url,
                    model, status_code, reason, retryable, retry_count,
                    max_retries, error_type, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            row_id = int(cur.lastrowid or 0)
            _prune_locked(conn)
    return row_id


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    retryable = row["retryable"]
    return {
        "id": row["id"],
        "ts": row["ts"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "platform": row["platform"],
        "provider": row["provider"],
        "base_url": row["base_url"],
        "model": row["model"],
        "status_code": row["status_code"],
        "reason": row["reason"],
        "retryable": None if retryable is None else bool(retryable),
        "retry_count": row["retry_count"],
        "max_retries": row["max_retries"],
        "error_type": row["error_type"],
        "error_message": row["error_message"],
    }


def list_errors(
    *,
    limit: int = 100,
    since_ts: Optional[str] = None,
    provider: Optional[str] = None,
    session_id: Optional[str] = None,
    status_code: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return recent error rows, newest first, with optional filters."""
    clauses: List[str] = []
    params: List[Any] = []
    if since_ts:
        clauses.append("ts >= ?")
        params.append(since_ts)
    if provider:
        clauses.append("provider = ?")
        params.append(provider)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if status_code is not None:
        clauses.append("status_code = ?")
        params.append(int(status_code))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, min(int(limit or 100), 1000))
    with _transaction() as conn:
        rows = conn.execute(
            f"SELECT * FROM api_errors {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def summary(since_ts: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate counts over the window: total, by provider/status/type."""
    clauses = ""
    params: tuple = ()
    if since_ts:
        clauses = "WHERE ts >= ?"
        params = (since_ts,)
    with _transaction() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM api_errors {clauses}", params
        ).fetchone()["c"]
        terminal = conn.execute(
            f"SELECT COUNT(*) AS c FROM api_errors {clauses}"
            f"{' AND' if clauses else 'WHERE'} retryable = 0",
            params,
        ).fetchone()["c"]
        by_provider = conn.execute(
            f"SELECT provider, COUNT(*) AS c FROM api_errors {clauses}"
            " GROUP BY provider ORDER BY c DESC",
            params,
        ).fetchall()
        by_status = conn.execute(
            f"SELECT status_code, COUNT(*) AS c FROM api_errors {clauses}"
            " GROUP BY status_code ORDER BY c DESC",
            params,
        ).fetchall()
        by_type = conn.execute(
            f"SELECT error_type, COUNT(*) AS c FROM api_errors {clauses}"
            " GROUP BY error_type ORDER BY c DESC",
            params,
        ).fetchall()
        grouped = conn.execute(
            f"SELECT provider, status_code, reason, COUNT(*) AS c"
            f" FROM api_errors {clauses}"
            " GROUP BY provider, status_code, reason ORDER BY c DESC",
            params,
        ).fetchall()
    return {
        "total": total,
        "terminal": terminal,
        "by_provider": {row["provider"] or "unknown": row["c"] for row in by_provider},
        "by_status_code": {
            str(row["status_code"]) if row["status_code"] is not None else "none": row["c"]
            for row in by_status
        },
        "by_error_type": {row["error_type"] or "unknown": row["c"] for row in by_type},
        # Dashboard chips contract: [{provider, status_code, reason, count}]
        "groups": [
            {
                "provider": row["provider"],
                "status_code": row["status_code"],
                "reason": row["reason"],
                "count": row["c"],
            }
            for row in grouped
        ],
    }


def _prune_locked(
    conn: sqlite3.Connection,
    *,
    older_than_days: int = _DEFAULT_PRUNE_AGE_DAYS,
    max_rows: int = _DEFAULT_MAX_ROWS,
) -> int:
    """Prune inside an open transaction (caller holds _DB_LOCK)."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=older_than_days)
    ).isoformat()
    deleted = 0
    cur = conn.execute("DELETE FROM api_errors WHERE ts < ?", (cutoff,))
    deleted += cur.rowcount if cur.rowcount is not None else 0
    cur = conn.execute(
        """
        DELETE FROM api_errors WHERE id NOT IN (
            SELECT id FROM api_errors ORDER BY id DESC LIMIT ?
        )
        """,
        (max_rows,),
    )
    deleted += cur.rowcount if cur.rowcount is not None else 0
    return deleted


def prune(
    older_than_days: int = _DEFAULT_PRUNE_AGE_DAYS,
    max_rows: int = _DEFAULT_MAX_ROWS,
) -> int:
    """Drop rows older than ``older_than_days`` and cap the table at ``max_rows``."""
    with _DB_LOCK:
        with _transaction() as conn:
            return _prune_locked(
                conn, older_than_days=older_than_days, max_rows=max_rows
            )
