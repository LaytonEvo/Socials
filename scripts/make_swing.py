"""The swing shot, attempted again — reframed so it can be judged at all.

Withdrawn on 2026-10-01 for two independent reasons, and only one of them was the swing:

1. **It showed her and showed no face.** The brief asks for down-the-line, from behind
   her. The identity scorer reads faces; hair, build and posture are measured nowhere, so
   nothing in this pipeline can confirm a down-the-line shot is her — and the render came
   back as a different woman, which the owner spotted and the gate could not. ADR 0012
   made that BLOCKING, and it still is.
2. **It was a full swing from 30 yards.** Five renders out of five, across two attempts,
   with "the club goes back to about waist height" in the prompt each time. ADR 0016 now
   measures the hands against the shoulder line of the same frame and refuses it.

So this does not re-run the withdrawn shot. **It reframes it front-on, with her face in
shot**, which is the only way a shot containing her can be verified, and then lets both
measurements decide. Neither is a formality: a full swing blocks, and a face that drifts
off-identity blocks.

**What this is a test of.** The clean keyframe (ADR 0018) more than halved head roll on
the talking shot — 19.2 degrees to 10.5, variance 5.8 to 2.1 — which suggests the seam was
feeding the motion model a discontinuity to animate. Whether that also buys a correct
pitch is an open question with five prior failures against it. Every take is measured and
reported, so a run where nothing passes is a result rather than a disappointment.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

import httpx

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.identity.dataset import NO_FACE_STILLS, collect, split
from app.identity.embedder import DlibEmbedder
from app.identity.evaluation import holdout_reference
from app.pipeline.acceptance import ShotUnderTest, assess, screen_still
from app.pipeline.disclosure import apply_disclosure
from app.pipeline.swing import check as check_swing
from app.pipeline.takes import measure
from app.providers.fal import api_key
from app.providers.pose import MediapipePose
from scripts.make_broll import edit_keyframe
from scripts.make_single_shot import REFERENCE_ROOT
from scripts.video_identity_test import submit_clip

ROOT = Path(__file__).resolve().parents[1]

#: Front-on and slightly open, not down-the-line. The brief's camera is behind her, which
#: is exactly the framing nothing here can verify — see the module docstring. Keeping her
#: face in shot is the one change that makes the shot judgeable, and it is a real cost:
#: this is not the shot the brief asked for.
EDIT = (
    "Keep the same woman, the same white golf clothes, the same glove on her lead hand "
    "and the same late afternoon light. She is standing over a golf ball with a sand "
    "wedge, about to play a short pitch. The camera is directly in front of her, about "
    "two metres away at chest height, so she faces the lens. Her whole body is in the "
    "frame and centred. Her head is up and she is looking straight at the camera. One "
    "golf ball only, on the grass by the clubhead. The green with its single flag is in "
    "the distance behind her."
)

#: The motion. The swing length is stated plainly and then MEASURED, because stating it
#: has failed five times out of five.
MOTION = (
    "She plays a short pitch shot. The club goes back only to about waist height, comes "
    "down and brushes the turf as it strikes the ball, and she holds a balanced finish "
    "facing the camera. It is a small controlled swing, not a full swing. Her weight "
    "stays on her lead side. The camera does not move."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "swing-v2")
    parser.add_argument(
        "--from-keyframe",
        type=Path,
        default=ROOT / "spike" / "runs" / "shot1-v2" / "keyframe.png",
        help="the clean, seam-screened keyframe this shot is edited from",
    )
    parser.add_argument("--takes", type=int, default=6)
    parser.add_argument("--keyframe-tries", type=int, default=4)
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    guard = BudgetGuard(config.budget, config.providers)
    edit_slot, _, _ = guard.price("image", "keyframe")
    video_slot, _, _ = guard.price("video", "golf")
    assert video_slot.model is not None

    estimate = guard.estimate("image", "keyframe", Decimal(1)) + guard.estimate(
        "video", "golf", Decimal(args.seconds * args.takes)
    )
    print(f"the swing shot, front-on, {args.takes} takes of {args.seconds}s")
    print(f"  keyframe  {edit_slot.model} (edited from {args.from_keyframe.name})")
    print(f"  video     {video_slot.model}")
    print("  declared  pitch — a full swing BLOCKS (ADR 0016)")
    print("  framing   her face in shot — a faceless shot of her BLOCKS (ADR 0012)")
    print(f"ESTIMATE    ${estimate}")
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0
    if not args.from_keyframe.is_file():
        raise SystemExit(f"no keyframe at {args.from_keyframe}")

    keyframe_tries = int(args.keyframe_tries)
    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(
        timeout=900.0, headers={"Authorization": f"Key {api_key()}"} if api_key() else {}
    )

    embedder = DlibEmbedder(config.providers)
    dataset = split(
        collect(
            {k: REFERENCE_ROOT / k for k in ("master_v2", "outfit", "lighting", "body")},
            exclude=NO_FACE_STILLS,
        ),
        trigger_word="mollie",
    )
    reference, _ = holdout_reference(dataset, embedder)
    threshold = float(config.persona.persona.look.identity_threshold_video or 0.0)
    pose = MediapipePose(ROOT / str(config.providers.pose.pose_model))

    # ----------------------------------------------------------- keyframe --
    # Screened for a VERIFIABLE FACE as well as for a seam, and redrawn until it has one.
    # The first attempt at this shot put her in profile at the edge of the frame with her
    # head down — seam 0.34, perfectly clean, and no face to score. Six takes would have
    # been generated from it and every one would have been refused on identity. ADR 0011
    # exists precisely so that costs $0.08 instead of $1.28; the first version of this
    # script scanned for seams and forgot to use it.
    keyframe_bar = float(config.persona.persona.look.identity_threshold_keyframe or threshold)
    keyframe = args.out / "keyframe.png"
    for attempt in range(1, keyframe_tries + 1):
        if attempt == 1 and args.skip_generate and keyframe.is_file():
            pass
        else:
            edit_keyframe(client, edit_slot, args.from_keyframe, EDIT, keyframe)
        screen = screen_still(
            keyframe, reference=reference, embedder=embedder, threshold=keyframe_bar
        )
        face = "no face found" if screen.score != screen.score else f"{screen.score:.5f}"
        seam_text = f"seam {screen.seam.score:.2f}" if screen.seam else "seam unscanned"
        print(f"keyframe    attempt {attempt}: face {face}, {seam_text} (bar {keyframe_bar})")
        if screen.passes:
            break
        print("            not usable — redrawing rather than paying for takes from it")
    else:
        raise SystemExit(
            f"no keyframe in {keyframe_tries} attempts had a verifiable face at or above "
            f"{keyframe_bar} and no seam. A swing shot that shows her must show her face, "
            f"or nothing downstream can confirm it is her (ADR 0012)."
        )

    request = dict(video_slot.request or {})
    request["duration_s"] = int(args.seconds)
    takes: list[Path] = []
    for index in range(args.takes):
        take = args.out / f"take_{index}.mp4"
        if not (args.skip_generate and take.is_file()):
            # No last-frame pin. The end state of a swing is a finish position, not its
            # start, and forcing a return would undo the shot.
            url = submit_clip(client, video_slot.model, MOTION, keyframe, request)
            take.write_bytes(client.get(url, timeout=600.0).content)
        takes.append(take)
        print(f"  take {index + 1}/{args.takes}  {take.name}")

    print(f"\n{'take':<12} {'peak':>6} {'swing?':<11} {'face':>6} {'below':>6} {'identity':>9}")
    rows: list[tuple[Path, bool, bool]] = []
    for take in takes:
        swing = check_swing("pitch", pose.frames(take))
        identity = measure(
            take, embedder._detector, embedder._predictor, embedder=embedder, reference=reference
        )
        peak = swing.measurement.peak
        verdict = (
            "cannot say"
            if not swing.verifiable
            else "FULL SWING"
            if swing.above_shoulder_line
            else "long"
            if swing.longer_than_declared
            else "pitch"
        )
        swing_ok = swing.verifiable and not swing.above_shoulder_line
        face_ok = identity.coverage >= 0.6 and identity.frames_below(threshold) == 0
        rows.append((take, swing_ok, face_ok))
        print(
            f"{take.name:<12} {(f'{peak:.2f}' if peak is not None else '--'):>6} "
            f"{verdict:<11} {identity.coverage:>5.0%} "
            f"{identity.frames_below(threshold):>6} {identity.identity_mean:>9.5f}"
        )

    usable = [t for t, s, f in rows if s and f]
    print(
        f"\n{len(usable)} of {len(rows)} takes are a pitch AND verifiably her"
        f"  ({sum(1 for _, s, _ in rows if s)} swing-ok, {sum(1 for _, _, f in rows if f)} face-ok)"
    )
    if not usable:
        print(
            "\nNothing to disclose. That is a measured result, not a failed run: the model\n"
            "was told 'only to about waist height' and the renders say otherwise, which is\n"
            "the case for taking the swing from real footage instead."
        )
        return 1

    disclosed = apply_disclosure(
        usable[0], args.out / "final.mp4", overlay=config.persona.persona.disclosure.overlay
    )
    print(f"disclosed   {disclosed.path.name}  (from {usable[0].name})")
    verdict_all = assess(
        [
            ShotUnderTest(
                name="swing",
                path=disclosed.path,
                speaks=False,
                audio_source="none",
                swing="pitch",
            )
        ],
        reference=reference,
        embedder=embedder,
        threshold=threshold,
        disclosed=True,
        pose=pose,
    )
    print("\n" + "=" * 70)
    print(verdict_all.report())
    print("=" * 70)
    return 0 if verdict_all.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
