"""Per-job Discord results channels for cron jobs.

A cron job can opt into additive fan-out delivery by adding
``discord:<channel_id>`` to its comma-separated ``deliver`` field — the
scheduler's existing delivery resolution already routes such targets, so no
scheduler or job-schema changes are needed.  This module provides the
provisioning half: creating the per-job ``cron-<slug>`` text channel over
the Discord REST API, plus listing the bot's guilds and known text channels
so the cron editor UI can offer them.

Reads the bot token via ``agent.secret_scope.get_secret("DISCORD_BOT_TOKEN")``
(profile-scoped) and the cached channel directory
(``~/.hermes/channel_directory.json``, see ``gateway/channel_directory.py``)
for the channels the bot can already see.  The token is only ever sent as an
``Authorization`` header — never logged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"

# Discord channel names are capped at 100 characters.
_CHANNEL_NAME_MAX = 100


class DiscordChannelError(Exception):
    """Raised when Discord channel provisioning or listing fails.

    ``status`` carries the Discord HTTP status when the failure came from
    the Discord API itself; ``None`` for local failures (no token, guild
    resolution, network errors).  Callers use this to tell upstream
    bad-gateway failures apart from fix-the-request client errors.
    """

    def __init__(self, message: str, status: Optional[int] = None):
        self.status = status
        super().__init__(message)


class DiscordAuthError(DiscordChannelError):
    """The Discord bot token is missing, invalid, or has been reset."""


def slugify_channel_name(job_name: str) -> str:
    """Turn a human job name into a valid Discord channel name.

    Lowercases, maps spaces to dashes, strips characters outside
    ``[a-z0-9_-]``, collapses consecutive dashes, strips leading/trailing
    dashes, and prefixes ``cron-``.  Truncated to Discord's 100-character
    channel-name limit.  A name with nothing slug-worthy left yields
    ``cron-job``.  Already-slugged names pass through unchanged (no double
    ``cron-`` prefix).
    """
    slug = str(job_name or "").lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9_-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        return "cron-job"
    if not slug.startswith("cron-"):
        slug = f"cron-{slug}"
    return slug[:_CHANNEL_NAME_MAX]


def _get_bot_token() -> str:
    """Resolve the Discord bot token under the active profile secret scope."""
    from agent.secret_scope import get_secret

    token = (get_secret("DISCORD_BOT_TOKEN", "") or "").strip()
    if not token:
        raise DiscordAuthError(
            "DISCORD_BOT_TOKEN is not configured — connect the Discord "
            "platform (or re-enter its bot token) first"
        )
    return token


async def _discord_request(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
) -> Any:
    """Make one authenticated request to the Discord REST API.

    Mirrors the standalone-send pattern in
    ``plugins/platforms/discord/adapter.py`` (``Authorization: Bot <token>``,
    ``DISCORD_PROXY``-aware aiohttp session).  401 maps to
    :class:`DiscordAuthError`; any other non-2xx maps to
    :class:`DiscordChannelError` carrying Discord's own ``message`` and the
    HTTP status.
    """
    try:
        import aiohttp
    except ImportError as exc:
        raise DiscordChannelError(
            "aiohttp is not installed. Run: pip install aiohttp"
        ) from exc

    token = _get_bot_token()

    from gateway.platforms.base import resolve_proxy_url, proxy_kwargs_for_aiohttp

    proxy = resolve_proxy_url(platform_env_var="DISCORD_PROXY")
    session_kwargs, request_kwargs = proxy_kwargs_for_aiohttp(proxy)
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession(**session_kwargs) as session:
            async with session.request(
                method,
                f"{DISCORD_API_BASE}{path}",
                headers=headers,
                json=json_body,
                **request_kwargs,
            ) as resp:
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = None
                if 200 <= resp.status < 300:
                    return data
                discord_message = ""
                if isinstance(data, dict):
                    discord_message = str(data.get("message") or "")
                detail = discord_message or f"HTTP {resp.status}"
                if resp.status == 401:
                    raise DiscordAuthError(
                        "Discord bot token invalid or reset — re-enter it in "
                        f"the Discord platform settings ({detail})",
                        status=401,
                    )
                raise DiscordChannelError(
                    f"Discord API error {resp.status}: {detail}",
                    status=resp.status,
                )
    except (DiscordChannelError, DiscordAuthError):
        raise
    except Exception as exc:  # aiohttp.ClientError and friends
        raise DiscordChannelError(f"Discord API request failed: {exc}") from exc


async def list_guilds() -> List[Dict[str, str]]:
    """List the guilds (servers) the Discord bot is a member of.

    Returns ``[{"id", "name"}, ...]``.  Raises :class:`DiscordAuthError`
    when the token is rejected, :class:`DiscordChannelError` otherwise.
    """
    data = await _discord_request("GET", "/users/@me/guilds")
    guilds: List[Dict[str, str]] = []
    for guild in data or []:
        if not isinstance(guild, dict) or not guild.get("id"):
            continue
        guilds.append(
            {"id": str(guild["id"]), "name": str(guild.get("name") or guild["id"])}
        )
    return guilds


async def list_guild_text_channels(
    guild_id: str, guild_name: str = ""
) -> List[Dict[str, str]]:
    """List one guild's text channels live over the Discord REST API.

    Returns ``[{"id", "name", "guild"}, ...]`` for text channels (type 0)
    only.  Unlike :func:`list_text_channels` (cached directory, never
    raises), this hits Discord and raises :class:`DiscordAuthError` /
    :class:`DiscordChannelError` on failure.
    """
    data = await _discord_request("GET", f"/guilds/{guild_id}/channels")
    channels: List[Dict[str, str]] = []
    for channel in data or []:
        if not isinstance(channel, dict) or channel.get("type") != 0:
            continue
        if not channel.get("id"):
            continue
        channels.append(
            {
                "id": str(channel["id"]),
                "name": str(channel.get("name") or channel["id"]),
                "guild": guild_name,
            }
        )
    return channels


async def list_all_text_channels(
    guilds: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """List text channels across every guild the bot is in, live over REST.

    The cached channel directory (``list_text_channels``) only exists where a
    gateway process rebuilds it — isolated profile dashboards don't have one —
    so the cron editor's channel picker needs this live path.  Raises on the
    first failing guild; callers fall back to the cache when appropriate.
    """
    channels: List[Dict[str, str]] = []
    for guild in guilds:
        channels.extend(
            await list_guild_text_channels(guild["id"], guild.get("name") or "")
        )
    return channels


def list_text_channels() -> List[Dict[str, str]]:
    """List known Discord text channels from the cached channel directory.

    Reads ``~/.hermes/channel_directory.json`` (rebuilt by the gateway every
    5 minutes — see ``gateway/channel_directory.py``).  Returns
    ``[{"id", "name", "guild"}, ...]`` for text channels only.  A missing or
    corrupt directory yields an empty list — this never raises, so feed
    builders can call it unconditionally.
    """
    path = get_hermes_home() / "channel_directory.json"
    try:
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.debug("discord_channels: channel directory unreadable", exc_info=True)
        return []

    platforms = data.get("platforms") if isinstance(data, dict) else None
    entries = platforms.get("discord") if isinstance(platforms, dict) else None
    if not isinstance(entries, list):
        return []

    channels: List[Dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "channel":
            continue
        channel_id = str(entry.get("id") or "").strip()
        if not channel_id:
            continue
        channels.append(
            {
                "id": channel_id,
                "name": str(entry.get("name") or channel_id),
                "guild": str(entry.get("guild") or ""),
            }
        )
    return channels


async def create_results_channel(
    job_name: str, guild_id: Optional[str] = None
) -> Dict[str, str]:
    """Create the per-job ``cron-<slug>`` text channel and return ``{"id", "name"}``.

    Guild resolution: an explicit ``guild_id`` wins; otherwise the bot must be
    in exactly one guild.  Multi-guild with no choice raises
    :class:`DiscordChannelError` (no ``status`` — a fix-the-request client
    error, mapped to HTTP 400 by the web layer).  Discord 403 maps to a
    ``DiscordChannelError`` pointing at the missing Manage Channels
    permission; 401 maps to :class:`DiscordAuthError`.

    Nothing is persisted here — the channel id lands in the job's ``deliver``
    string via the caller.  The channel directory is not refreshed inline:
    ``build_channel_directory`` needs live gateway adapters this process may
    not have, and the gateway rebuilds it every 5 minutes anyway.
    """
    slug = slugify_channel_name(job_name)
    guilds = await list_guilds()

    if guild_id:
        resolved_guild = str(guild_id)
    elif len(guilds) == 1:
        resolved_guild = guilds[0]["id"]
    elif not guilds:
        raise DiscordChannelError(
            "Discord bot is not a member of any guild — invite it to a server first"
        )
    else:
        names = ", ".join(g["name"] for g in guilds)
        raise DiscordChannelError(
            f"Discord bot is in multiple guilds ({names}); pick one and pass guild_id"
        )

    try:
        channel = await _discord_request(
            "POST",
            f"/guilds/{resolved_guild}/channels",
            json_body={"name": slug, "type": 0},
        )
    except DiscordChannelError as exc:
        if exc.status == 403:
            raise DiscordChannelError(
                "Discord bot lacks the Manage Channels permission in this "
                "guild — grant it and retry",
                status=403,
            ) from exc
        raise

    if not isinstance(channel, dict) or not channel.get("id"):
        raise DiscordChannelError("Discord did not return the created channel")
    return {"id": str(channel["id"]), "name": str(channel.get("name") or slug)}
