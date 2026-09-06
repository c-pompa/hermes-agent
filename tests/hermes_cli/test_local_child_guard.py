"""Wedged-child guard: a llama.cpp router child that stays alive, answers
/health, and lists in GET /models yet 500s every completion (and may
ignore SIGTERM) must be detected from the client side and recycled.

The incident this guards: one child wedged exactly so; the crash watchdog
only restarts on process exit, touch_generate only runs at load time, and
model_failures only surfaces children llama.cpp itself marks failed — so
nothing noticed, and every turn burned all retries and died. Upstream
declined child health supervision (ggml-org/llama.cpp#18912, closed
not-planned); hermes_cli/local_runtime/child_guard.py is the workaround.

Contracts under test:
1. Consecutive-failure counting per model, reset by a success.
2. Past the threshold, recovery runs once per cooldown window.
3. disabled config = the hook is a no-op.
4. A successful probe means the child recovered — never escalate.
5. A failed probe escalates to POST /models/unload; a failed unload (or a
   still-broken reload) kills the child process (SIGTERM, then SIGKILL).
"""

from __future__ import annotations

import json
import types

import pytest

from hermes_cli.local_runtime import child_guard

MODEL = "Qwen-Local"


@pytest.fixture
def guard(monkeypatch):
    """Module state reset, config pinned, recovery run inline, build-nudge
    silenced — tests drive _recover synchronously instead of via thread."""
    monkeypatch.setattr(child_guard, "_config", lambda: {
        "enabled": True,
        "failure_threshold": 2,
        "recovery_cooldown_seconds": 300,
    })
    child_guard._failures.clear()
    child_guard._last_recovery.clear()
    child_guard._recovery_in_flight.clear()
    monkeypatch.setattr(child_guard, "_build_checked", True)
    monkeypatch.setattr(child_guard, "_start_recovery",
                        lambda model: child_guard._recover(model))
    return child_guard


class _FakeRouter:
    """Supervisor-shaped client: queued probe results, recorded unloads."""

    def __init__(self, probe_results, unload_exc=None):
        self.probe_results = list(probe_results)
        self.unload_exc = unload_exc
        self.probes = 0
        self.unloaded = []

    def touch_generate(self, model, timeout_s=300):
        self.probes += 1
        return self.probe_results.pop(0) if self.probe_results else False

    def unload_model(self, model):
        self.unloaded.append(model)
        if self.unload_exc is not None:
            raise self.unload_exc


def _use_router(guard, monkeypatch, router):
    monkeypatch.setattr(guard, "_router_client", lambda: router)
    return router


def _fail(guard, model=MODEL, status=500):
    guard.note_inference_failure(model, status, RuntimeError("Compute error"))


# ── 1+2. counting, reset, threshold ──────────────────────────


def test_success_resets_consecutive_count(guard, monkeypatch):
    router = _use_router(guard, monkeypatch, _FakeRouter([True]))
    _fail(guard)
    guard.note_inference_success(MODEL)
    _fail(guard)
    assert router.probes == 0, (
        "success between failures must reset the consecutive count — "
        "isolated errors never reach the threshold")
    _fail(guard)  # now 2 consecutive -> recovery
    assert router.probes == 1


def test_threshold_triggers_recovery(guard, monkeypatch):
    router = _use_router(guard, monkeypatch, _FakeRouter([True]))
    _fail(guard)
    assert router.probes == 0, "one failure is below the default threshold"
    _fail(guard)
    assert router.probes == 1


def test_4xx_never_counts(guard, monkeypatch):
    router = _use_router(guard, monkeypatch, _FakeRouter([True]))
    guard.note_inference_failure(MODEL, 400, RuntimeError("bad request"))
    guard.note_inference_failure(MODEL, 404, RuntimeError("not found"))
    assert router.probes == 0, "request-shape errors are not a wedged child"


def test_transport_error_counts(guard, monkeypatch):
    router = _use_router(guard, monkeypatch, _FakeRouter([True]))
    guard.note_inference_failure(MODEL, None, ConnectionError("reset"))
    guard.note_inference_failure(MODEL, None, TimeoutError("timeout"))
    assert router.probes == 1


# ── 2b. cooldown ──────────────────────────────────────────────


def test_cooldown_prevents_double_recovery(guard, monkeypatch):
    router = _use_router(guard, monkeypatch, _FakeRouter([True, True]))
    _fail(guard)
    _fail(guard)
    assert router.probes == 1
    # Immediately failing twice more must NOT re-trigger inside the window.
    _fail(guard)
    _fail(guard)
    assert router.probes == 1, (
        "recovery re-ran inside the cooldown — a permanently broken child "
        "would probe/escape once per failure burst instead of once per window")


