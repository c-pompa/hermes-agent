#!/usr/bin/env python3
"""Warm, resident NeuTTS synthesis service.

A one-shot tools/neutts_synth.py run spends most of its wall time loading the
backbone + codec + semantic encoder (~20s on an M5 Pro) and then throws it all
away, because the helper exits to avoid pinning ~500MB in the agent process.
This service loads the model ONCE and keeps it resident, so each request pays
only inference cost.

Endpoints (loopback only — this is a local accelerator, not a network service):

    GET  /health   -> {"status":"ok","ready":bool,"pid":int,"uptime_s":float,...}
    POST /synth    -> body {"text","ref_audio","ref_text","model","device",
                            "language","out"}
                      writes a 24kHz mono WAV to "out", returns
                      {"ok":true,"out":...,"synth_s":float,"total_s":float}

The reference voice is cached by (path, mtime, size), so repeated calls with the
same voice skip re-encoding. Inference is serialized with a lock — llama_cpp
contexts are not safe for concurrent use.

Run:  venv/bin/python tools/neutts_serve.py --model <gguf> --device cpu --preload
"""

import argparse
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODEL_CACHE: dict = {}
REF_CACHE: dict = {}
LOCK = threading.Lock()
START = time.time()
DEFAULT_LANGUAGE = "en-us"


def log(msg: str) -> None:
    print(f"[serve {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _load_tts(model: str, device: str, language):
    """Load and memoize a NeuTTS instance for this (model, device, language)."""
    key = (model, device, language)
    cached = MODEL_CACHE.get(key)
    if cached is not None:
        return cached

    from neutts import NeuTTS

    # llama_cpp only offloads for the literal string "gpu"; torch only accepts
    # "cuda". One --device value cannot satisfy both, so map explicitly.
    backbone_device = "gpu" if device == "cuda" else device
    t0 = time.time()
    tts = NeuTTS(
        backbone_repo=model,
        backbone_device=backbone_device,
        codec_repo="neuphonic/neucodec",
        codec_device=device,
        language=language,
    )
    MODEL_CACHE[key] = tts
    log(f"loaded model={model} device={device} language={language} "
        f"in {time.time() - t0:.1f}s")
    return tts


def _ref_codes(tts, ref_audio: str):
    """Encode the reference voice, memoized on (path, mtime, size)."""
    p = Path(ref_audio).expanduser()
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    cached = REF_CACHE.get(key)
    if cached is not None:
        return cached

    t0 = time.time()
    codes = tts.encode_reference(str(p))
    REF_CACHE.clear()  # keep only the newest reference — bound resident memory
    REF_CACHE[key] = codes
    log(f"encoded reference {p.name} in {time.time() - t0:.1f}s")
    return codes


def _write_wav(path: str, wav, sr: int = 24000) -> None:
    try:
        import soundfile as sf

        sf.write(path, wav, sr)
        return
    except ImportError:
        pass

    import wave

    import numpy as np

    data = np.clip(np.asarray(wav).ravel(), -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(pcm.tobytes())


def synthesize(req: dict) -> dict:
    """Run one synthesis request. Raises on failure (caller maps to HTTP 500)."""
    started = time.time()
    text = req.get("text")
    model = req.get("model")
    out = req.get("out")
    ref_audio = req.get("ref_audio")
    ref_text_path = req.get("ref_text")
    if not (text and model and out and ref_audio and ref_text_path):
        raise ValueError("text, model, out, ref_audio and ref_text are required")

    device = req.get("device") or "cpu"
    language = req.get("language")
    if language is None and os.path.isfile(model):
        # A local GGUF path is absent from BACKBONE_LANGUAGE_MAP and the model is
        # phoneme-input, so the language must be explicit or NeuTTS raises.
        language = DEFAULT_LANGUAGE

    ref_p = Path(ref_audio).expanduser()
    ref_text_p = Path(ref_text_path).expanduser()
    if not ref_p.exists():
        raise FileNotFoundError(f"reference audio not found: {ref_p}")
    if not ref_text_p.exists():
        raise FileNotFoundError(f"reference text not found: {ref_text_p}")
    ref_text = ref_text_p.read_text(encoding="utf-8").strip()

    with LOCK:  # llama_cpp contexts are not concurrency-safe
        tts = _load_tts(model, device, language)
        codes = _ref_codes(tts, ref_audio)
        t0 = time.time()
        wav = tts.infer(text, codes, ref_text)
        synth_s = time.time() - t0

    out_p = Path(out).expanduser()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    _write_wav(str(out_p), wav, 24000)

    return {
        "ok": True,
        "out": str(out_p),
        "synth_s": round(synth_s, 2),
        "total_s": round(time.time() - started, 2),
        "model_was_warm": True,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "neutts-serve/1.0"

    def log_message(self, format, *args):  # noqa: A002 — stdlib signature
        """Silence per-request logging; keep the launchd log readable."""

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler API
        if self.path.split("?")[0] == "/health":
            self._send(200, {
                "status": "ok",
                "ready": bool(MODEL_CACHE),
                "pid": os.getpid(),
                "uptime_s": round(time.time() - START, 1),
                "models": [list(k) for k in MODEL_CACHE],
                "refs_cached": len(REF_CACHE),
            })
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler API
        if self.path.split("?")[0] != "/synth":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, synthesize(req))
        except Exception as exc:  # noqa: BLE001 — report, never kill the server
            log(f"synth failed: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            self._send(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--model", default=os.environ.get("HERMES_NEUTTS_MODEL", ""))
    ap.add_argument("--device", default=os.environ.get("HERMES_NEUTTS_DEVICE", "cpu"))
    ap.add_argument("--language", default=None)
    ap.add_argument("--preload", action="store_true",
                    help="load the model before accepting connections")
    ap.add_argument("--selftest", action="store_true",
                    help="print a sentinel and exit (for health probing)")
    args = ap.parse_args()

    if args.selftest:
        print("NT_SERVE_READY")
        return 0

    if args.preload and args.model:
        language = args.language or (DEFAULT_LANGUAGE if os.path.isfile(args.model)
                                     else None)
        try:
            _load_tts(args.model, args.device, language)
        except Exception as exc:  # noqa: BLE001 — fall back to lazy loading
            log(f"preload failed ({type(exc).__name__}: {exc}); will load lazily")

    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        log(f"cannot bind {args.host}:{args.port} — {exc}")
        return 1

    srv.daemon_threads = True
    log(f"listening on http://{args.host}:{args.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
