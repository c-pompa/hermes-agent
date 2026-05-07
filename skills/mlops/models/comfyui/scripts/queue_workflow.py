#!/usr/bin/env python3
"""
ComfyUI remote client. Queues workflows, polls status, fetches outputs.
Reads COMFYUI_URL, CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET from env.

Stdlib only (uses urllib + json) so it works on a stock Python 3.10+ without pip installs.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def _env(name: str, *, required: bool = True) -> str:
    val = os.environ.get(name, "").strip()
    if not val and required:
        sys.exit(f"error: ${name} is not set. Add it to ~/.hermes/.env.")
    return val


def _headers() -> dict[str, str]:
    return {
        "CF-Access-Client-Id": _env("CF_ACCESS_CLIENT_ID"),
        "CF-Access-Client-Secret": _env("CF_ACCESS_CLIENT_SECRET"),
        "User-Agent": "hermes-comfyui-client/1.0",
    }


def _url(path: str) -> str:
    base = _env("COMFYUI_URL").rstrip("/")
    return f"{base}{path}"


def _get(path: str, *, accept_json: bool = True) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(_url(path), headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def _post_json(path: str, payload: dict) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _url(path),
        data=body,
        headers={**_headers(), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post_multipart(path: str, fields: dict[str, str], files: dict[str, Path]) -> tuple[int, bytes]:
    boundary = f"----hermes{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        parts.append(v.encode() + b"\r\n")
    for k, p in files.items():
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{k}"; filename="{p.name}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {ctype}\r\n\r\n".encode())
        parts.append(p.read_bytes())
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        _url(path),
        data=body,
        headers={**_headers(), "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _check_auth(status: int, body: bytes) -> None:
    if status in (301, 302, 401, 403):
        sys.exit(
            "error: HTTP "
            f"{status} from server — most likely Cloudflare Access rejected the request.\n"
            "Confirm CF_ACCESS_CLIENT_ID + CF_ACCESS_CLIENT_SECRET are a service token added to "
            "the Allow policy for comfyui.cpompa.com."
        )
    if status >= 400:
        sys.exit(f"error: HTTP {status}: {body[:500].decode('utf-8', errors='replace')}")


# ---------- subcommands ----------

def cmd_ping(_: argparse.Namespace) -> int:
    status, body, _h = _get("/system_stats")
    _check_auth(status, body)
    info = json.loads(body)
    devs = info.get("devices", [])
    queue_status, queue_body, _ = _get("/queue")
    _check_auth(queue_status, queue_body)
    queue = json.loads(queue_body)
    running = len(queue.get("queue_running", []))
    pending = len(queue.get("queue_pending", []))
    print(f"server: {_env('COMFYUI_URL')}")
    for d in devs:
        print(f"  device: {d.get('name')} (type={d.get('type')}, vram={d.get('vram_total')})")
    print(f"  queue: running={running}, pending={pending}")
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    workflow_path = Path(args.workflow).expanduser()
    if not workflow_path.is_file():
        sys.exit(f"error: workflow file not found: {workflow_path}")
    with workflow_path.open("r", encoding="utf-8") as f:
        workflow = json.load(f)

    if not isinstance(workflow, dict) or not all(
        isinstance(v, dict) and "class_type" in v for v in workflow.values()
    ):
        sys.exit(
            "error: this looks like a UI-format workflow, not API format. "
            "In the ComfyUI UI, choose 'Save (API Format)' and re-export."
        )

    payload = {"prompt": workflow, "client_id": args.client_id or uuid.uuid4().hex}
    status, body = _post_json("/prompt", payload)
    _check_auth(status, body)
    resp = json.loads(body)
    prompt_id = resp.get("prompt_id")
    if not prompt_id:
        sys.exit(f"error: server returned no prompt_id: {resp}")
    print(prompt_id)
    if args.wait:
        return _wait(prompt_id, timeout=args.timeout)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    status, body, _ = _get(f"/history/{urllib.parse.quote(args.prompt_id)}")
    _check_auth(status, body)
    history = json.loads(body)
    entry = history.get(args.prompt_id)
    if entry is None:
        print(json.dumps({"prompt_id": args.prompt_id, "state": "queued_or_unknown"}))
        return 0
    print(json.dumps(entry, indent=2))
    return 0


def _wait(prompt_id: str, *, timeout: int = 600, poll: float = 2.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body, _ = _get(f"/history/{urllib.parse.quote(prompt_id)}")
        _check_auth(status, body)
        history = json.loads(body)
        entry = history.get(prompt_id)
        if entry is not None:
            outputs = entry.get("outputs", {})
            files = []
            for _node_id, out in outputs.items():
                for img in out.get("images", []) or []:
                    files.append(f"{img.get('subfolder', '')}/{img['filename']}@{img.get('type', 'output')}")
                for vid in out.get("videos", []) or []:
                    files.append(f"{vid.get('subfolder', '')}/{vid['filename']}@{vid.get('type', 'output')}")
                for gif in out.get("gifs", []) or []:
                    files.append(f"{gif.get('subfolder', '')}/{gif['filename']}@{gif.get('type', 'output')}")
            err = entry.get("status", {}).get("status_str") if isinstance(entry.get("status"), dict) else None
            if err == "error":
                msgs = entry.get("status", {}).get("messages", [])
                sys.exit(f"workflow errored: {json.dumps(msgs)[:1000]}")
            for f in files:
                print(f)
            return 0
        time.sleep(poll)
    sys.exit(f"timeout: prompt {prompt_id} did not finish in {timeout}s")


def cmd_wait(args: argparse.Namespace) -> int:
    return _wait(args.prompt_id, timeout=args.timeout)


def cmd_output(args: argparse.Namespace) -> int:
    status, body, _ = _get(f"/history/{urllib.parse.quote(args.prompt_id)}")
    _check_auth(status, body)
    history = json.loads(body)
    entry = history.get(args.prompt_id)
    if entry is None:
        sys.exit(f"prompt {args.prompt_id} not found in /history (still queued?)")

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    outputs = entry.get("outputs", {})
    for _node_id, out in outputs.items():
        for kind in ("images", "videos", "gifs"):
            for item in out.get(kind, []) or []:
                params = {
                    "filename": item["filename"],
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output"),
                }
                qs = urllib.parse.urlencode(params)
                status, body, _ = _get(f"/view?{qs}", accept_json=False)
                _check_auth(status, body)
                dest = out_dir / item["filename"]
                dest.write_bytes(body)
                saved.append(dest)

    for p in saved:
        print(p)
    if not saved:
        print("(no output files in history entry)", file=sys.stderr)
        return 1
    return 0


def cmd_upload_image(args: argparse.Namespace) -> int:
    p = Path(args.path).expanduser()
    if not p.is_file():
        sys.exit(f"error: file not found: {p}")
    fields = {"type": args.type, "overwrite": "true" if args.overwrite else "false"}
    if args.subfolder:
        fields["subfolder"] = args.subfolder
    status, body = _post_multipart("/upload/image", fields, {"image": p})
    _check_auth(status, body)
    resp = json.loads(body)
    print(json.dumps(resp))
    return 0


def cmd_object_info(args: argparse.Namespace) -> int:
    path = "/object_info"
    if args.node:
        path = f"/object_info/{urllib.parse.quote(args.node)}"
    status, body, _ = _get(path)
    _check_auth(status, body)
    data = json.loads(body)
    print(json.dumps(data, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="queue_workflow", description=__doc__.strip().splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ping", help="health check + queue depth")
    sp.set_defaults(func=cmd_ping)

    sp = sub.add_parser("submit", help="submit a workflow JSON (API format)")
    sp.add_argument("workflow")
    sp.add_argument("--client-id", default=None)
    sp.add_argument("--wait", action="store_true", help="block until done; print outputs")
    sp.add_argument("--timeout", type=int, default=600)
    sp.set_defaults(func=cmd_submit)

    sp = sub.add_parser("status", help="get history entry for a prompt_id")
    sp.add_argument("prompt_id")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("wait", help="block until prompt finishes; print output filenames")
    sp.add_argument("prompt_id")
    sp.add_argument("--timeout", type=int, default=600)
    sp.set_defaults(func=cmd_wait)

    sp = sub.add_parser("output", help="download a prompt's outputs to a local directory")
    sp.add_argument("prompt_id")
    sp.add_argument("--out", default="./renders")
    sp.set_defaults(func=cmd_output)

    sp = sub.add_parser("upload-image", help="upload an image to use as workflow input")
    sp.add_argument("path")
    sp.add_argument("--type", default="input", choices=["input", "temp"])
    sp.add_argument("--subfolder", default="")
    sp.add_argument("--overwrite", action="store_true")
    sp.set_defaults(func=cmd_upload_image)

    sp = sub.add_parser("object-info", help="dump /object_info (or for a single node class)")
    sp.add_argument("node", nargs="?", default=None)
    sp.set_defaults(func=cmd_object_info)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
