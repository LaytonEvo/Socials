"""Assemble one short golf piece end to end, from a shot list to a disclosed render.

A rehearsal for tasks 3.1 to 3.10 rather than the production pipeline: the shot list is a
literal below rather than generated (3.1), and there is no review step (3.5). What it
does exercise for real is keyframe -> clip -> edit list -> assembly -> disclosure, on
golf content rather than on identity-test prompts.

**The audio is dropped, deliberately.** The video model generates a soundtrack
unconditionally, in an unidentified language nobody chose. Until the voice layer exists
(3.6), silence is the honest output — see `AudioPolicy` in the assembler.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.pipeline.assembler import assemble, edit_list
from app.pipeline.disclosure import apply_disclosure
from app.providers.fal import api_key
from scripts.evaluate_lora import generate as generate_image
from scripts.video_identity_test import submit_clip

ROOT = Path(__file__).resolve().parent.parent

#: The shot list. Golf content, in her clothes, on a course — which is what the persona
#: is for. Each shot is a still prompt and the motion applied to it.
#: The shot list. Golf content, in her clothes, on a course — which is what the persona
#: is for.
#:
#: **Every still prompt states its framing, and that is not decoration.** The first
#: version of this list did not, and the model answered "walking along a fairway" with a
#: wide shot in which her face was a few dozen pixels: face coverage across the piece
#: fell to 0.45 and five frames scored below threshold. The identity layer was fine —
#: there was simply not enough face to measure. Apparent face size is the variable the
#: spike's condition matrix kept finding underneath its other results, and a shot list
#: that leaves it to the model is a shot list that will sometimes produce unmeasurable
#: footage.
SHOTS = [
    {
        "name": "01_intro",
        "still": "a photo of {w}, a young woman in a white golf polo and visor, "
        "head and shoulders, standing on a golf course fairway, smiling at "
        "the camera, golden hour, shallow depth of field",
        "motion": "she looks at the camera and speaks, small natural head movements, "
        "gentle breeze in her hair, camera static",
        "label": "opening — to camera on the fairway",
    },
    {
        "name": "02_walk",
        "still": "a photo of {w}, a young woman in golf clothing carrying a golf bag "
        "over her shoulder, MEDIUM SHOT from the waist up, face clearly "
        "visible and filling much of the frame, walking on a fairway, "
        "trees behind, afternoon light",
        "motion": "she walks forward carrying her bag, camera tracks alongside at the "
        "same height, her face stays in frame",
        "label": "b-roll — walking the fairway",
    },
    {
        "name": "03_swing",
        "still": "a photo of {w}, a young woman in a white golf polo and visor STANDING "
        "UPRIGHT at address over a golf ball, driver in both hands, MEDIUM "
        "SHOT from the waist up, face visible in profile, on the tee",
        "motion": "she takes the club back and swings through, full follow through, "
        "camera static at chest height",
        "label": "the swing",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "piece-golf")
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true", help="reuse what is on disk")
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    artefact = json.loads((ROOT / "spike" / "runs" / "lora" / "artefact.json").read_text())
    guard = BudgetGuard(config.budget, config.providers)

    image_slot, _, _ = guard.price("image", "lora_inference")
    video_slot, _, _ = guard.price("video", "golf")
    scale = float(image_slot.options.get("lora_scale", 1.0))
    seconds = Decimal(str((video_slot.request or {}).get("duration_s", 5)))

    still_cost = guard.estimate("image", "lora_inference", Decimal(len(SHOTS)))
    clip_cost = guard.estimate("video", "golf", seconds * len(SHOTS))
    estimate = still_cost + clip_cost

    print(f"shots         {len(SHOTS)}")
    for s in SHOTS:
        print(f"  {s['name']:<10} {s['label']}")
    print(f"\nkeyframes     {image_slot.model} at scale {scale} = ${still_cost}")
    print(f"clips         {video_slot.model} = ${clip_cost}")
    print(f"ESTIMATE      ${estimate}")
    print("audio         dropped — the model's soundtrack is not a recording of anything")
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0

    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Key {api_key()}"} if api_key() else {}
    client = httpx.Client(timeout=300.0, headers=headers)
    image_base = dict((image_slot.request or {}).get("base") or {})
    video_shape = dict(video_slot.request or {})

    clips: list[tuple[Path, str, str]] = []
    for shot in SHOTS:
        keyframe = args.out / f"{shot['name']}_key.png"
        clip = args.out / f"{shot['name']}.mp4"

        if not (args.skip_generate and keyframe.is_file()):
            prompt = shot["still"].format(w=artefact["trigger_word"])
            print(f"\n[{shot['name']}] keyframe")
            assert image_slot.model is not None
            url = generate_image(
                client, image_slot.model, prompt, artefact["weights_url"], scale, image_base
            )
            keyframe.write_bytes(client.get(url, timeout=180.0).content)
            print(f"  -> {keyframe.name}")

        if not (args.skip_generate and clip.is_file()):
            print(f"[{shot['name']}] clip")
            assert video_slot.model is not None
            url = submit_clip(client, video_slot.model, shot["motion"], keyframe, video_shape)
            clip.write_bytes(client.get(url, timeout=300.0).content)
            print(f"  -> {clip.name} ({clip.stat().st_size / 1048576:.2f} MB)")

        clips.append((clip, f"piece-golf/{shot['name']}", str(shot["label"])))

    edl = edit_list(clips, aspect="9:16")
    print(f"\nedit list     {len(edl.cuts)} cuts, {edl.duration_s:.2f}s, audio={edl.audio}")
    rough = assemble(edl, args.out / "rough.mp4")
    final = apply_disclosure(
        rough.path, args.out / "final.mp4", overlay=config.persona.persona.disclosure.overlay
    )
    print(f"rough         {rough.path.name}")
    print(f"FINAL         {final.path.name}  '{final.disclosure_text}' at {final.position}")
    print(f"              {final.path.stat().st_size / 1048576:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
