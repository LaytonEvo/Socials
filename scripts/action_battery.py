"""What can Mollie actually be shown doing? Measure it, rather than guessing.

Eleven renders out of eleven played a full swing when asked for a pitch, and on the back
of that one failure the product kept getting narrowed — first to "she talks and we cut
away", then to "does she need to swing at all". That narrowing was never measured. The
space between *talking to camera*, which works at 0.97-0.98 identity, and *a full golf
swing*, which has never once worked, is almost entirely untested.

This tests it. One take of each action from a clean, screened keyframe, measured on the
same instruments the gate uses, and a table at the end saying which held together.

**These are measurement takes, not renders.** Nothing here goes through the overlay pass
and nothing is signed, because nothing here is a deliverable — the output is a verdict
about what the model can do, not a video anybody publishes. `cut_piece.py` is what makes
pieces, and it discloses and signs every one.

**Each action keeps her face in frame.** Not an aesthetic choice: ADR 0012 blocks any
shot containing her without a verifiable face, so an action framed from behind would
produce an unmeasurable take and tell us nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import TypedDict, cast

import httpx

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.identity.dataset import NO_FACE_STILLS, collect, split
from app.identity.embedder import DlibEmbedder
from app.identity.evaluation import holdout_reference
from app.pipeline.acceptance import screen_still
from app.pipeline.swing import SwingKind
from app.pipeline.swing import check as check_swing
from app.pipeline.takes import measure
from app.providers.fal import api_key
from app.providers.pose import MediapipePose
from scripts.make_broll import edit_keyframe
from scripts.make_single_shot import REFERENCE_ROOT
from scripts.video_identity_test import submit_clip

ROOT = Path(__file__).resolve().parents[1]

#: Shared by every scene prompt, so wardrobe and light do not become the variable under
#: test. The source keyframe carries them; this only keeps the edit from discarding them.
KEEP = (
    "Keep the same woman, the same white golf clothes, the same glove on her lead hand "
    "and the same late afternoon light. Her face is clearly visible to the camera. "
)


@dataclass
class Result:
    """One measured take, or one action that never got a usable keyframe."""

    action: str
    tests: str
    verdict: str
    take: str | None = None
    coverage: float | None = None
    frames_below: int | None = None
    identity_mean: float | None = None
    roll_swing_deg: float | None = None
    swing_peak: float | None = None


class Action(TypedDict):
    """One thing to try, and what trying it is supposed to settle."""

    scene: str
    motion: str
    #: Declared swing length where a club is swung, so ADR 0016 can judge it. None where
    #: there is no backswing to be wrong about — a wince has no shoulder line to cross.
    swing: str | None
    tests: str


#: Ordered roughly from least to most body motion, which is the axis the swing failure
#: suggests actually matters.
ACTIONS: dict[str, Action] = {
    "hold_up": {
        "scene": KEEP + "She stands on the fairway holding a golf scorecard up beside her "
        "face, looking at the camera. Head and shoulders and hands in frame.",
        "motion": "She holds the scorecard up next to her face, glances at it, raises her "
        "eyebrows at the camera and gives a small shrug. The camera does not move.",
        "swing": None,
        "tests": "a prop held near the face — the smallest motion that is not just talking",
    },
    "react": {
        "scene": KEEP + "She stands on the fairway watching something away to her left, "
        "her face toward the camera, head and shoulders in frame.",
        "motion": "She watches a shot sail away, winces, closes her eyes briefly and puts "
        "one hand over her face, then looks back at the camera. The camera does not move.",
        "swing": None,
        "tests": "expression over motion, which is what the model is demonstrably best at",
    },
    "lean": {
        "scene": KEEP + "She stands on the fairway leaning both hands on the grip of an "
        "upright golf club, whole body in frame, facing the camera.",
        "motion": "She leans on the club, shifts her weight from one foot to the other, "
        "and talks to the camera. The camera does not move.",
        "swing": None,
        "tests": "a whole body at rest with a club in it — the pose the swing shots start from",
    },
    "read_green": {
        "scene": KEEP + "She is crouched down on a putting green behind a golf ball, "
        "looking along the line toward the hole, her face visible in profile to the camera.",
        "motion": "She crouches behind the ball, looks along the line to the hole, then "
        "stands up and steps to the ball. The camera does not move.",
        "swing": None,
        "tests": "crouching and standing — a slow full-body change of posture",
    },
    "putt": {
        "scene": KEEP + "She stands over a golf ball on a putting green with a putter, "
        "addressing it, the hole a few feet away. Whole body in frame, face toward camera.",
        "motion": "She makes a short putting stroke: the putter moves back a few inches "
        "and through, striking the ball, which rolls toward the hole. Her head stays "
        "still. The camera does not move.",
        "swing": "putt",
        "tests": "the smallest real golf stroke — does ANY club motion work, or none",
    },
    "walk": {
        "scene": KEEP + "She is walking along the fairway toward the camera carrying a "
        "golf club, whole body in frame.",
        "motion": "She walks toward the camera carrying the club at her side, looking at "
        "the camera, and stops. The camera does not move.",
        "swing": None,
        "tests": "locomotion — a whole body translating through the frame",
    },
    "celebrate": {
        "scene": KEEP + "She stands on a putting green, face toward the camera, whole "
        "body in frame, a holed putt in front of her.",
        "motion": "She watches the ball drop, then throws both arms up and laughs at the "
        "camera. The camera does not move.",
        "swing": None,
        "tests": "a large, fast motion with no club in it",
    },
    "club_throw": {
        "scene": KEEP + "She stands on the fairway holding a golf club in one hand, "
        "whole body in frame, facing the camera with a resigned expression.",
        "motion": "She looks at the camera, shakes her head, and tosses the club lightly "
        "away to her side with one hand. The camera does not move.",
        "swing": None,
        "tests": "a large fast motion WITH a club — the nearest thing to a swing that is not one",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "battery")
    parser.add_argument(
        "--from-keyframe",
        type=Path,
        default=ROOT / "spike" / "runs" / "shot1-v2" / "keyframe.png",
        help="the clean, seam-screened still every scene is edited from",
    )
    parser.add_argument("--only", nargs="*", choices=sorted(ACTIONS), default=None)
    parser.add_argument("--takes", type=int, default=1)
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument("--keyframe-tries", type=int, default=3)
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()

    chosen = {k: v for k, v in ACTIONS.items() if not args.only or k in args.only}
    config = load_all(ROOT / "config")
    guard = BudgetGuard(config.budget, config.providers)
    edit_slot, _, _ = guard.price("image", "keyframe")
    video_slot, _, _ = guard.price("video", "golf")
    assert video_slot.model is not None

    clips = len(chosen) * args.takes
    estimate = guard.estimate("image", "keyframe", Decimal(len(chosen))) + guard.estimate(
        "video", "golf", Decimal(args.seconds * clips)
    )
    print(f"{len(chosen)} actions x {args.takes} take(s) of {args.seconds}s")
    print(f"  keyframe  {edit_slot.model}   video  {video_slot.model}")
    print(f"ESTIMATE    ${estimate}  (before any keyframe redraws)")
    for name, action in chosen.items():
        print(f"    {name:<12} {action['tests']}")
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0
    if not args.from_keyframe.is_file():
        raise SystemExit(f"no source keyframe at {args.from_keyframe}")

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
    keyframe_bar = float(config.persona.persona.look.identity_threshold_keyframe or threshold)
    pose = MediapipePose(ROOT / str(config.providers.pose.pose_model))

    results: list[Result] = []
    for name, action in chosen.items():
        print(f"\n{name}")
        keyframe = args.out / f"{name}_keyframe.png"
        screen = None
        for attempt in range(1, args.keyframe_tries + 1):
            if not (attempt == 1 and args.skip_generate and keyframe.is_file()):
                edit_keyframe(client, edit_slot, args.from_keyframe, action["scene"], keyframe)
            screen = screen_still(
                keyframe, reference=reference, embedder=embedder, threshold=keyframe_bar
            )
            face = "no face" if screen.score != screen.score else f"{screen.score:.5f}"
            print(f"  keyframe attempt {attempt}: face {face} (bar {keyframe_bar})")
            if screen.passes:
                break
        if screen is None or not screen.passes:
            # Not a failure of the ACTION — the scene never got made. Recorded as such so
            # the table does not blame the motion for something the still never reached.
            print("  keyframe never passed; action not tested")
            results.append(Result(action=name, tests=action["tests"], verdict="no keyframe"))
            continue

        for index in range(args.takes):
            take = args.out / f"{name}_take_{index}.mp4"
            if not (args.skip_generate and take.is_file()):
                request = dict(video_slot.request or {})
                request["duration_s"] = int(args.seconds)
                url = submit_clip(client, video_slot.model, action["motion"], keyframe, request)
                take.write_bytes(client.get(url, timeout=600.0).content)
            identity = measure(
                take,
                embedder._detector,
                embedder._predictor,
                embedder=embedder,
                reference=reference,
            )
            below = identity.frames_below(threshold)
            verdict = (
                "unmeasurable" if identity.coverage < 0.6 else "off-identity" if below else "holds"
            )
            peak: float | None = None
            if action["swing"] is not None:
                swing = check_swing(cast(SwingKind, action["swing"]), pose.frames(take))
                measured = swing.measurement.peak
                peak = round(measured, 2) if measured is not None else None
                if swing.above_shoulder_line:
                    verdict = "wrong stroke"
            row = Result(
                action=name,
                tests=action["tests"],
                verdict=verdict,
                take=take.name,
                coverage=round(identity.coverage, 3),
                frames_below=below,
                identity_mean=round(identity.identity_mean, 5),
                roll_swing_deg=round(identity.roll_swing_deg, 1),
                swing_peak=peak,
            )
            results.append(row)
            print(
                f"  {take.name:<22} cov {identity.coverage:>4.0%}  below {below:>2}  "
                f"mean {identity.identity_mean:.5f}  roll {identity.roll_swing_deg:>5.1f}d  "
                f"{verdict}"
            )

    print("\n" + "=" * 78)
    print(f"{'action':<13} {'verdict':<14} {'cov':>5} {'below':>6} {'identity':>9}  tests")
    for row in results:
        coverage = f"{row.coverage:.0%}" if row.coverage is not None else "--"
        mean = f"{row.identity_mean:.5f}" if row.identity_mean is not None else "--"
        below_text = "--" if row.frames_below is None else str(row.frames_below)
        print(
            f"{row.action:<13} {row.verdict:<14} {coverage:>5} "
            f"{below_text:>6} {mean:>9}  {row.tests[:40]}"
        )
    print("=" * 78)
    holds = [r for r in results if r.verdict == "holds"]
    print(f"\n{len(holds)} of {len(results)} actions hold identity outright.")
    print("Nothing here is disclosed or signed: these are measurements, not renders.")
    (args.out / "battery.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2) + "\n"
    )
    print(f"written     {args.out / 'battery.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
