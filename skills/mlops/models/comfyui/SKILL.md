---
name: comfyui-remote
description: Run ComfyUI workflows against the user's network ComfyUI server (RTX 3070, gated by Cloudflare Access). Queues workflows via the HTTP API, uploads missing models on demand via SCP, retrieves rendered outputs. Use when the user asks for image/video generation, mentions ComfyUI, AnimateDiff, SDXL, or wants to offload GPU-heavy diffusion work from the local machine.
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [ComfyUI, Image Generation, Video Generation, AnimateDiff, Stable Diffusion, Remote GPU]

---

# ComfyUI Remote (network 3070)

Operational wrapper for the user's home-lab ComfyUI server. The server runs in Docker on Windows behind a Cloudflare Tunnel + Cloudflare Access gate at `https://comfyui.cpompa.com`. This skill submits workflows, fetches outputs, and uploads any missing models the workflow needs.

**Picking between this skill and `skills/creative/comfyui/`:** the creative skill is the general-purpose ComfyUI playbook (sample workflows, dep/health checks, schema extraction). Use it for *building* a workflow, learning ComfyUI mechanics, or driving a local install. Use **this** skill the moment the user wants the work done on the network 3070 (auth headers, model upload over SSH, the user's specific custom-node inventory). The two are designed to coexist — load workflows / generate JSON via the creative skill, then submit via this skill's `queue_workflow.py`.

The local Mac install of ComfyUI is still preferred for **prototyping and quick iteration** on MPS. Switch to remote when:
- Workflow needs a GPU larger than the Mac's MPS can comfortably run (SDXL at high res, AnimateDiff, video diffusion).
- A long batch is queued and you don't want to tie up the Mac.
- The model already lives on the server (no upload cost).

For **interactive UI work** (building/editing a workflow visually), the user should open `https://comfyui.cpompa.com` in their browser — Cloudflare Access OTP login, then full ComfyUI UI loads. This skill is for programmatic / "run this workflow for me" requests.

## Server inventory

Custom nodes available on the server (no need to install):
- `ComfyUI-Manager` — runtime install of more nodes
- `rgthree-comfy` — quality-of-life nodes
- `ComfyUI-Custom-Scripts` — pysssss extras
- `ComfyUI-Crystools` — system stats overlay
- `ComfyUI-AnimateDiff-Evolved` — AnimateDiff video generation
- `ComfyUI-VideoHelperSuite` — video import/export
- `ComfyUI-Impact-Pack` — detector/segmentation pipeline (SAM 1 / `segment-anything` only; SAM-2 was removed, torch pinned at 2.4.1+cu121 due to ai-dock NCCL incompatibility)

GPU: NVIDIA RTX 3070 via NVIDIA Docker runtime. Single GPU, single user — there is no per-user isolation in ComfyUI, so concurrent jobs share the queue.

## Environment contract

The skill scripts read these from the environment (typically `~/.hermes/.env`):

```
COMFYUI_URL=https://comfyui.cpompa.com
CF_ACCESS_CLIENT_ID=<service-token client id>.access
CF_ACCESS_CLIENT_SECRET=<service-token client secret>
COMFYUI_SSH_HOST=10.88.1.168           # LAN IP; use comfyui-host.cpompa.com if off-LAN
COMFYUI_SSH_USER=pompa
COMFYUI_MODELS_PATH=D:/Docker/comfyui/comfyui_data/models
```

`CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET` are a Cloudflare Access service token added to the Allow policy for `comfyui.cpompa.com`. Without them, every API call returns a Cloudflare login redirect.

## Scripts

### `scripts/queue_workflow.py`

Thin Python CLI over the ComfyUI HTTP API. Always prepends the CF Access headers. Subcommands:

```bash
# Submit a workflow JSON file (API format, not UI format) and print the prompt_id
python3 queue_workflow.py submit path/to/workflow.json

# Poll status of a queued prompt
python3 queue_workflow.py status <prompt_id>

# Block until prompt finishes; print the list of output filenames
python3 queue_workflow.py wait <prompt_id> [--timeout 600]

# Download all outputs of a finished prompt to a local directory
python3 queue_workflow.py output <prompt_id> --out ./renders/

# Upload an image to be used as a workflow input (LoadImage node)
python3 queue_workflow.py upload-image path/to/input.png

# Inspect what models / nodes the server currently exposes
python3 queue_workflow.py object-info [NodeClassName]

# Quick health check (returns CUDA device info if reachable)
python3 queue_workflow.py ping
```

Workflows must be in **API format** — that's what `Save (API Format)` produces in the ComfyUI UI, NOT the default `Save` (which is the editor-only graph). If the user gives you a UI-format workflow, ask them to re-export.

### `scripts/upload_model.sh`

Bridges the gap that ComfyUI's HTTP API doesn't cover — model files (`.safetensors`, `.ckpt`, `.pt`) must land on the server's filesystem before they appear in `/object_info`.

```bash
# Usage: upload_model.sh <type> <local_path>
# <type> is the subdir under .../models: checkpoints | loras | controlnet | vae | embeddings | clip | clip_vision | upscale_models | animatediff_models | ...

bash upload_model.sh checkpoints ~/comfyui/models/checkpoints/sd_xl_base_1.0.safetensors
bash upload_model.sh loras ~/Downloads/my-style-lora.safetensors
bash upload_model.sh animatediff_models ~/Downloads/mm_sd_v15_v2.ckpt
```

Uses rsync over ssh (resumable, skips if size+mtime match). Requires the Mac's pubkey to be authorized on the Windows host (`pompa@10.88.1.168`).

After upload the server sees the file immediately (host directory is bind-mounted into the container at `/opt/ComfyUI/models/`). For some node types ComfyUI caches the model list — call `python3 queue_workflow.py object-info CheckpointLoaderSimple` to verify the new file appears, or restart the container if needed.

## Bundled workflows

Two known-working API-format workflows live under `workflows/`. Both are minimal SD 1.5 text-to-image graphs (`CheckpointLoaderSimple → CLIPTextEncode×2 → KSampler → VAEDecode → SaveImage`) — small enough to read in one screen, fast enough to run as smoke tests on the 3070 (~10-30 s each).

- `workflows/realistic-portrait.json` — uses `v1-5-pruned-emaonly.safetensors` (SD 1.5 base). Photorealistic prompt. Output prefix `realistic-portrait`.
- `workflows/anime-portrait.json` — uses `Counterfeit-V3.0_fp16.safetensors`. Anime-style prompt. Output prefix `anime-portrait`.

To run a workflow end-to-end (submit, wait, fetch):

```bash
python3 scripts/queue_workflow.py submit workflows/realistic-portrait.json --wait
# captures prompt_id, blocks until done, prints output filename
python3 scripts/queue_workflow.py output <prompt_id> --out ./renders/
```

Either checkpoint can be uploaded via `scripts/upload_model.sh checkpoints <local_path>` (rsync from the Mac), or pulled server-side via ComfyUI Manager / a direct download to `D:/Docker/comfyui/comfyui_data/models/checkpoints/`. To swap to a different checkpoint, edit the `ckpt_name` field in node `"4"`.

## Standard workflow

When the user asks "render X with model Y":

1. **Check model availability** — `queue_workflow.py object-info <LoaderClass>` and look for `Y` in the file list. If absent:
   - Ask the user where Y lives on the Mac (likely `~/Documents/comfy/ComfyUI/models/<type>/Y`).
   - `upload_model.sh <type> <path>`.
2. **Submit** — `queue_workflow.py submit workflow.json` → captures `prompt_id`.
3. **Wait** — `queue_workflow.py wait <prompt_id>` (it'll print outputs when done; failure modes raise non-zero).
4. **Fetch** — `queue_workflow.py output <prompt_id> --out ./renders/`.
5. **Hand back** — give the user the local file path(s). Open the first image with the OS default viewer if the user wants to see it immediately.

## Troubleshooting

**302 redirect to `cpompa.cloudflareaccess.com`** — service-token headers missing or wrong. Confirm `$CF_ACCESS_CLIENT_ID` ends in `.access` and `$CF_ACCESS_CLIENT_SECRET` is the secret (not the id). Re-issue the token if the secret was lost — Cloudflare only shows it once.

**`KeyError: 'prompt'` from /api/prompt** — workflow is in UI format, not API format. Re-export from the ComfyUI UI with `Save (API Format)`.

**Workflow queues but errors `<model>.safetensors not found`** — server doesn't have the model. Re-run `object-info`; if absent, upload via `upload_model.sh`. If present but error persists, ComfyUI may have a cached model list — ssh in and `docker restart comfyui-rtx`.

**Upload over LAN is slow** — confirm `COMFYUI_SSH_HOST=10.88.1.168` (not the public hostname). Public hostname routes through the Cloudflare Tunnel which has lower throughput.

**Workflow takes much longer than expected** — check if someone else is using the GPU: `queue_workflow.py ping` returns queue length. There is no multi-tenant isolation; jobs serialize.

## Local fallback

If the network ComfyUI is unreachable (server off, tunnel down), fall back to the Mac's local ComfyUI at `~/Documents/comfy/ComfyUI` (richer custom_nodes than `~/git-repos/ComfyUI`). The Mac install runs on MPS — slower for SDXL but fine for SD 1.5 / quick iteration. Don't try to "fall back" automatically mid-job; ask the user first.
