"""Tests for hermes_cli.observability.api_error_logs (agent.log tail source)."""

from pathlib import Path

import pytest

from hermes_cli.observability import api_error_logs


# Real line shapes from ~/.hermes/logs/agent.log (2026-08-02).
FAILED_401 = (
    "2026-08-02 14:55:31,466 WARNING [20260802_145508_8324f7] "
    "agent.conversation_loop: API call failed (attempt 1/3) "
    "error_type=AuthenticationError thread=Thread-19 (run):13036318720 "
    "provider=model-router base_url=http://127.0.0.1:8867/v1 model=hermes/main "
    "summary=HTTP 401: {"
)
FAILED_CONN = (
    "2026-08-01 19:26:13,762 WARNING [20260801_025055_eb38d2] "
    "agent.conversation_loop: API call failed (attempt 2/3) "
    "error_type=APIConnectionError thread=Thread-161 (run):13086797824 "
    "provider=lmstudio base_url=http://127.0.0.1:8867/v1 model=hermes/main "
    "summary=Connection error."
)
NON_RETRYABLE = (
    "2026-08-02 14:55:31,489 ERROR [20260802_145508_8324f7] "
    "agent.conversation_loop: Non-retryable client error: Error code: 401 - "
    "{'error': 'unauthorized'}"
)
FALLBACK = (
    "2026-08-02 14:55:10,911 INFO [20260802_145508_8324f7] "
    "agent.chat_completion_helpers: Fallback activated: hermes/main → "
    "qwen3.6-35b-a3b-uncensored-genesis-hermes-v5 (lmstudio)"
)
MALFORMED = [
    # Mentions the marker but has no parseable fields.
    "2026-08-02 14:55:31,466 WARNING agent.conversation_loop: API call failed",
    # Truncated mid-line (as a sliced tail window can produce).
    "error_type=BadRequestError provider=moa base_",
    # Ordinary noise.
    "2026-08-02 14:55:32,000 INFO [abc] agent.tools: tool call ok",
    "",
]


@pytest.fixture()
def log_file(tmp_path):
    path = tmp_path / "agent.log"
    path.write_text(
        "\n".join([FAILED_CONN, FALLBACK, FAILED_401, NON_RETRYABLE, *MALFORMED])
        + "\n"
    )
    return path


def test_parses_api_call_failed(log_file):
    rows = api_error_logs.list_errors(log_path=log_file)
    failed = [row for row in rows if row["error_type"] == "AuthenticationError"]
    assert len(failed) == 1
    row = failed[0]
    assert row["ts"] == "2026-08-02T14:55:31+00:00"
    assert row["session_id"] == "20260802_145508_8324f7"
    assert row["provider"] == "model-router"
    assert row["base_url"] == "http://127.0.0.1:8867/v1"
    assert row["model"] == "hermes/main"
    assert row["status_code"] == 401
    assert row["retryable"] is True
    assert row["retry_count"] == 1
    assert row["max_retries"] == 3
    assert row["error_message"] == "HTTP 401: {"


def test_parses_non_retryable(log_file):
    rows = api_error_logs.list_errors(log_path=log_file)
    row = next(r for r in rows if r["error_type"] == "NonRetryableClientError")
    assert row["status_code"] == 401
    assert row["retryable"] is False
    assert row["reason"] == "non_retryable"
    assert "unauthorized" in row["error_message"]


def test_parses_fallback_activated(log_file):
    rows = api_error_logs.list_errors(log_path=log_file)
    row = next(r for r in rows if r["error_type"] == "FallbackActivated")
    assert row["provider"] == "lmstudio"
    assert row["model"] == "qwen3.6-35b-a3b-uncensored-genesis-hermes-v5"
    assert row["reason"] == "fallback_activated"
    assert "hermes/main" in row["error_message"]


def test_malformed_lines_skipped(log_file):
    rows = api_error_logs.list_errors(log_path=log_file)
    # Only the four well-formed records survive.
    assert len(rows) == 4


def test_newest_first_ordering(log_file):
    rows = api_error_logs.list_errors(log_path=log_file)
    timestamps = [row["ts"] for row in rows]
    assert timestamps == sorted(timestamps, reverse=True)


def test_filters(log_file):
    assert len(api_error_logs.list_errors(log_path=log_file, provider="lmstudio")) == 2
    rows = api_error_logs.list_errors(log_path=log_file, status_code=401)
    assert len(rows) == 2
    rows = api_error_logs.list_errors(
        log_path=log_file, session_id="20260801_025055_eb38d2"
    )
    assert len(rows) == 1
    rows = api_error_logs.list_errors(
        log_path=log_file, since_ts="2026-08-02T00:00:00+00:00"
    )
    assert len(rows) == 3


def test_summary(log_file):
    result = api_error_logs.summary(log_path=log_file)
    assert result["total"] == 4
    assert result["terminal"] == 1
    assert result["by_provider"]["lmstudio"] == 2
    assert result["by_status_code"]["401"] == 2
    assert result["by_error_type"]["FallbackActivated"] == 1


def test_missing_log_returns_empty(tmp_path):
    assert api_error_logs.list_errors(log_path=tmp_path / "nope.log") == []


def test_tail_window_skips_sliced_first_line(tmp_path):
    path = tmp_path / "agent.log"
    filler = "x" * 4096 + "\n"
    path.write_text(filler + FAILED_401 + "\n")
    rows = api_error_logs.list_errors(log_path=path, tail_bytes=len(FAILED_401) + 20)
    assert len(rows) == 1
    assert rows[0]["status_code"] == 401
