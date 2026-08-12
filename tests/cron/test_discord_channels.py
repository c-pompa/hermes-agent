"""Tests for cron/discord_channels.py — per-job Discord results channels.

Covers the channel-name slugifier, the Discord REST provisioning helpers
(mocked at the ``aiohttp.ClientSession`` boundary, same pattern as
tests/tools/test_discord_send_message_caption.py), and the cached channel
directory reader (backed by the per-test HERMES_HOME sandbox from
tests/conftest.py).
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cron.discord_channels import (
    DiscordAuthError,
    DiscordChannelError,
    create_results_channel,
    list_all_text_channels,
    list_guild_text_channels,
    list_guilds,
    list_text_channels,
    slugify_channel_name,
)


# ---------------------------------------------------------------------------
# slugify_channel_name
# ---------------------------------------------------------------------------

class TestSlugifyChannelName:
    def test_mixed_case_and_special_chars(self):
        assert (
            slugify_channel_name("LM Studio Release Review & Upgrade Advisor")
            == "cron-lm-studio-release-review-upgrade-advisor"
        )

    def test_multiple_spaces_collapse_to_single_dash(self):
        assert slugify_channel_name("daily   news   digest") == "cron-daily-news-digest"

    def test_strips_characters_outside_allowed_set(self):
        assert slugify_channel_name("Release Notes: v2.0 (final!)") == "cron-release-notes-v20-final"

    def test_leading_trailing_dashes_stripped(self):
        assert slugify_channel_name(" - spaced - ") == "cron-spaced"

    def test_long_name_truncated_to_discord_limit(self):
        result = slugify_channel_name("x" * 200)
        assert result == f"cron-{'x' * 95}"
        assert len(result) == 100

    def test_already_slugged_name_is_idempotent(self):
        once = slugify_channel_name("Morning Brief")
        assert once == "cron-morning-brief"
        assert slugify_channel_name(once) == once

    def test_underscores_and_digits_kept(self):
        assert slugify_channel_name("gpu_watch_2") == "cron-gpu_watch_2"

    @pytest.mark.parametrize("empty", ["", "   ", "&&& !!!", "•••"])
    def test_empty_after_slugify_falls_back_to_cron_job(self, empty):
        assert slugify_channel_name(empty) == "cron-job"


# ---------------------------------------------------------------------------
# aiohttp boundary fakes
# ---------------------------------------------------------------------------

def _resp(status, payload=None):
    r = AsyncMock()
    r.status = status
    r.json = AsyncMock(return_value=payload)
    return r


def _session_with(responses):
    """Mocked aiohttp.ClientSession; serves *responses* in request order."""
    calls = []
    idx = [0]

    def _request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        r = responses[idx[0]] if idx[0] < len(responses) else responses[-1]
        idx[0] += 1
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=r)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    session = MagicMock()
    session.request = MagicMock(side_effect=_request)
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    return session_ctx, calls


@pytest.fixture
def discord_token(monkeypatch):
    """Bot token present + proxy resolution neutralized."""
    monkeypatch.setattr(
        "agent.secret_scope.get_secret",
        lambda name, default=None: "test-bot-token",
    )
    import gateway.platforms.base as platform_base

    monkeypatch.setattr(platform_base, "resolve_proxy_url", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# list_guilds / create_results_channel
# ---------------------------------------------------------------------------

class TestListGuildTextChannels:
    def test_filters_to_text_channels(self, discord_token):
        session_ctx, _ = _session_with([
            _resp(200, [
                {"id": "c1", "name": "general", "type": 0},
                {"id": "c2", "name": "voice", "type": 2},
                {"id": "c3", "name": "announcements", "type": 5},
                {"id": "c4", "name": "cron-job", "type": 0},
                {"name": "no-id", "type": 0},
            ]),
        ])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            channels = asyncio.run(list_guild_text_channels("g1", "Guild One"))
        assert channels == [
            {"id": "c1", "name": "general", "guild": "Guild One"},
            {"id": "c4", "name": "cron-job", "guild": "Guild One"},
        ]

    def test_401_raises_auth_error(self, discord_token):
        session_ctx, _ = _session_with([_resp(401, {"message": "401: Unauthorized"})])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            with pytest.raises(DiscordAuthError):
                asyncio.run(list_guild_text_channels("g1"))


class TestListAllTextChannels:
    def test_fans_out_across_guilds(self, discord_token):
        session_ctx, calls = _session_with([
            _resp(200, [{"id": "c1", "name": "general", "type": 0}]),
            _resp(200, [{"id": "c2", "name": "dev", "type": 0}]),
        ])
        guilds = [
            {"id": "g1", "name": "One"},
            {"id": "g2", "name": "Two"},
        ]
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            channels = asyncio.run(list_all_text_channels(guilds))
        assert channels == [
            {"id": "c1", "name": "general", "guild": "One"},
            {"id": "c2", "name": "dev", "guild": "Two"},
        ]
        assert [url for _, url, _ in calls] == [
            "https://discord.com/api/v10/guilds/g1/channels",
            "https://discord.com/api/v10/guilds/g2/channels",
        ]

    def test_no_guilds_returns_empty(self, discord_token):
        assert asyncio.run(list_all_text_channels([])) == []


class TestListGuilds:
    def test_returns_id_name_pairs(self, discord_token):
        session_ctx, _ = _session_with([
            _resp(200, [{"id": "g1", "name": "Guild One"}, {"id": 123, "name": "Two"}, {"no_id": True}]),
        ])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            guilds = asyncio.run(list_guilds())
        assert guilds == [{"id": "g1", "name": "Guild One"}, {"id": "123", "name": "Two"}]

    def test_401_raises_auth_error(self, discord_token):
        session_ctx, _ = _session_with([_resp(401, {"message": "401: Unauthorized"})])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            with pytest.raises(DiscordAuthError, match="token"):
                asyncio.run(list_guilds())

    def test_other_error_raises_channel_error_with_discord_message(self, discord_token):
        session_ctx, _ = _session_with([_resp(500, {"message": "internal"})])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            with pytest.raises(DiscordChannelError, match="internal"):
                asyncio.run(list_guilds())

    def test_missing_token_raises_auth_error_without_http(self, monkeypatch):
        monkeypatch.setattr(
            "agent.secret_scope.get_secret", lambda name, default=None: ""
        )
        with pytest.raises(DiscordAuthError, match="DISCORD_BOT_TOKEN"):
            asyncio.run(list_guilds())


class TestCreateResultsChannel:
    def test_success_single_guild(self, discord_token):
        session_ctx, calls = _session_with([
            _resp(200, [{"id": "g1", "name": "Guild One"}]),
            _resp(200, {"id": "c123", "name": "cron-morning-brief"}),
        ])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            result = asyncio.run(create_results_channel("Morning Brief"))

        assert result == {"id": "c123", "name": "cron-morning-brief"}
        assert len(calls) == 2
        method, url, body = calls[1]
        assert method == "POST"
        assert url.endswith("/guilds/g1/channels")
        assert body == {"name": "cron-morning-brief", "type": 0}

    def test_explicit_guild_id_wins_in_multi_guild(self, discord_token):
        session_ctx, calls = _session_with([
            _resp(200, [{"id": "g1", "name": "One"}, {"id": "g2", "name": "Two"}]),
            _resp(200, {"id": "c9", "name": "cron-job-x"}),
        ])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            result = asyncio.run(create_results_channel("Job X", guild_id="g2"))

        assert result["id"] == "c9"
        assert "/guilds/g2/channels" in calls[1][1]

    def test_multi_guild_without_choice_raises_client_error(self, discord_token):
        session_ctx, calls = _session_with([
            _resp(200, [{"id": "g1", "name": "One"}, {"id": "g2", "name": "Two"}]),
        ])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            with pytest.raises(DiscordChannelError, match="multiple guilds") as exc_info:
                asyncio.run(create_results_channel("Job X"))

        # No Discord HTTP status → the web layer maps this to 400.
        assert exc_info.value.status is None
        # Nothing was created.
        assert len(calls) == 1

    def test_no_guilds_raises(self, discord_token):
        session_ctx, _ = _session_with([_resp(200, [])])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            with pytest.raises(DiscordChannelError, match="not a member of any guild"):
                asyncio.run(create_results_channel("Job X"))

    def test_401_on_guild_list_raises_auth_error(self, discord_token):
        session_ctx, _ = _session_with([_resp(401, {"message": "401: Unauthorized"})])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            with pytest.raises(DiscordAuthError, match="token"):
                asyncio.run(create_results_channel("Job X"))

    def test_403_on_create_mentions_manage_channels(self, discord_token):
        session_ctx, _ = _session_with([
            _resp(200, [{"id": "g1", "name": "Guild One"}]),
            _resp(403, {"message": "Missing Permissions"}),
        ])
        with patch("aiohttp.ClientSession", return_value=session_ctx):
            with pytest.raises(DiscordChannelError, match="Manage Channels") as exc_info:
                asyncio.run(create_results_channel("Job X"))
        assert exc_info.value.status == 403


# ---------------------------------------------------------------------------
# list_text_channels (cached channel directory)
# ---------------------------------------------------------------------------

def _write_directory(raw: str):
    from hermes_constants import get_hermes_home

    path = get_hermes_home() / "channel_directory.json"
    path.write_text(raw, encoding="utf-8")
    return path


class TestListTextChannels:
    def test_missing_file_returns_empty(self):
        assert list_text_channels() == []

    def test_corrupt_file_returns_empty(self):
        _write_directory("{not valid json")
        assert list_text_channels() == []

    def test_unexpected_shape_returns_empty(self):
        _write_directory(json.dumps({"platforms": {"discord": "oops"}}))
        assert list_text_channels() == []

    def test_returns_only_text_channels(self):
        _write_directory(json.dumps({
            "platforms": {
                "discord": [
                    {"id": "c1", "name": "general", "guild": "Guild One", "type": "channel"},
                    {"id": "c2", "name": "cron-morning-brief", "guild": "Guild One", "type": "channel"},
                    {"id": "f1", "name": "help-forum", "guild": "Guild One", "type": "forum"},
                    {"id": "u1", "name": "alice", "type": "dm"},
                    {"name": "no-id", "type": "channel"},
                ],
                "telegram": [{"id": "t1", "name": "tg-group", "type": "group"}],
            }
        }))
        assert list_text_channels() == [
            {"id": "c1", "name": "general", "guild": "Guild One"},
            {"id": "c2", "name": "cron-morning-brief", "guild": "Guild One"},
        ]
