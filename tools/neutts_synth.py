#!/usr/bin/env python3
"""Standalone NeuTTS synthesis helper with remote-host fallback.

Called by tts_tool.py via subprocess to keep the TTS model (~500MB)
in a separate process that exits after synthesis — no lingering memory.

Host order (first entry that produces audio wins):
    this Mac (local)  ->  desktop2 (WSL2 Ubuntu on DESKTOP-39NF657)  ->  mac mini

Local leads by default: it is the simplest path and measured ~20s here versus
~25-86s for the remote hosts, whose cost is dominated by cold model loading.
The remote hosts remain in the chain as resilience if local cannot synthesize.

Override with --hosts or the HERMES_NEUTTS_HOSTS env var, e.g.
    HERMES_NEUTTS_HOSTS=desktop2,mini,local
Use --local to force on-box synthesis only.

Usage:
    python -m tools.neutts_synth --text "Hello" --out output.wav \
        --ref-audio samples/jo.wav --ref-text samples/jo.txt

Requires: python -m pip install -U neutts[all]
System:   apt install espeak-ng  (or brew install espeak-ng)
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

# --------------------------------------------------------------------------
# Remote host registry
# --------------------------------------------------------------------------
# Each host must have: a neutts-capable python, this same script, a backbone
# GGUF on disk, and a writable staging dir that BOTH the host's shell and our
# scp (from this Mac) can see.
#
# kind == "wsl":   Windows OpenSSH -> PowerShell -> `wsl -e ...` (Ubuntu)
#                  staging_win   = path as scp/Windows sees it
#                  staging_linux = same dir as WSL sees it (/mnt/c/...)
# kind == "posix": plain Unix host; staging_linux is used for both.

REMOTE_HOSTS = {
    "desktop2": {
        "label": "desktop2 (DESKTOP-39NF657, WSL2 Ubuntu-24.04, RTX 3080)",
        "ssh": "pompa@10.88.1.168",
        "kind": "wsl",
        "staging_win": "C:/Users/pompa/neutts-out",
        "staging_linux": "/mnt/c/Users/pompa/neutts-out",
        "python": "/home/pompa/neutts-venv/bin/python",
        "script": "/home/pompa/neutts/neutts_synth.py",
        "model": "/home/pompa/neutts-models/neutts-air-Q4_0.gguf",
        "device": "cpu",
        # Everything the pipeline needs is already in the local HF cache; offline
        # mode drops the per-run revision check against huggingface.co (which
        # otherwise shows up as an "unauthenticated request" warning and couples
        # TTS latency to HF availability). Remove this to fetch new models.
        "env": {"HF_HUB_OFFLINE": "1"},
    },
    "mini": {
        "label": "mac mini (Christians-Mini, arm64)",
        "ssh": "christianpompa@100.73.11.35",
        "kind": "posix",
        "staging_win": None,
        "staging_linux": "/Users/christianpompa/.hermes/neutts-out",
        "python": "/Users/christianpompa/.hermes/voice-venv/bin/python",
        "script": "/Users/christianpompa/.hermes/neutts/neutts_synth.py",
        "model": "/Users/christianpompa/.hermes/models/neutts/neutts-air-Q4_0.gguf",
        "device": "cpu",
        "env": {"HF_HUB_OFFLINE": "1"},
    },
}

DEFAULT_HOST_ORDER = "local,desktop2,mini"
SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=5",
]
PROBE_TIMEOUT = 12      # seconds, per probe ssh call
REMOTE_TIMEOUT = 150    # seconds, for the remote synthesis itself


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _write_wav(path: str, samples, sample_rate: int = 24000) -> None:
    """Write a WAV file from float32 samples (no soundfile dependency)."""
    import numpy as np

    if not isinstance(samples, np.ndarray):
        samples = np.array(samples, dtype=np.float32)
    samples = samples.flatten()

    # Clamp and convert to int16
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)

    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = len(pcm) * (bits_per_sample // 8)

    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, num_channels, sample_rate,
                            byte_rate, block_align, bits_per_sample))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm.tobytes())


# --------------------------------------------------------------------------
# Warm resident service
# --------------------------------------------------------------------------

# A resident tools/neutts_serve.py keeps the model loaded, so a request costs
# only inference (~7s) instead of inference + cold load (~20s). Tried before the
# cold path; if it is not running we simply fall through, never fail.
WARM_URL = os.environ.get("HERMES_NEUTTS_WARM_URL", "http://127.0.0.1:8770")
WARM_TIMEOUT = float(os.environ.get("HERMES_NEUTTS_WARM_TIMEOUT", "180"))


def _warm_enabled() -> bool:
    val = os.environ.get("HERMES_NEUTTS_WARM", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def _try_warm(text: str, out_path: str, ref_audio: str, ref_text_path: str,
              model: str, device: str, language: str | None) -> bool:
    """Synthesize via the resident service if it is up. Never raises.

    Returns True only when audio was actually written to out_path.
    """
    if not _warm_enabled():
        return False

    import urllib.error
    import urllib.request

    # Cheap liveness gate so a wedged/dead service cannot cost us the full
    # synthesis timeout before we fall through to the cold path.
    try:
        with urllib.request.urlopen(f"{WARM_URL}/health", timeout=2) as resp:
            health = json.loads(resp.read() or b"{}")
        if not health.get("ready"):
            return False
    except Exception:  # noqa: BLE001 — service absent is the normal case
        return False

    payload = json.dumps({
        "text": text,
        "ref_audio": ref_audio,
        "ref_text": ref_text_path,
        "model": model,
        "device": device,
        "language": language,
        "out": out_path,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{WARM_URL}/synth", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=WARM_TIMEOUT) as resp:
            body = json.loads(resp.read() or b"{}")
    except Exception as exc:  # noqa: BLE001 — fall through to cold synthesis
        _log(f"neutts: warm service failed ({type(exc).__name__}: {exc}) — using cold path")
        return False

    if not body.get("ok"):
        _log(f"neutts: warm service error: {body.get('error')} — using cold path")
        return False
    if not Path(out_path).exists():
        _log("neutts: warm service reported ok but wrote no file — using cold path")
        return False

    _log(f"neutts: synthesized via warm local service ({body.get('total_s')}s)")
    return True


# --------------------------------------------------------------------------
# Core local synthesis
# --------------------------------------------------------------------------

def _synth_local(text: str, out_path: str, ref_audio: str, ref_text_path: str,
                 model: str, device: str, language: str | None) -> None:
    """Run NeuTTS on this machine and write a WAV to out_path."""
    # llama_cpp (backbone) offloads to GPU only for the literal string "gpu";
    # torch (codec) only accepts "cuda". A single --device value can't satisfy
    # both — "cuda" silently no-ops on the backbone, leaving it on CPU.
    backbone_device = "gpu" if device == "cuda" else device
    codec_device = device

    ref_audio_p = Path(ref_audio).expanduser()
    ref_text_p = Path(ref_text_path).expanduser()
    if not ref_audio_p.exists():
        raise FileNotFoundError(f"reference audio not found: {ref_audio_p}")
    if not ref_text_p.exists():
        raise FileNotFoundError(f"reference text not found: {ref_text_p}")

    ref_text = ref_text_p.read_text(encoding="utf-8").strip()

    try:
        from neutts import NeuTTS
    except ImportError as exc:
        raise RuntimeError(
            "neutts not installed on this host "
            "(python -m pip install -U 'neutts[all]' && pip install torchao==0.17.0)"
        ) from exc

    # Language resolution: with a HF repo id the package derives the language
    # from its internal BACKBONE_LANGUAGE_MAP, but a local GGUF file path is not
    # in that map and phoneme-input models require an explicit language. Default
    # local files to 'en-us' (neutts-air family); explicit --language always wins.
    if language is None and os.path.isfile(model):
        language = "en-us"

    tts = NeuTTS(
        backbone_repo=model,
        backbone_device=backbone_device,
        codec_repo="neuphonic/neucodec",
        codec_device=codec_device,
        language=language,
    )
    ref_codes = tts.encode_reference(str(ref_audio_p))
    wav = tts.infer(text, ref_codes, ref_text)

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    try:
        import soundfile as sf
        sf.write(str(out_p), wav, 24000)
    except ImportError:
        _write_wav(str(out_p), wav, 24000)

    print(f"OK: {out_p}", file=sys.stderr)


# --------------------------------------------------------------------------
# Remote execution
# --------------------------------------------------------------------------

def _run(cmd, timeout: float):
    """Run a command, returning (returncode, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, encoding="utf-8",
                           errors="replace")
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except OSError as exc:
        return 127, "", str(exc)


