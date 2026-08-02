"""Persist API request errors to the local error store (dashboard /errors).

First-party lifecycle consumer for the ``api_request_error`` hook (fired per
failed attempt from ``agent/conversation_loop.py``, payload built in
``run_agent.py::_invoke_api_request_error_hook``). Unlike the Relay-backed
shared-metrics consumer this is unconditional: the store is a local sqlite
file with no consent gate and no runtime dependency, so every process that
dispatches lifecycle hooks (gateway / serve / CLI / cron) records errors.

Fail-isolation is provided by the dispatcher: ``hermes_cli.observability``
calls every consumer through ``_safe_observe``, so a broken store can never
break a turn.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

HANDLED_HOOKS = frozenset({"api_request_error"})


def handles_hook(hook_name: str) -> bool:
    return hook_name in HANDLED_HOOKS


def observe_lifecycle(hook_name: str, **kwargs: Any) -> None:
    """Map one ``api_request_error`` payload onto the error store."""
    if not handles_hook(hook_name):
        return
    from . import api_error_store

    api_error_store.record_error(kwargs)
