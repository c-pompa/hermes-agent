"""Tests for the api_request_error hook consumer wiring.

A synthetic ``api_request_error`` through
``hermes_cli.observability.observe_lifecycle`` must persist a store row, and a
raising store must be swallowed by the dispatcher's ``_safe_observe`` guard so
a broken consumer can never break a turn.
"""

import time

import pytest

from hermes_cli import observability
from hermes_cli.observability import api_error_store


def _hook_payload():
    return {
        "task_id": "task-1",
        "turn_id": "turn-1",
        "api_request_id": "req-1",
        "session_id": "sess-hook",
        "platform": "cli",
        "model": "hermes/main",
        "provider": "model-router",
        "base_url": "http://127.0.0.1:8867/v1",
        "api_mode": "chat_completions",
        "api_call_count": 1,
        "api_duration": 0.5,
        "started_at": time.time() - 0.5,
        "ended_at": time.time(),
        "status_code": 401,
        "retry_count": 1,
        "max_retries": 3,
        "retryable": False,
        "reason": "auth",
        "error": {"type": "AuthenticationError", "message": "HTTP 401: unauthorized"},
        "request": {"messages": [{"role": "user", "content": "do-not-persist"}]},
    }


def test_hook_persists_row(tmp_path, monkeypatch):
    db = tmp_path / "api_errors.db"
    monkeypatch.setattr(api_error_store, "_db_path", lambda: db)

    observability.observe_lifecycle("api_request_error", **_hook_payload())

    rows = api_error_store.list_errors()
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "sess-hook"
    assert row["provider"] == "model-router"
    assert row["status_code"] == 401
    assert row["retryable"] is False
    assert row["error_type"] == "AuthenticationError"


def test_handles_hook_advertised():
    assert observability.handles_hook("api_request_error") is True
    assert observability.handles_hook("some_other_hook") is False


def test_raising_store_is_swallowed(tmp_path, monkeypatch):
    def _boom(payload):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(api_error_store, "record_error", _boom)

    # Must not raise — _safe_observe fail-isolates the consumer.
    observability.observe_lifecycle("api_request_error", **_hook_payload())


def test_unhandled_hook_is_a_noop(tmp_path, monkeypatch):
    db = tmp_path / "api_errors.db"
    monkeypatch.setattr(api_error_store, "_db_path", lambda: db)

    observability.observe_lifecycle("post_tool_call", **_hook_payload())

    assert api_error_store.list_errors() == []
