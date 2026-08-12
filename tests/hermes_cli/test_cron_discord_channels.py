"""Tests for the cron Discord channel provisioning endpoints.

- GET  /api/cron/discord-channels returns the bot's guilds + known text
  channels; Discord-side failures map to 502 with a human-readable detail.
- POST /api/cron/discord-channels creates the per-job ``cron-<slug>``
  channel: 200 with ``{"id", "name"}`` on success, 502 on Discord auth
  (401) / permission (403) failures, 400 when a multi-guild bot call
  didn't pick a guild.

The workers live in ``hermes_cli.web_server`` and are late-bound into the
router (``hermes_cli.web_deps.late``), so tests monkeypatch them on
``web_server`` — the same seam the other cron dashboard tests use.
"""

import pytest

from cron.discord_channels import DiscordAuthError, DiscordChannelError


@pytest.fixture
def client(monkeypatch):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import hermes_state
    from hermes_constants import get_hermes_home
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db")
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return c


class TestListCronDiscordChannels:
    def test_returns_guilds_and_channels(self, client, monkeypatch):
        from hermes_cli import web_server

        payload = {
            "guilds": [{"id": "g1", "name": "Guild One"}],
            "channels": [{"id": "c1", "name": "general", "guild": "Guild One"}],
        }
        monkeypatch.setattr(
            web_server, "_list_cron_discord_channels_sync", lambda: payload
        )

        resp = client.get("/api/cron/discord-channels")
        assert resp.status_code == 200
        assert resp.json() == payload

    def test_discord_failure_maps_to_502(self, client, monkeypatch):
        from hermes_cli import web_server

        def boom():
            raise DiscordAuthError("Discord bot token invalid or reset")

        monkeypatch.setattr(web_server, "_list_cron_discord_channels_sync", boom)

        resp = client.get("/api/cron/discord-channels")
        assert resp.status_code == 502
        assert "token" in resp.json()["detail"]


class TestCreateCronDiscordChannel:
    def test_create_success(self, client, monkeypatch):
        from hermes_cli import web_server

        seen = {}

        def fake_create(body):
            seen["name"] = body.name
            seen["guild_id"] = body.guild_id
            return {"id": "c123", "name": "cron-morning-brief"}

        monkeypatch.setattr(
            web_server, "_create_cron_discord_channel_sync", fake_create
        )

        resp = client.post(
            "/api/cron/discord-channels",
            json={"name": "Morning Brief", "guild_id": "g1"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"id": "c123", "name": "cron-morning-brief"}
        assert seen == {"name": "Morning Brief", "guild_id": "g1"}

    def test_auth_error_maps_to_502(self, client, monkeypatch):
        from hermes_cli import web_server

        def boom(body):
            raise DiscordAuthError("Discord bot token invalid or reset")

        monkeypatch.setattr(web_server, "_create_cron_discord_channel_sync", boom)

        resp = client.post("/api/cron/discord-channels", json={"name": "X"})
        assert resp.status_code == 502
        assert "token" in resp.json()["detail"]

    def test_permission_error_maps_to_502(self, client, monkeypatch):
        from hermes_cli import web_server

        def boom(body):
            raise DiscordChannelError(
                "Discord bot lacks the Manage Channels permission in this "
                "guild — grant it and retry",
                status=403,
            )

        monkeypatch.setattr(web_server, "_create_cron_discord_channel_sync", boom)

        resp = client.post("/api/cron/discord-channels", json={"name": "X"})
        assert resp.status_code == 502
        assert "Manage Channels" in resp.json()["detail"]

    def test_multi_guild_without_choice_maps_to_400(self, client, monkeypatch):
        from hermes_cli import web_server

        def boom(body):
            raise DiscordChannelError(
                "Discord bot is in multiple guilds (One, Two); pick one and pass guild_id"
            )

        monkeypatch.setattr(web_server, "_create_cron_discord_channel_sync", boom)

        resp = client.post("/api/cron/discord-channels", json={"name": "X"})
        assert resp.status_code == 400
        assert "pick one" in resp.json()["detail"]

    def test_empty_name_rejected(self, client):
        resp = client.post("/api/cron/discord-channels", json={"name": ""})
        assert resp.status_code == 422