def _ssh(host: str, remote_cmd: str, timeout: float = PROBE_TIMEOUT):
    return _run(["ssh", *SSH_OPTS, host, remote_cmd], timeout)


def _scp(srcs, dst: str, timeout: float = 60):
    return _run(["scp", *SSH_OPTS, "-q", *[str(s) for s in srcs], dst], timeout)


def _remote_cmd(spec: dict, tail: str) -> str:
    """Build a remote command line for a host.

    `wsl -e` execs directly with no shell, so a `VAR=val cmd` prefix would not
    be parsed — route env through the `env` binary instead. Quote-free by
    design: the string travels bash -> PowerShell -> wsl, so avoid nested
    quoting entirely.
    """
    env = spec.get("env") or {}
    prefix = ""
    if env:
        prefix = "env " + " ".join(f"{k}={v}" for k, v in env.items()) + " "
    if spec["kind"] == "wsl":
        return f"wsl -e {prefix}{tail}"
    return f"{prefix}{tail}"


def _host_probe(spec: dict) -> bool:
    """Cheap reachability + provisioning check.

    Runs the host's own python with --selftest and parses stdout for a sentinel.
    We deliberately do NOT trust the remote exit status: some hosts (the mac
    mini over Tailscale) return 0 even for a failed command. This also proves
    the interpreter path itself exists — a bare `test -f` would not.
    """
    cmd = _remote_cmd(spec, f"{spec['python']} {spec['script']} --selftest --model {spec['model']}")
    rc, out, _ = _ssh(spec["ssh"], cmd, timeout=PROBE_TIMEOUT)
    return "NT_READY" in (out or "")


