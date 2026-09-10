"""First-party Hermes observability integrations."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def observe_lifecycle(hook_name: str, **kwargs: Any) -> None:
    """Dispatch a Hermes lifecycle event to built-in observability features."""
    from . import api_errors, relay_shared_metrics

    try:
        relay_shared_metrics.observe_lifecycle(hook_name, **kwargs)
    except Exception:
        logger.warning("Built-in observability hook failed: %s", hook_name, exc_info=True)
    try:
        api_errors.observe_lifecycle(hook_name, **kwargs)
    except Exception:
        logger.warning("Built-in observability hook failed: %s", hook_name, exc_info=True)


def handles_hook(hook_name: str) -> bool:
    """Return whether any built-in observability feature handles a hook."""
    from . import api_errors, relay_shared_metrics

    return relay_shared_metrics.handles_hook(hook_name) or api_errors.handles_hook(
        hook_name
    )
