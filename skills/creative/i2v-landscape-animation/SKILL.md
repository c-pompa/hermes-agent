---
name: i2v-landscape-animation
description: Image-to-video landscape animations using WanVideo or AnimateDiff on ComfyUI. Automates creating short animated clips from static photos.
category: creative
tags: [comfyui, video-generation, image-to-video, wanvideo, animatdiff]
---

# I2V Landscape Animation Skill

Automates generating short landscape animations from static images using either WanVideo 14B (highest quality) or AnimateDiff + IPAdapter (easier setup).

## Prerequisites

### Hardware Requirements
- RTX 3070 minimum for AnimateDiff; RTX 4090/A6000 recommended for WanVideo 14B fp8
- VRAM: 16 GB (AnimateDiff) or 24 GB (WanVideo fp8)

### Software Setup
The ComfyUI instance must be running (ai-dock image, server-internal HTTP port). For SSH access to the host (model uploads, container restarts), see `skills/mlops/models/comfyui/SKILL.md` — that skill documents the env-var setup (`COMFYUI_SSH_HOST`, `COMFYUI_SSH_USER`) and assumes the Mac's pubkey is already authorized on the host. **Do not hardcode credentials in this file.**

### Model Requirements

**WanVideo I2V (preferred, highest quality):**
- `wanvideo_i2v_14b_fp8.safetensors` → models/diffusion_models/ (~6 GB)
- `siglip_vision_transformer_patch16_384.safetensors` → models/clip_vision/ (~1.5 GB)
- `wanvae_bf16.safetensors` → models/vae/

**AnimateDiff I2V (fallback, easier setup):**
- SDXL checkpoint → models/checkpoints/
- `mm_sdxl_v10_beta.safetensors` → models/animatediff_models/
- IPAdapter model → models/ipadapter/ (SDXL or SD1.5 variant)

## Quick Start (Convenience Script)

```bash
# WanVideo with defaults
./scripts/i2v_landscape.py ~/Pictures/mountain.jpg \
  --prompt "golden hour light, gentle clouds drifting"

# AnimateDiff with longer duration
./scripts/i2v_landscape.py ~/Pictures/forest.jpg \
  --workflow animate_diff --duration 6s \
  --prompt "breeze through pine trees, leaves rustling"

# Custom resolution (1080p-ish)
./scripts/i2v_landscape.py ~/Pictures/lake.jpg \
  --width 1920 --height 1080 --duration 5s \
  --prompt "calm lake with ripples, overcast sky"
```

## Advanced Usage (Full Control)

### WanVideo I2V
```bash
python3 scripts/run_workflow.py \
  --workflow workflows/wanvideo-i2v-landscape.md.json \
  --mode i2v \
  --image ~/Pictures/photo.jpg \
  --args '{\"prompt\": \"cinematic landscape, slow pan right, atmospheric lighting\", \"seed\": -1}' \
  --host http://10.88.1.168:8190 \
  --output-dir ./outputs
```

### AnimateDiff I2V
```bash
python3 scripts/run_workflow.py \
  --workflow workflows/animate_diff-i2v-landscape.md.json \
  --mode i2v \
  --image ~/Pictures/photo.jpg \
  --args '{\"prompt\": \"peaceful landscape, gentle wind movement\", \"seed\": -1}' \
  --host http://10.88.1.168:8190 \
  --output-dir ./outputs
```

### Auto-detect Mode (simpler)
```bash
python3 scripts/run_workflow.py \
  --workflow workflows/wanvideo-i2v-landscape.md.json \
  --image ~/Pictures/photo.jpg \
  --args '{\"prompt\": \"mountain view, clouds moving slowly\"}' \
  --output-dir ./outputs
```

## Parameter Reference

| Parameter | Default | Notes |
|-----------|---------|-------|
| `width` | 832 | Resolution width (keep even numbers) |
| `height` | 480 | Resolution height — keep aspect ratio like the photo |
| `length` | 81 | Frame count (~3.5s at 24fps). Keep under 81 for RTX 3070 VRAM safety |
| `steps` | 30 | Quality vs speed tradeoff; 20-40 is typical for I2V |
| `cfg` | 4.5 | Classifier-free guidance — lower values are more creative |
| `prompt` | (see defaults) | Describe the desired motion, not just the scene |

## Tips for Better Results

1. **Source image quality:** Use high-resolution photos (at least 832×480). Upscale first if needed.

2. **Motion descriptions:** Be specific about the kind of motion:
   - Camera: "slow pan right", "gentle zoom in"
   - Environment: "clouds drifting", "wind through trees", "water rippling"
   - Lighting: "golden hour glow", "dappled sunlight"

3. **Negative prompts:** Avoid "static, frozen, still image, no movement" — let the model know you want animation.

4. **WanVideo vs AnimateDiff:**
   - WanVideo: Better quality, true I2V semantics, requires fp8 checkpoint + SigLIP vision encoder
   - AnimateDiff: Easier setup with existing SDXL models, uses IPAdapter for reference conditioning, may produce more stylized results

5. **Batch processing:** Combine with a loop to generate multiple variations:
   ```bash
   for prompt in "slow pan right" "gentle zoom in" "clouds drifting"; do
     ./scripts/i2v_landscape.py photo.jpg --prompt "$prompt" --seed $RANDOM
   done
   ```

## Troubleshooting

- **"No LoadImage or I2V node found":** The workflow file doesn't contain a LoadImage node. Use `--mode i2v` explicitly with the correct workflow path.
- **Out of memory:** Reduce `length` (frame count) and/or lower resolution. RTX 3070 has 8GB VRAM — consider using AnimateDiff if WanVideo OOMs.
- **Auth redirect failure on Comfy Cloud:** If running on cloud, ensure port 1111 or 18189 is mapped in the docker run command for auth proxy access.