# ── 3. disabled flag ──────────────────────────────────────────


def test_disabled_flag_is_noop(guard, monkeypatch):
    monkeypatch.setattr(guard, "_config", lambda: {
        "enabled": False,
        "failure_threshold": 2,
        "recovery_cooldown_seconds": 300,
    })
    router = _use_router(guard, monkeypatch, _FakeRouter([True]))
    for _ in range(5):
        _fail(guard)
    assert router.probes == 0
    assert guard._failures == {}, "disabled guard must not even count"


# ── 4+5. probe / escalate ladder ──────────────────────────────


def test_probe_success_does_not_escalate(guard, monkeypatch):
    router = _use_router(guard, monkeypatch, _FakeRouter([True]))
    _fail(guard)
    _fail(guard)
    assert router.unloaded == [], (
        "child answered the probe — it recovered on its own; unloading "
        "would throw away a healthy model's VRAM residency")
    assert guard._failures.get(MODEL, 0) == 0


def test_probe_failure_unloads_for_fresh_autoload(guard, monkeypatch):
    # Probe fails, unload ok, reloaded child answers the verification probe.
    router = _use_router(guard, monkeypatch, _FakeRouter([False, True]))
    _fail(guard)
    _fail(guard)
    assert router.unloaded == [MODEL]
    assert router.probes == 2


class _FakeChild:
    def __init__(self, pid, cmdline, survives_sigterm=False):
        self.pid = pid
        self._cmdline = cmdline
        self.terminated = False
        self.killed = False
        self._survives = survives_sigterm

    def cmdline(self):
        return self._cmdline

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _fake_psutil(children, survivors=()):
    return types.SimpleNamespace(
        Process=lambda pid: types.SimpleNamespace(
            children=lambda recursive=True: children),
        wait_procs=lambda procs, timeout=None: (
            [p for p in procs if p not in survivors],
            [p for p in procs if p in survivors]),
    )


def _router_state(tmp_path, monkeypatch, pid=4242):
    state = tmp_path / "server.json"
    state.write_text(json.dumps({
        "base_url": "http://127.0.0.1:18434/v1", "api_key": "k", "pid": pid,
    }))
    monkeypatch.setattr("hermes_cli.local_runtime.supervisor.state_path",
                        lambda: state)


def test_failed_unload_kills_the_wedged_child(guard, monkeypatch, tmp_path):
    _router_state(tmp_path, monkeypatch)
    wedged = _FakeChild(101, ["llama-server", "--model", f"{MODEL}.gguf"])
    healthy = _FakeChild(102, ["llama-server", "--model", "Other.gguf"])
    monkeypatch.setitem(__import__("sys").modules, "psutil",
                        _fake_psutil([wedged, healthy]))
    router = _use_router(guard, monkeypatch,
                         _FakeRouter([False], unload_exc=RuntimeError("500")))
    _fail(guard)
    _fail(guard)
    assert router.unloaded == [MODEL]
    assert wedged.terminated and not healthy.terminated, (
        "the kill ladder must only touch the wedged model's child")
    assert not wedged.killed, "child took SIGTERM — no SIGKILL needed"


def test_sigterm_ignoring_child_gets_sigkill(guard, monkeypatch, tmp_path):
    _router_state(tmp_path, monkeypatch)
    wedged = _FakeChild(101, ["llama-server", "--model", f"{MODEL}.gguf"],
                        survives_sigterm=True)
    monkeypatch.setitem(__import__("sys").modules, "psutil",
                        _fake_psutil([wedged], survivors=[wedged]))
    # Probe fails, unload ok, reload still broken -> kill ladder.
    _use_router(guard, monkeypatch, _FakeRouter([False, False]))
    _fail(guard)
    _fail(guard)
    assert wedged.terminated and wedged.killed, (
        "the incident child ignored SIGTERM; the guard must escalate to "
        "SIGKILL or the wedge survives the whole recovery")


# ── endpoint gating ───────────────────────────────────────────


def test_is_managed_endpoint_matches_state_netloc(tmp_path, monkeypatch):
    _router_state(tmp_path, monkeypatch)
    assert child_guard.is_managed_endpoint("http://127.0.0.1:18434/v1") is True
    # Same host, different port: a user's own server — never the guard's.
    assert child_guard.is_managed_endpoint("http://127.0.0.1:8080/v1") is False
    assert child_guard.is_managed_endpoint("") is False
    assert child_guard.is_managed_endpoint(None) is False
