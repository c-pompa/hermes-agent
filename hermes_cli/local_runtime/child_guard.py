"""WORKAROUND for llama.cpp router-mode wedged children.

A router child (the per-model llama-server the router spawns) can wedge in
a state where the process is alive, /health returns ok, GET /models shows
the model loaded, yet every /v1/chat/completions returns HTTP 500
("Compute error") — and the child may even ignore SIGTERM, needing
SIGKILL. None of the existing supervision catches it: the crash watchdog
(supervisor._watch) only restarts on process EXIT, touch_generate() only
runs at load/readiness time, and model_failures() only surfaces children
llama.cpp itself marks "failed".

Upstream owns child lifecycle in router mode and declined child health
supervision: ggml-org/llama.cpp#18912 (closed not-planned). This module is
the hermes-side workaround, and it is meant to be DELETED — together with
the ``local_runtime.child_guard`` config section and the single guarded
hook call site in agent/conversation_loop.py — when upstream adds child
health supervision.

Design:
- The conversation loop reports inference outcomes against the managed
  endpoint (note_inference_failure / note_inference_success). Consecutive
  500-class or transport failures per model are counted; a success resets.
- Past ``failure_threshold`` consecutive failures, recovery runs ONCE per
  ``recovery_cooldown_seconds`` window, on a daemon thread so the hot
  path never blocks:
  1. probe the child with the supervisor's touch generation;
  2. probe ok -> the child recovered on its own, done;
  3. probe fails -> POST /models/unload so the router autoloads a fresh
     child on the next request;
  4. unload failed or the reloaded child still errors -> kill the child
     process directly (SIGTERM, then SIGKILL for stragglers).
- Everything is best-effort: internal errors are logged and swallowed,
  never raised into the caller.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_failures: dict[str, int] = {}            # model -> consecutive failures
_last_recovery: dict[str, float] = {}     # model -> monotonic ts of last recovery
_recovery_in_flight: set[str] = set()     # models with a recovery thread running
_build_checked = False                    # version-nudge runs once per process

_DEFAULTS = {
    "enabled": True,
    "failure_threshold": 2,
    "recovery_cooldown_seconds": 300,
}

# Marker file recording the llama.cpp build the guard last saw, beside the
# runtimes. A build change is the reminder to re-test upstream and delete.
_BUILD_MARKER = "child_guard_build"


def _config() -> dict:
    """``local_runtime.child_guard`` section, defaults filled."""
    cfg = dict(_DEFAULTS)
    try:
        from hermes_cli.config import load_config

        user = ((load_config() or {}).get("local_runtime") or {}).get("child_guard") or {}
        for key in _DEFAULTS:
            if user.get(key) is not None:
                cfg[key] = user[key]
    except Exception:  # noqa: BLE001 — config read is best-effort
        pass
    return cfg


def is_managed_endpoint(base_url: str | None) -> bool:
    """True when *base_url* targets the llama-server this Hermes manages.

    Same contract as agent.auxiliary_client._is_managed_local_endpoint
    (netloc match against the supervisor state file), re-implemented here
    so this workaround stays self-contained and deletable without touching
    anything outside the module.
    """
    try:
        if not base_url:
            return False
        from hermes_cli.local_runtime.supervisor import state_path

        state = json.loads(state_path().read_text(encoding="utf-8"))
        managed = str(state.get("base_url") or "")
        if not managed:
            return False
        return urlparse(str(base_url)).netloc.lower() == urlparse(managed).netloc.lower()
    except Exception:  # noqa: BLE001
        return False


def _countable(status_code: int | None) -> bool:
    """Only 500-class server errors and transport errors signal a wedge.

    status None means the request never got a response (connection reset,
    timeout). Some None-status errors are really local bugs, but the probe
    step makes a false trigger benign: a healthy child answers it and the
    counter resets. 4xx (request-shape problems) never counts.
    """
    if status_code is None:
        return True
    try:
        return int(status_code) >= 500
    except (TypeError, ValueError):
        return False


def note_inference_failure(model: str, status_code: int | None,
                           exc: Exception | None) -> None:
    """Record one inference failure against the managed endpoint.

    Counts CONSECUTIVE failures per model; note_inference_success resets.
    Past the threshold, kicks recovery once per cooldown window. Never
    raises.
    """
    try:
        cfg = _config()
        if not cfg["enabled"]:
            return
        _check_build_nudge()
        if not model or not _countable(status_code):
            return
        trigger = False
        with _LOCK:
            count = _failures.get(model, 0) + 1
            _failures[model] = count
            now = time.monotonic()
            cooldown = float(cfg["recovery_cooldown_seconds"])
            if (count >= int(cfg["failure_threshold"])
                    and model not in _recovery_in_flight
                    and now - _last_recovery.get(model, float("-inf")) >= cooldown):
                _last_recovery[model] = now
                _recovery_in_flight.add(model)
                trigger = True
        if trigger:
            logger.warning(
                "child_guard: %s hit %d consecutive inference failures "
                "(last: status=%s, %s); probing the router child",
                model, count, status_code, exc)
            _start_recovery(model)
    except Exception:  # noqa: BLE001 — never raise into the agent loop
        logger.exception("child_guard: note_inference_failure failed")


def note_inference_success(model: str) -> None:
    """A successful response from the managed endpoint resets the count."""
    try:
        if not model:
            return
        with _LOCK:
            _failures.pop(model, None)
    except Exception:  # noqa: BLE001
        logger.exception("child_guard: note_inference_success failed")


# ── recovery ─────────────────────────────────────────────────


def _start_recovery(model: str) -> None:
    """Recovery off the hot path (the probe alone can take seconds)."""
    threading.Thread(target=_recover, args=(model,), daemon=True,
                     name=f"child-guard-{model}").start()


def _router_client():
    """A LlamaServerSupervisor-shaped HTTP client for the running server.

    Deliberately NOT bootstrap.get_supervisor(): the managed server is
    usually ADOPTED (spawned by an earlier Hermes process), so no
    in-process supervisor object exists. touch_generate/unload_model need
    only ``port`` and ``api_key``, both recorded in the state file.
    """
    from hermes_cli.local_runtime.supervisor import (
        LlamaServerSupervisor,
        state_path,
    )

    try:
        state = json.loads(state_path().read_text(encoding="utf-8"))
        port = urlparse(str(state.get("base_url") or "")).port
        if not port:
            return None
        client = LlamaServerSupervisor.__new__(LlamaServerSupervisor)
        client.port = int(port)
        client.api_key = str(state.get("api_key") or "")
        return client
    except Exception:  # noqa: BLE001
        return None


def _recover(model: str) -> None:
    """Probe -> unload -> kill ladder for one wedged child."""
    try:
        client = _router_client()
        if client is None:
            logger.warning("child_guard: cannot probe %s — no managed "
                           "endpoint state; skipping recovery", model)
            return
        if client.touch_generate(model, timeout_s=120):
            logger.info("child_guard: %s recovered on its own (probe "
                        "succeeded); counter reset", model)
            return
        logger.warning("child_guard: %s probe failed; unloading so the "
                       "router autoloads a fresh child", model)
        try:
            client.unload_model(model)
        except Exception as exc:  # noqa: BLE001
            logger.warning("child_guard: unload of %s failed (%s); "
                           "killing the child process", model, exc)
            _kill_child(model)
            return
        # --models-autoload makes this probe load a FRESH child.
        if client.touch_generate(model, timeout_s=300):
            logger.warning("child_guard: %s healthy again after unload + "
                           "autoload", model)
        else:
            logger.warning("child_guard: %s still errors after reload; "
                           "killing the child process", model)
            _kill_child(model)
    except Exception:  # noqa: BLE001
        logger.exception("child_guard: recovery for %s failed", model)
    finally:
        with _LOCK:
            # Reset regardless of outcome: the recovery run answered the
            # accumulated failures, and a still-wedged child will simply
            # re-accumulate to the threshold after the cooldown.
            _failures.pop(model, None)
            _recovery_in_flight.discard(model)


def _kill_child(model: str) -> None:
    """Last resort: SIGTERM the wedged child, SIGKILL if it ignores it.

    Router children are enumerated from the state's router pid exactly like
    supervisor._terminate_tree does. The child serving *model* is matched
    by cmdline (the router passes the model path/alias to its spawn); with
    exactly one child there is nothing to disambiguate. Never falls back to
    killing unmatched children — a wrong-model kill takes a healthy model's
    VRAM down with it.
    """
    try:
        import psutil

        from hermes_cli.local_runtime.supervisor import state_path

        state = json.loads(state_path().read_text(encoding="utf-8"))
        pid = int(state.get("pid") or 0)
        if pid <= 0:
            logger.warning("child_guard: no router pid in state; cannot "
                           "kill the %s child", model)
            return
        children = psutil.Process(pid).children(recursive=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("child_guard: cannot enumerate router children "
                       "(%s); %s left wedged", exc, model)
        return
    victims = []
    for child in children:
        try:
            if model in " ".join(str(a) for a in (child.cmdline() or [])):
                victims.append(child)
        except Exception:  # noqa: BLE001 — process may be gone already
            continue
    if not victims and len(children) == 1:
        victims = list(children)
    if not victims:
        logger.warning("child_guard: no child of router pid=%s matches %s; "
                       "giving up (kill it by hand)", pid, model)
        return
    for child in victims:
        try:
            logger.warning("child_guard: SIGTERM to wedged child pid=%s "
                           "(model %s)", child.pid, model)
            child.terminate()
        except Exception:  # noqa: BLE001
            continue
    try:
        _, alive = psutil.wait_procs(victims, timeout=5)
    except Exception:  # noqa: BLE001
        alive = victims
    for child in alive:
        try:
            logger.warning("child_guard: child pid=%s ignored SIGTERM; "
                           "SIGKILL", child.pid)
            child.kill()
        except Exception:  # noqa: BLE001
            continue


# ── version-awareness nudge ──────────────────────────────────


def _check_build_nudge() -> None:
    """Once per process: when the llama.cpp build changed since the guard
    last saw it, remind that the workaround may be obsolete upstream."""
    global _build_checked
    with _LOCK:
        if _build_checked:
            return
        _build_checked = True
    try:
        from hermes_cli.local_runtime.binaries import installed_tags, runtimes_root

        tags = installed_tags()
        if not tags:
            return
        current = tags[0]
        marker = runtimes_root() / _BUILD_MARKER
        previous = ""
        try:
            previous = marker.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        if previous == current:
            return
        if previous:
            logger.warning(
                "llama.cpp runtime updated (%s → %s); re-test whether "
                "child_guard workaround is still needed, then delete this "
                "module", previous, current)
        marker.write_text(current, encoding="utf-8")
    except Exception:  # noqa: BLE001 — the nudge is advisory
        logger.debug("child_guard: build nudge failed", exc_info=True)