def _host_staging(spec: dict) -> str:
    return spec["staging_win"] or spec["staging_linux"]


def _try_remote(host_key: str, spec: dict, text: str, out_path: str,
                ref_audio: str, ref_text_path: str) -> bool:
    """Attempt synthesis on a remote host. Returns True on success."""
    label = spec.get("label", host_key)

    if not _host_probe(spec):
        _log(f"neutts: {label} not available (probe failed) — trying next")
        return False

    rid = uuid.uuid4().hex[:12]
    stag_lin = spec["staging_linux"]
    stag_win = _host_staging(spec)
    remote_wav = f"{stag_lin}/nt-{rid}.wav"
    remote_ref_audio = f"{stag_lin}/ref-{rid}{Path(ref_audio).suffix}"
    remote_ref_text = f"{stag_lin}/ref-{rid}.txt"

    with tempfile.TemporaryDirectory() as td:
        # Stage the reference voice + request on the host so the voice is
        # identical everywhere (and custom reference voices work remotely).
        staged_ref_audio = Path(td) / Path(remote_ref_audio).name
        staged_ref_text = Path(td) / Path(remote_ref_text).name
        shutil.copyfile(Path(ref_audio).expanduser(), staged_ref_audio)
        shutil.copyfile(Path(ref_text_path).expanduser(), staged_ref_text)

        request = {
            "text": text,
            "out": remote_wav,
            "ref_audio": remote_ref_audio,
            "ref_text": remote_ref_text,
            "model": spec["model"],
            "device": spec["device"],
        }
        req_file = Path(td) / f"req-{rid}.json"
        req_file.write_text(json.dumps(request), encoding="utf-8")
        remote_req = f"{stag_lin}/{req_file.name}"

        # Ensure the staging dir exists (mkdir is a real binary; no shell needed).
        _ssh(spec["ssh"], f"wsl -e mkdir -p {stag_lin}" if spec["kind"] == "wsl"
             else f"mkdir -p {stag_lin}", timeout=PROBE_TIMEOUT)

        rc, _, err = _scp([staged_ref_audio, staged_ref_text, req_file],
                          f"{spec['ssh']}:{stag_win}/", timeout=60)
        if rc != 0:
            _log(f"neutts: {label} staging failed: {err.strip()[:200]} — trying next")
            return False

        remote_cmd = _remote_cmd(spec, f"{spec['python']} {spec['script']} --request {remote_req}")

        rc, _, err = _ssh(spec["ssh"], remote_cmd, timeout=REMOTE_TIMEOUT)
        if rc != 0:
            _log(f"neutts: {label} synthesis failed (rc={rc}): {err.strip()[-300:]} — trying next")
            return False

        rc, _, err = _scp([f"{spec['ssh']}:{stag_win}/nt-{rid}.wav"], out_path, timeout=60)
        if rc != 0:
            _log(f"neutts: {label} fetch failed: {err.strip()[:200]} — trying next")
            return False

    _log(f"neutts: synthesized on {label}")
    return True


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def _parse_hosts(raw: str | None) -> list[str]:
    if raw:
        order = [h.strip() for h in raw.split(",") if h.strip()]
    else:
        order = [h.strip() for h in
                 os.environ.get("HERMES_NEUTTS_HOSTS", DEFAULT_HOST_ORDER).split(",")
                 if h.strip()]
    return order or ["local"]


