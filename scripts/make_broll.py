"""The brief's shots 2-4: the pitch, and the ball finishing by the hole.

These are a different problem from shot 1, and the difference is the point.

**Nothing here shows her face.** Shot 2-3 is filmed down-the-line from behind her and
shot 4 is tight on the green with nobody in it. So identity cannot be verified, and
`ShotUnderTest.face_expected=False` tells the gate to judge them on the opposite question:
not "is this her" but "is someone here who should not be". A face that turns up in a
cutaway and scores below threshold is a stranger in the piece, which is worse than no face.

**Wardrobe is carried by the keyframe, not by the prompt.** The brief asks for wardrobe,
glove hand, club and lighting locked across all three generations. A clothing change
described in a prompt forces a re-rendered person
(`docs/reports/wardrobe-control-2026-09-28.md`), so each keyframe here is an EDIT of shot
1's keyframe rather than a fresh generation: the same woman in the same clothes, moved to a
new camera position. That is ADR 0015 applied to continuity rather than to identity.

**Take selection has no criterion here.** Swing and identity are both unmeasurable without
a face, so there is nothing to rank on and this does not pretend otherwise: every take is
kept and a human picks. The owner's eye has been the instrument of record all day.
"""

from __future__ import annotations

import argparse
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.identity.dataset import NO_FACE_STILLS, collect, split
from app.identity.embedder import DlibEmbedder
from app.identity.evaluation import holdout_reference
from app.pipeline.acceptance import ShotUnderTest, assess
from app.pipeline.disclosure import apply_disclosure
from app.pipeline.golf import apply_house_style
from app.pipeline.golf import check as check_golf
from app.providers.fal import QUEUE_ROOT, api_key, data_uri

# REFERENCE_ROOT comes from the single-shot script because that is where the spike's data
# layout is declared; the no-face exclusions come from the dataset module that owns them.
from scripts.make_single_shot import REFERENCE_ROOT as REFERENCE_ROOT
from scripts.video_identity_test import submit_clip

ROOT = Path(__file__).resolve().parents[1]

#: The brief's shot list, minus shot 1. Shots 2 and 3 are one clip because the brief says
#: so and is right: a cut between address and strike is a cut across the hardest moment to
#: render, and the model holds a continuous move better than two that must match.
SHOTS: dict[str, dict[str, Any]] = {
    "address_strike": {
        "seconds": 5,
        "edit": (
            "Keep the same woman, the same clothes, the same glove on her lead hand and "
            "the same late afternoon light. Move the camera behind her at hip height, "
            "looking down the line at her back as she stands over the ball with a sand "
            "wedge. The green with its flag sits in the top third of the frame. Her face "
            "is not visible."
        ),
        "motion": (
            "She takes a smooth pitching swing: the club goes back to about waist height, "
            "comes down and brushes the turf as it strikes the ball, and she holds a "
            "balanced finish. Weight stays on her lead side. The camera does not move."
        ),
    },
    "result": {
        "seconds": 5,
        "edit": (
            "Keep the same golf course, the same late afternoon light and the same green "
            "with its flag. Move the camera close to the green, looking across the "
            "putting surface toward the hole, with a single golf ball on the grass short "
            "of it. Nobody is in the frame."
        ),
        "motion": (
            "The ball rolls across the green, slows, and comes to rest close to the hole. "
            "The flag moves slightly in the breeze. The camera pushes in very slightly."
        ),
    },
}


