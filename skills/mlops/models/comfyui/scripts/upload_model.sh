#!/usr/bin/env bash
# Upload a ComfyUI model file from this Mac to the network ComfyUI server.
#
# Usage: upload_model.sh <type> <local_path>
#   <type> = subdir under .../comfyui_data/models/, e.g.:
#            checkpoints | loras | controlnet | vae | embeddings | clip | clip_vision |
#            upscale_models | animatediff_models | ipadapter | style_models
#
# Reads from environment (typically ~/.hermes/.env, sourced by the Hermes harness):
#   COMFYUI_SSH_HOST       (e.g. 10.88.1.168)
#   COMFYUI_SSH_USER       (e.g. pompa)
#   COMFYUI_MODELS_PATH    (e.g. D:/Docker/comfyui/comfyui_data/models)
#
# Uses rsync over ssh: resumable, skips on size+mtime match. Requires this Mac's pubkey
# to be authorized on the Windows host (~/.ssh/authorized_keys for the SSH user).

set -euo pipefail

usage() {
  cat >&2 <<EOF
Usage: $(basename "$0") <type> <local_path>

Examples:
  $(basename "$0") checkpoints ~/comfyui/models/checkpoints/sd_xl_base_1.0.safetensors
  $(basename "$0") loras ~/Downloads/my-style.safetensors
  $(basename "$0") animatediff_models ~/Downloads/mm_sd_v15_v2.ckpt

Env required:
  COMFYUI_SSH_HOST, COMFYUI_SSH_USER, COMFYUI_MODELS_PATH
EOF
  exit 2
}

[[ $# -eq 2 ]] || usage

TYPE="$1"
SRC="$2"

[[ -f "$SRC" ]] || { echo "error: file not found: $SRC" >&2; exit 1; }

: "${COMFYUI_SSH_HOST:?error: COMFYUI_SSH_HOST not set}"
: "${COMFYUI_SSH_USER:?error: COMFYUI_SSH_USER not set}"
: "${COMFYUI_MODELS_PATH:?error: COMFYUI_MODELS_PATH not set}"

# Whitelist subdirs to avoid path-injection via $TYPE.
case "$TYPE" in
  checkpoints|loras|controlnet|vae|embeddings|clip|clip_vision|\
  upscale_models|animatediff_models|ipadapter|style_models|\
  diffusers|hypernetworks|gligen|photomaker|unet|configs)
    ;;
  *)
    echo "error: unrecognized model type '$TYPE'." >&2
    echo "Allowed: checkpoints loras controlnet vae embeddings clip clip_vision \\" >&2
    echo "         upscale_models animatediff_models ipadapter style_models diffusers \\" >&2
    echo "         hypernetworks gligen photomaker unet configs" >&2
    exit 1
    ;;
esac

DEST_DIR="${COMFYUI_MODELS_PATH%/}/${TYPE}"
DEST="${COMFYUI_SSH_USER}@${COMFYUI_SSH_HOST}:${DEST_DIR}/"

# Make sure the destination dir exists on the server (idempotent).
ssh -o BatchMode=yes -o ConnectTimeout=10 \
  "${COMFYUI_SSH_USER}@${COMFYUI_SSH_HOST}" \
  "powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -Path '${DEST_DIR}' | Out-Null\"" \
  >/dev/null

echo "→ rsync ${SRC} → ${DEST}" >&2
rsync -avh --partial --inplace --info=progress2 \
  -e "ssh -o BatchMode=yes -o ConnectTimeout=10" \
  "$SRC" "$DEST"

BASENAME=$(basename "$SRC")
echo "✔ uploaded: ${TYPE}/${BASENAME}" >&2
echo "  server path: ${DEST_DIR}/${BASENAME}" >&2
echo "  in container: /opt/ComfyUI/models/${TYPE}/${BASENAME}" >&2