def _run_request(path: str) -> int:
    """Remote-side entry point: synthesize from a JSON request. Never dispatches."""
    req = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        _synth_local(
            text=req["text"],
            out_path=req["out"],
            ref_audio=req["ref_audio"],
            ref_text_path=req["ref_text"],
            model=req["model"],
            device=req.get("device", "cpu"),
            language=req.get("language"),
        )
    except Exception as exc:  # noqa: BLE001 — surface as a clean remote error
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _selftest(model: str | None) -> int:
    """Host provisioning check used by the dispatcher's probe.

    Prints a sentinel on stdout so the caller can key off output rather than
    the remote exit status (the mac mini does not propagate exit codes).
    """
    import importlib.util

    problems = []
    if model and os.path.isfile(model):
        pass
    elif model and not os.path.isfile(model):
        problems.append(f"model missing: {model}")
    if importlib.util.find_spec("neutts") is None:
        problems.append("python package 'neutts' not importable")
    if importlib.util.find_spec("llama_cpp") is None:
        problems.append("python package 'llama_cpp' not importable")

    if problems:
        for p in problems:
            print(f"selftest: {p}", file=sys.stderr)
        print("NT_NOPE")
        return 1
    print("NT_READY")
    return 0


def main():
    parser = argparse.ArgumentParser(description="NeuTTS synthesis helper (remote-fallback)")
    parser.add_argument("--text", help="Text to synthesize (required unless --request)")
    parser.add_argument("--out", help="Output WAV path (required unless --request)")
    parser.add_argument("--ref-audio", help="Reference voice audio path")
    parser.add_argument("--ref-text", help="Reference voice transcript path")
    parser.add_argument("--model", default="neuphonic/neutts-air-q4-gguf",
                        help="HuggingFace backbone model repo OR local GGUF path")
    parser.add_argument("--language", default=None,
                        help="eSpeak language code (default: derived from model repo; "
                             "'en-us' for local GGUF file paths, which are not in the "
                             "package's repo->language map)")
    parser.add_argument("--device", default="cpu", help="Device (cpu/cuda/mps)")
    parser.add_argument("--hosts", default=None,
                        help="Comma-separated host order, e.g. 'desktop2,mini,local'. "
                             "Env: HERMES_NEUTTS_HOSTS")
    parser.add_argument("--local", action="store_true",
                        help="Skip remote hosts; synthesize on this machine only")
    parser.add_argument("--request", default=None,
                        help="Execute synthesis from a JSON request file (remote-side)")
    parser.add_argument("--selftest", action="store_true",
                        help="Check this host is provisioned; prints NT_READY/NT_NOPE")
    args = parser.parse_args()

    # Provisioning probe (used by the dispatcher). Must run before anything else
    # so a bare host can answer without any model loaded.
    if args.selftest:
        return _selftest(args.model)

    # Remote-side mode: execute and exit. Never dispatch (avoids recursion).
    if args.request:
        return _run_request(args.request)

    if not args.text or not args.out:
        parser.error("--text and --out are required")

    out_path = args.out
    if not out_path.endswith(".wav"):
        out_path = out_path.rsplit(".", 1)[0] + ".wav"

    # tts_tool.py resolves empty refs to the bundled samples before calling us;
    # mirror that here so the script is also safe to invoke directly.
    _here = Path(__file__).resolve().parent
    ref_audio = args.ref_audio or str(_here / "neutts_samples" / "jo.wav")
    ref_text_path = args.ref_text or str(_here / "neutts_samples" / "jo.txt")

    # ---- walk the host order; "local" is a real position in the chain ----
    # Ordered fallback: the first entry that produces audio wins. Local is the
    # default first choice because it is both simplest and fastest on this Mac
    # (~20s) versus the remote hosts (~25-86s, dominated by cold model load);
    # the remotes remain as resilience if local cannot synthesize.
    order = ["local"] if args.local else _parse_hosts(args.hosts)
    for key in order:
        if key == "local":
            # Prefer the resident service; it skips the ~13s cold model load.
            if _try_warm(args.text, out_path, ref_audio, ref_text_path,
                         args.model, args.device, args.language):
                return 0
            _log("neutts: synthesizing locally on this Mac (cold start)")
            try:
                _synth_local(args.text, out_path, ref_audio, ref_text_path,
                             args.model, args.device, args.language)
                return 0
            except Exception as exc:  # noqa: BLE001 — keep walking the chain
                _log(f"neutts: local synthesis raised {type(exc).__name__}: {exc} — trying next")
                continue
        spec = REMOTE_HOSTS.get(key)
        if not spec:
            _log(f"neutts: unknown host '{key}' in host order — skipping")
            continue
        try:
            if _try_remote(key, spec, args.text, out_path, ref_audio, ref_text_path):
                return 0
        except Exception as exc:  # noqa: BLE001 — a broken host must not kill TTS
            _log(f"neutts: {key} raised {type(exc).__name__}: {exc} — trying next")

    print("Error: no host in the voice chain could synthesize audio", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