def edit_keyframe(
    client: httpx.Client, slot: Any, source: Path, instruction: str, dest: Path
) -> Path:
    """Move the camera by editing shot 1's keyframe, rather than generating a new scene.

    The source is the frame the finished shot 1 was built from, so wardrobe, light and
    club come along by construction. Describing them in a prompt instead is what produced
    a re-rendered person in `wardrobe-control-2026-09-28`.
    """
    prompt = apply_house_style(instruction)
    for problem in check_golf(prompt):
        raise SystemExit(f"edit prompt contains {problem.rule} — {problem.why}")
    shape = dict(slot.request or {})
    field = str(shape.get("image_field") or "")
    if not field:
        raise SystemExit("image.keyframe declares no request.image_field; a wrong name is a 422")
    payload = data_uri(source)
    arguments: dict[str, Any] = {
        "prompt": prompt,
        field: [payload] if shape.get("image_field_is_list") else payload,
        **dict(shape.get("base") or {}),
    }
    response = client.post(f"{QUEUE_ROOT}/{slot.model}", json=arguments)
    if response.status_code >= 400:
        raise SystemExit(f"keyframe edit failed {response.status_code}: {response.text[:300]}")
    submitted = response.json()
    for _ in range(150):
        if client.get(submitted["status_url"]).json().get("status") in {
            "COMPLETED",
            "FAILED",
            "ERROR",
        }:
            break
        time.sleep(3)
    result = client.get(submitted["response_url"]).json()
    images = result.get("images") or []
    url = (images[0].get("url") if images else None) or (result.get("image") or {}).get("url")
    if not url:
        raise SystemExit(f"edit COMPLETED with no image: {str(result)[:300]}")
    dest.write_bytes(client.get(url, timeout=300.0).content)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "broll")
    parser.add_argument(
        "--from-shot1",
        type=Path,
        default=ROOT / "spike" / "runs" / "shot1-final" / "keyframe.png",
        help="the keyframe shot 1 was built from; wardrobe and light come from here",
    )
    parser.add_argument("--takes", type=int, default=3)
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    guard = BudgetGuard(config.budget, config.providers)
    edit_slot, _, _ = guard.price("image", "keyframe")
    video_slot, _, _ = guard.price("video", "golf")

    seconds = sum(int(s["seconds"]) for s in SHOTS.values())
    estimate = guard.estimate("image", "keyframe", Decimal(len(SHOTS))) + guard.estimate(
        "video", "golf", Decimal(seconds * args.takes)
    )
    print(f"{len(SHOTS)} shots with no face in them, {args.takes} takes each")
    print(f"  keyframe  {edit_slot.model} (editing shot 1's keyframe, so wardrobe carries)")
    print(f"  video     {video_slot.model}")
    print(f"ESTIMATE    ${estimate}")
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0
    if not args.from_shot1.is_file():
        raise SystemExit(f"no shot 1 keyframe at {args.from_shot1}; run make_single_shot first")

    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    embedder = DlibEmbedder(config.providers)
    client = httpx.Client(
        timeout=600.0, headers={"Authorization": f"Key {api_key()}"} if api_key() else {}
    )
    dataset = split(
        collect(
            {k: REFERENCE_ROOT / k for k in ("master_v2", "outfit", "lighting", "body")},
            exclude=NO_FACE_STILLS,
        ),
        trigger_word="mollie",
    )
    reference, _ = holdout_reference(dataset, embedder)
    threshold = float(config.persona.persona.look.identity_threshold_video or 0.0)

    finished: list[ShotUnderTest] = []
    for name, shot in SHOTS.items():
        print(f"\n{name}")
        keyframe = args.out / f"{name}_keyframe.png"
        if not (args.skip_generate and keyframe.is_file()):
            edit_keyframe(client, edit_slot, args.from_shot1, str(shot["edit"]), keyframe)
        print(f"  keyframe  {keyframe.name}")

        assert video_slot.model is not None
        request = dict(video_slot.request or {})
        request["duration_s"] = int(shot["seconds"])
        takes = []
        for index in range(args.takes):
            take = args.out / f"{name}_take_{index}.mp4"
            if not (args.skip_generate and take.is_file()):
                # The last frame is NOT pinned here. Shot 2-3 is a swing: its end state is
                # a finish position, not its start, and forcing a return would undo the
                # shot. Shot 4's ball has to stop by the hole, not roll back.
                url = submit_clip(client, video_slot.model, str(shot["motion"]), keyframe, request)
                take.write_bytes(client.get(url, timeout=300.0).content)
            takes.append(take)
            print(f"  take {index + 1}/{args.takes}  {take.name}")

        # No face means nothing to rank on, so the first take is a placeholder for a human
        # choice rather than a judgement. Every take is kept.
        chosen = takes[0]
        disclosed = apply_disclosure(
            chosen,
            args.out / f"{name}_final.mp4",
            overlay=config.persona.persona.disclosure.overlay,
        )
        print(f"  disclosed {disclosed.path.name}  (take 1 of {len(takes)}; a human picks)")
        finished.append(
            ShotUnderTest(
                name=name,
                path=disclosed.path,
                speaks=False,
                audio_source="none",
                face_expected=False,
            )
        )

    # Judged WITH shot 1, because a piece in which no shot expects a verifiable face is
    # refused — and on their own these two are exactly that piece.
    shot1 = ROOT / "spike" / "runs" / "shot1-final" / "final_captioned.mp4"
    shots = list(finished)
    if shot1.is_file():
        shots.insert(
            0, ShotUnderTest(name="explain", path=shot1, speaks=True, audio_source="voice")
        )
    verdict = assess(
        shots,
        reference=reference,
        embedder=embedder,
        threshold=threshold,
        disclosed=True,
        captioned=True,
    )
    print("\n" + "=" * 70)
    print(verdict.report())
    print("=" * 70)
    return 0 if verdict.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
