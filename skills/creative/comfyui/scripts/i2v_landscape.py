#!/usr/bin/env python3
"""
i2v_landscape.py — Quick convenience script for landscape image-to-video animations.

Wraps run_workflow.py with sensible defaults for the I2V landscape workflows.

Usage:
    # WanVideo (highest quality)
    ./i2v_landscape.py ~/Pictures/sunset.jpg --prompt "golden hour sunset, gentle clouds drifting"

    # AnimateDiff (fallback — easier setup)
    ./i2v_landscape.py ~/Pictures/mountain.jpg --workflow animate_diff \
        --prompt "mountain landscape, wind through pines"

    # Custom resolution and duration
    ./i2v_landscape.py photo.jpg --width 1024 --height 576 --duration 5s \
        --prompt "cityscape timelapse, clouds moving fast"

    # Run with verbose output
    ./i2v_landscape.py photo.jpg --verbose
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# The workflows directory is a sibling of scripts/ (not inside it)
COMFYUI_SKILLS_DIR = SCRIPT_DIR.parent
RUN_WORKFLOW = SCRIPT_DIR / "run_workflow.py"
WORKFLOWS_DIR = COMFYUI_SKILLS_DIR / "workflows"


def main():
    parser = argparse.ArgumentParser(
        description="Generate a landscape animation from a static image.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s ~/Pictures/sunset.jpg --prompt "golden sunset, gentle clouds"
  %(prog)s ~/Pictures/mountain.jpg --workflow animate_diff --duration 5s
  %(prog)s photo.jpg --width 1024 --height 576 --verbose

For full parameter control, use run_workflow.py directly:
  python3 run_workflow.py --workflow wanvideo-i2v-landscape.md.json \\\n    --mode i2v --image photo.jpg --args '{\"prompt\": \"...\", \"seed\": -1}'
""",
    )
    parser.add_argument("image", help="Path to the source landscape image")
    parser.add_argument("--workflow", choices=["wanvideo", "animate_diff"], default="wanvideo",
                        help="Workflow engine: wanvideo (higher quality) or animate_diff (easier setup)")
    parser.add_argument("--prompt", "-p", default="", help="Motion description for the animation")
    parser.add_argument("--negative-prompt", default="", help="What to avoid in the output")
    parser.add_argument("--width", "-w", type=int, default=832, help="Output width (default: 832)")
    parser.add_argument("--height", "-H", type=int, default=480, help="Output height (default: 480)")
    parser.add_argument("--duration", "-d", default="3.5s",
                        help="Duration in seconds or frames (e.g., '3.5s', '6s', '81'). Default: 3.5s (~24fps→81 frames)")
    parser.add_argument("--steps", type=int, default=30, help="Generation steps (default: 30)")
    parser.add_argument("--cfg", type=float, default=4.5, help="Classifier-free guidance scale")
    parser.add_argument("--seed", "-s", type=int, default=-1, help="Random seed (-1 for random)")
    parser.add_argument("--host", help=f"ComfyUI server URL (default: {os.getenv('COMFYUI_HOST', 'http://10.88.1.168:18188')})")
    parser.add_argument("--output-dir", "-o", default="./outputs/i2v_landscape",
                        help="Output directory for the video (default: ./outputs/i2v_landscape)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose output from run_workflow.py")

    args = parser.parse_args()

    # Resolve image path
    img_path = Path(args.image).expanduser().resolve()
    if not img_path.exists():
        print(f"Error: Image not found: {args.image}", file=sys.stderr)
        return 1

    # Parse duration into frame count (assume 24fps, allow override for raw frame counts)
    duration = args.duration
    if str.isdigit(duration):
        frames = int(duration)
    else:
        seconds = float(duration.rstrip("sS"))
        frames = max(25, min(int(seconds * 24), 160))

    # Build host URL
    host = args.host or os.getenv("COMFYUI_HOST", "http://10.88.1.168:18188")

    # Select workflow file
    if args.workflow == "wanvideo":
        workflow_file = WORKFLOWS_DIR / "wanvideo-i2v-landscape.md.json"
    else:
        workflow_file = WORKFLOWS_DIR / "animate_diff-i2v-landscape.md.json"

    if not workflow_file.exists():
        print(f"Error: Workflow file not found: {workflow_file}", file=sys.stderr)
        return 1

    # Build args JSON
    user_args = {
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "width": args.width,
        "height": args.height,
        "length": frames,
        "steps": args.steps,
        "cfg": args.cfg,
        "seed": args.seed,
    }
    # Filter out empty strings (let defaults handle them)
    user_args = {k: v for k, v in user_args.items() if v and v != ""}

    args_json = json.dumps(user_args)

    # Build the command — run_workflow.py uses --input-image and auto-detects mode from workflow
    cmd = [
        sys.executable, str(RUN_WORKFLOW),
        "--workflow", str(workflow_file),
        "--input-image", str(img_path),
        "--args", args_json,
        "--host", host,
        "--output-dir", args.output_dir,
    ]

    if args.verbose:
        print(f"Running:\n  {' '.join(cmd)}\n")

    # Execute
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
