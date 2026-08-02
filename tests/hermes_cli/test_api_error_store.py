"""Tests for hermes_cli.observability.api_error_store (sqlite error store)."""

import time
from datetime import datetime, timedelta, timezone

import pytest

from hermes_cli.observability import api_error_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    db = tmp_path / "api_errors.db"
    monkeypatch.setattr(api_error_store, "_db_path", lambda: db)
    return api_error_store


def _payload(**overrides):
    payload = {
        "session_id": "20260802_145508_8324f7",
        "turn_id": "turn-1",
        "platform": "cli",
        "provider": "model-router",
        "base_url": "http://127.0.0.1:8867/v1",
        "model": "hermes/main",
        "status_code": 401,
        "reason": "auth",
        "retryable": False,
        "retry_count": 1,
        "max_retries": 3,
        "ended_at": time.time(),
        "error": {"type": "AuthenticationError", "message": "HTTP 401: unauthorized"},
        # Must never be persisted.
        "request": {"messages": [{"role": "user", "content": "secret-payload"}]},
    }
    payload.update(overrides)
    return payload


def test_record_and_list_roundtrip(store):
    row_id = store.record_error(_payload())
    assert row_id

    rows = store.list_errors()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == row_id
    assert row["session_id"] == "20260802_145508_8324f7"
    assert row["turn_id"] == "turn-1"
    assert row["platform"] == "cli"
    assert row["provider"] == "model-router"
    assert row["base_url"] == "http://127.0.0.1:8867/v1"
    assert row["model"] == "hermes/main"
    assert row["status_code"] == 401
    assert row["reason"] == "auth"
    assert row["retryable"] is False
    assert row["retry_count"] == 1
    assert row["max_retries"] == 3
    assert row["error_type"] == "AuthenticationError"
    assert "401" in row["error_message"]
    # The hook's request payload is never persisted.
    assert "request" not in row
    assert "secret-payload" not in row["error_message"]


def test_list_newest_first_and_limit(store):
    for index in range(5):
        store.record_error(_payload(turn_id=f"turn-{index}"))
    rows = store.list_errors(limit=3)
    assert [row["turn_id"] for row in rows] == ["turn-4", "turn-3", "turn-2"]


def test_list_filters(store):
    store.record_error(_payload(provider="lmstudio", status_code=400))
    store.record_error(_payload(provider="model-router", status_code=401))
    store.record_error(
        _payload(provider="model-router", status_code=401, session_id="other")
    )

    assert len(store.list_errors(provider="model-router")) == 2
    assert len(store.list_errors(status_code=400)) == 1
    assert len(store.list_errors(session_id="other")) == 1
    assert len(store.list_errors(provider="model-router", status_code=400)) == 0


def test_list_since_ts(store):
    store.record_error(_payload())
    future = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert store.list_errors(since_ts=future) == []
    assert len(store.list_errors(since_ts=past)) == 1


def test_error_message_truncated_and_redacted(store):
    secret = "sk-abcdef0123456789abcdef0123456789"
    long_message = f"prefix {secret} " + "x" * 5000
    store.record_error(_payload(error={"type": "E", "message": long_message}))
    row = store.list_errors()[0]
    assert len(row["error_message"]) <= 2000
    assert secret not in row["error_message"]


def test_summary_aggregates(store):
    store.record_error(_payload(provider="a", status_code=401, retryable=False))
    store.record_error(_payload(provider="a", status_code=500, retryable=True))
    store.record_error(
        _payload(
            provider="b",
            status_code=None,
            retryable=None,
            error={"type": "APIConnectionError", "message": "Connection error."},
        )
    )
    result = store.summary()
    assert result["total"] == 3
    assert result["terminal"] == 1
    assert result["by_provider"] == {"a": 2, "b": 1}
    assert result["by_status_code"] == {"401": 1, "500": 1, "none": 1}
    assert result["by_error_type"]["APIConnectionError"] == 1


def test_prune_by_max_rows(store):
    for index in range(5):
        store.record_error(_payload(turn_id=f"turn-{index}"))
    deleted = store.prune(older_than_days=3650, max_rows=2)
    assert deleted == 3
    rows = store.list_errors()
    assert [row["turn_id"] for row in rows] == ["turn-4", "turn-3"]


def test_prune_on_insert_drops_old_rows(store):
    old_epoch = time.time() - 10 * 86400
    store.record_error(_payload(turn_id="old", ended_at=old_epoch))
    # The insert-time prune (default: 7 days) removed the old row already.
    assert store.list_errors() == []
    store.record_error(_payload(turn_id="fresh"))
    assert [row["turn_id"] for row in store.list_errors()] == ["fresh"]


def test_missing_error_block_tolerated(store):
    row_id = store.record_error({"provider": "p", "ended_at": time.time()})
    assert row_id
    row = store.list_errors()[0]
    assert row["error_type"] == ""
    assert row["error_message"] == ""
    assert row["retryable"] is None
