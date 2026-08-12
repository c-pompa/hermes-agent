"""Tests for hermes_cli.web_routers.errors (/api/errors* routes).

Mirrors tests/hermes_cli/test_web_server_session_search.py: handlers are
called directly (auth is middleware-level, covered by the dashboard auth
tests), with the store source seeded into a tmp sqlite db and the logs source
pointed at a fixture log tail.
"""

import time

from datetime import datetime

import pytest
from fastapi import HTTPException

from hermes_cli.observability import api_error_logs, api_error_store
from hermes_cli.web_routers import errors as errors_routes


@pytest.fixture()
def seeded_store(tmp_path, monkeypatch):
    db = tmp_path / "api_errors.db"
    monkeypatch.setattr(api_error_store, "_db_path", lambda: db)
    for index, (provider, status) in enumerate(
        [("model-router", 401), ("lmstudio", 400), ("lmstudio", 400)]
    ):
        api_error_store.record_error(
            {
                "session_id": "sess-1",
                "turn_id": f"turn-{index}",
                "platform": "cli",
                "provider": provider,
                "base_url": "http://127.0.0.1:8867/v1",
                "model": "hermes/main",
                "status_code": status,
                "reason": "test",
                "retryable": status >= 500,
                "retry_count": 1,
                "max_retries": 3,
                "ended_at": time.time(),
                "error": {"type": "APIError", "message": f"boom {index}"},
            }
        )
    return db


@pytest.fixture()
def log_source(tmp_path, monkeypatch):
    path = tmp_path / "agent.log"
    # Fresh timestamp: the summary endpoint filters to its since_minutes
    # window, so a hardcoded date ages out of it (write-time bomb).
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S,000")
    path.write_text(
        f"{ts} WARNING [sess-9] agent.conversation_loop: "
        "API call failed (attempt 1/3) error_type=AuthenticationError "
        "thread=Thread-19 (run):13036318720 provider=model-router "
        "base_url=http://127.0.0.1:8867/v1 model=hermes/main "
        "summary=HTTP 401: {\n"
    )
    monkeypatch.setattr(api_error_logs, "_log_path", lambda: path)
    return path


def test_get_errors_store_source(seeded_store):
    response = errors_routes.get_errors(source="store")
    assert response["source"] == "store"
    assert len(response["errors"]) == 3
    # Newest first.
    assert response["errors"][0]["turn_id"] == "turn-2"


def test_get_errors_store_filters(seeded_store):
    response = errors_routes.get_errors(source="store", provider="lmstudio")
    assert len(response["errors"]) == 2
    response = errors_routes.get_errors(source="store", status_code=401)
    assert len(response["errors"]) == 1
    response = errors_routes.get_errors(source="store", limit=1)
    assert len(response["errors"]) == 1


def test_get_errors_logs_source(log_source):
    response = errors_routes.get_errors(source="logs")
    assert response["source"] == "logs"
    assert len(response["errors"]) == 1
    row = response["errors"][0]
    assert row["provider"] == "model-router"
    assert row["status_code"] == 401


def test_get_errors_invalid_source(seeded_store):
    with pytest.raises(HTTPException) as excinfo:
        errors_routes.get_errors(source="bogus")
    assert excinfo.value.status_code == 400


def test_default_source_from_config(seeded_store, monkeypatch):
    from hermes_cli import config as hermes_config

    monkeypatch.setattr(
        hermes_config,
        "read_raw_config_readonly",
        lambda: {"observability": {"errors_source": "store"}},
    )
    response = errors_routes.get_errors()
    assert response["source"] == "store"
    assert len(response["errors"]) == 3


def test_summary_endpoint(seeded_store):
    result = errors_routes.get_errors_summary(source="store")
    assert result["source"] == "store"
    assert result["total"] == 3
    assert result["by_provider"] == {"lmstudio": 2, "model-router": 1}
    assert result["by_status_code"] == {"400": 2, "401": 1}
    assert result["since_ts"]


def test_summary_logs_source(log_source):
    result = errors_routes.get_errors_summary(source="logs")
    assert result["source"] == "logs"
    assert result["total"] == 1


def test_meta_endpoint(monkeypatch):
    from hermes_cli import config as hermes_config

    monkeypatch.setattr(
        hermes_config,
        "read_raw_config_readonly",
        lambda: {"observability": {"errors_source": "logs"}},
    )
    meta = errors_routes.get_errors_meta()
    assert meta["default_source"] == "logs"
    assert meta["sources"] == ["store", "logs"]
    assert "more I/O" in meta["logs_cons_note"]


def test_meta_default_without_config_key(monkeypatch):
    from hermes_cli import config as hermes_config

    monkeypatch.setattr(hermes_config, "read_raw_config_readonly", lambda: {})
    assert errors_routes.get_errors_meta()["default_source"] == "store"
