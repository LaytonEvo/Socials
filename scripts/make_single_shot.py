"""One unbroken shot, gated before it is shown to anyone.

Every defect in the three-shot pieces was a MULTI-SHOT defect: wardrobe changing between
cuts, hair changing, her apparent height changing, identity holding in one scene and not
the next, a sound stage invented for b-roll putting a voice back in. None of those exist
in a single take.

So this makes one shot, end to end, and runs it past `acceptance.assess` before it is
called finished. A piece that fails is refused here rather than by the owner watching
it, which is the only reason any of the earlier ones were caught.

Takes are generated and chosen on measured head stability before anything is synced —
the sync costs eight times what a take does, so choosing first is the cheap order.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.identity.dataset import NO_FACE_STILLS, collect, split
from app.identity.embedder import DlibEmbedder
from app.identity.evaluation import holdout_reference
from app.pipeline.acceptance import ShotUnderTest, StillScreen, assess, best_still, screen_still
from app.pipeline.assembler import duration_of
from app.pipeline.disclosure import apply_disclosure
from app.pipeline.fidelity import detail_pass, require_identity_preserved
from app.pipeline.golf import apply_house_style
from app.pipeline.golf import check as check_golf
from app.pipeline.lipsync import lip_sync, should_lip_sync
from app.pipeline.takes import best_take, measure
from app.pipeline.voice import pad_to
from app.providers.fal import QUEUE_ROOT, api_key
from app.storage.keys import key_for
from app.storage.s3 import S3Storage, bucket_from_env
from scripts.evaluate_lora import generate as generate_image
from scripts.train_lora import persona_storage_id
from scripts.video_identity_test import submit_clip

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ROOT = ROOT / "spike" / "data"

#: The shot. One framing, one wardrobe, one thing said.
#:
#: Her line is golf, specific, and from her own round — ADR 0009 constrains register,
#: not subject: a 14 handicap, "not a coach, not a pro", never instructing.
SHOT = {
    "still": (
        "a photo of {w}, a young woman in a white golf polo and white visor, "
        "head and shoulders, standing on a golf course fairway, looking at the camera, "
        "warm late afternoon light, shallow depth of field"
    ),
    "motion": (
        "she looks into the lens and talks to camera. Her head stays completely still "
        "and upright throughout, no tilting, no turning, no nodding. Shoulders still. "
        "Only her lips and her hair move. Camera locked off."
    ),
    "line": (
        "Right, first tee, and there's water left the whole way down. "
        "Which is exactly where I'm going to hit it."
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "single")
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--takes", type=int, default=4)
    parser.add_argument("--keyframes", type=int, default=4)
    parser.add_argument("--seconds", type=int, default=None, help="5-15; the brief's shot 1 is 6")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    look = config.persona.persona.look
    threshold = float(look.identity_threshold_video or look.identity_threshold or 0)
    artefact = json.loads((ROOT / "spike" / "runs" / "lora" / "artefact.json").read_text())
    guard = BudgetGuard(config.budget, config.providers)

    image_slot, _, _ = guard.price("image", "lora_inference")
    detail_slot, _, _ = guard.price("image", "detail_pass")
    video_slot, _, _ = guard.price("video", "golf")
    voice_slot, _, _ = guard.price("voice", "primary")
    sync_slot, _, _ = guard.price("lipsync", "primary")
    # The brief's shot 1 is six seconds. The model takes 5 to 15 inclusive (ADR 0013
    # corrected a config note that read as "only 5"), so this is a real choice rather than
    # the one value available — and a longer shot is HARDER, because the gate's verdict
    # rests on the worst frame and a longer clip offers more frames to be worst.
    seconds = Decimal(str(args.seconds or (video_slot.request or {}).get("duration_s", 5)))
    video_request = dict(video_slot.request or {})
    video_request["duration_s"] = int(seconds)

    estimate = (
        guard.estimate("image", "lora_inference", Decimal(args.keyframes))
        + guard.estimate("image", "detail_pass", Decimal(1))
        + guard.estimate("video", "golf", seconds * args.takes)
        + guard.estimate("voice", "primary", Decimal(len(SHOT["line"])) / Decimal(1000))
        + guard.estimate("lipsync", "primary", seconds)
    )
    print(
        f"one shot, {args.keyframes} keyframes screened on identity, {args.takes} takes, "
        "pick on head stability, then sync the winner"
    )
    print(f"  keyframe  {image_slot.model}")
    print(f"  video     {video_slot.model}")
    print(f"  voice     {voice_slot.model}")
    print(f"  lip sync  {sync_slot.model}")
    print(f"ESTIMATE    ${estimate}")
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0

    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    embedder = DlibEmbedder(config.providers)
    client = httpx.Client(
        timeout=300.0, headers={"Authorization": f"Key {api_key()}"} if api_key() else {}
    )

    # The reference is needed twice — once to screen the keyframe and once to judge the
    # finished shot — so it is built before either, from the same holdout both times.
    dataset = split(
        collect(
            {k: REFERENCE_ROOT / k for k in ("master_v2", "outfit", "lighting", "body")},
            exclude=NO_FACE_STILLS,
        ),
        trigger_word="mollie",
    )
    reference, _ = holdout_reference(dataset, embedder)

    # ------------------------------------------------------------ keyframe --
    keyframe = args.out / "keyframe.png"
    # The KEYFRAME bar, not the stills bar. A keyframe is the input to an animation that
    # costs 0.0165-0.0328 off the worst frame, so one at the stills threshold of 0.9619
    # lands below the video threshold of 0.951 and its take is refused. Five of six runs
    # failed precisely that way on keyframes the stills screen had passed.
    still_threshold = (
        config.persona.persona.look.identity_threshold_keyframe
        or config.persona.persona.look.identity_threshold
    )
    if still_threshold is None:
        raise SystemExit(
            "neither persona.look.identity_threshold_keyframe nor identity_threshold is "
            "set; a keyframe cannot be screened against a threshold that does not exist"
        )
    if not (args.skip_generate and keyframe.is_file()):
        prompt = apply_house_style(SHOT["still"].format(w=artefact["trigger_word"]))
        for problem in check_golf(prompt):
            raise SystemExit(f"shot prompt contains {problem.rule} — {problem.why}")
        assert image_slot.model is not None
        # Candidates screened and the hunt STOPS at the first one that clears, because
        # identity is lost here or not at all. Measured 2026-10-01: animating costs 0.0165
        # to 0.0477 off the worst frame, so a keyframe at the stills threshold of 0.9619
        # lands under the video threshold of 0.951 and its take is refused. The bar here is
        # `identity_threshold_keyframe`, which carries that margin. Roughly 1 draw in 40
        # clears it, at $0.035 a draw against $1.46 for the takes and sync underneath.
        screens: list[StillScreen] = []
        for candidate_index in range(args.keyframes):
            candidate = args.out / f"keyframe_{candidate_index}.png"
            url = generate_image(
                client,
                image_slot.model,
                prompt,
                artefact["weights_url"],
                float(image_slot.options.get("lora_scale", 1.0)),
                dict((image_slot.request or {}).get("base") or {}),
            )
            candidate.write_bytes(client.get(url, timeout=180.0).content)
            screen = screen_still(
                candidate, reference=reference, embedder=embedder, threshold=still_threshold
            )
            screens.append(screen)
            print(
                f"  keyframe {candidate_index + 1}/{args.keyframes}: {screen.score:.5f} "
                f"{'CLEARS' if screen.passes else 'below ' + format(still_threshold, '.4f')}"
            )
            if screen.passes:
                # Stop paying for draws once one clears. Later draws cannot improve the
                # outcome — the gate is a threshold, not a beauty contest.
                break
        chosen = best_still(screens)
        if not chosen.passes:
            spread = ", ".join(f"{s.score:.5f}" for s in screens)
            raise SystemExit(
                f"no keyframe in {len(screens)} draws reached {still_threshold:.4f} "
                f"(best {chosen.score:.5f}; all: {spread}). Refusing before paying for "
                "video and sync — animating costs 0.0165 to 0.0477 off the worst frame, so "
                "a keyframe below this bar produces a take the gate will refuse, and no "
                "later stage recovers identity the first frame never had."
            )
        chosen.path.replace(keyframe)
    print(f"keyframe    {keyframe.name}")

    # ------------------------------------------------------- fidelity pass --
    # The owner's verdict on an otherwise-passing shot was "it's her but almost a more AI
    # version of her", and that measured out: a flux+LoRA keyframe carries 100.2 of fine
    # detail against 222.7 for her own training stills. The pass takes it to 204.2 — 92% of
    # her stills — and moves identity by -0.00165. Applied to the WINNER only, after the
    # hunt, so a 40-draw hunt costs one pass rather than forty.
    if not (args.skip_generate and (args.out / "keyframe_detailed.png").is_file()):
        before = screen_still(
            keyframe, reference=reference, embedder=embedder, threshold=still_threshold
        )
        assert detail_slot.model is not None
        detailed = detail_pass(
            client,
            queue_root=QUEUE_ROOT,
            model=detail_slot.model,
            source=keyframe,
            dest=args.out / "keyframe_detailed.png",
            base=dict((detail_slot.request or {}).get("base") or {}),
        )
        after = screen_still(
            detailed, reference=reference, embedder=embedder, threshold=still_threshold
        )
        # This provider invents detail, and invented detail on a face is a different face.
        require_identity_preserved(before.score, after.score)
        print(f"detail pass {detailed.name}  identity {before.score:.5f} -> {after.score:.5f}")
        detailed.replace(keyframe)

    # --------------------------------------------------------------- takes --
    clip = args.out / "take.mp4"
    if not (args.skip_generate and clip.is_file()):
        motion = apply_house_style(SHOT["motion"])
        candidates = []
        for take in range(args.takes):
            candidate = args.out / f"take_{take}.mp4"
            assert video_slot.model is not None
            url = submit_clip(client, video_slot.model, motion, keyframe, video_request)
            candidate.write_bytes(client.get(url, timeout=300.0).content)
            candidates.append(candidate)
            print(f"  take {take + 1}/{args.takes}")
        # Scored against the same reference and the same threshold the gate will use, at
        # the gate's own sampling rate, so take selection and the gate cannot disagree.
        measured = [
            measure(
                c,
                embedder._detector,
                embedder._predictor,
                embedder=embedder,
                reference=reference,
            )
            for c in candidates
        ]
        for m in measured:
            print(
                f"    {m.path.name}: head roll sd {m.head_roll_sd_deg:.2f} deg, "
                f"{m.frames_with_face}/{m.frames_sampled} frames scorable "
                f"({m.coverage:.0%}), {m.frames_below(threshold)} below {threshold} "
                f"(mean {m.identity_mean:.5f})"
            )
        try:
            best = best_take(measured, threshold=threshold)
        except ValueError as refusal:
            # Refusing here is the point: the sync below is $0.50 and cannot rescue a take
            # the gate will refuse on identity.
            raise SystemExit(f"no usable take — {refusal}") from refusal
        print(f"  picked {best.path.name}")
        best.path.replace(clip)

    # --------------------------------------------------------------- voice --
    line_audio = args.out / "line.mp3"
    if not (args.skip_generate and line_audio.is_file()):
        shape = dict(voice_slot.request or {})
        voice = config.persona.persona.voice
        assert voice_slot.model is not None
        arguments: dict[str, Any] = {
            str(shape.get("text_field", "text")): SHOT["line"],
            str(shape.get("voice_field", "voice")): str(voice.voice_id),
            **dict(voice.options or {}),
        }
        r = client.post(f"{QUEUE_ROOT}/{voice_slot.model}", json=arguments)
        r.raise_for_status()
        sub = r.json()
        for _ in range(120):
            if client.get(sub["status_url"]).json().get("status") in {
                "COMPLETED",
                "FAILED",
                "ERROR",
            }:
                break
            time.sleep(3)
        url = str((client.get(sub["response_url"]).json().get("audio") or {}).get("url") or "")
        if not url:
            raise SystemExit("TTS returned no audio")
        line_audio.write_bytes(client.get(url, timeout=120.0).content)
    print(f"voice       {line_audio.name}")

    # ------------------------------------------------------------ lip sync --
    synced = args.out / "synced.mp4"
    decision = should_lip_sync(face_forward=True, has_dialogue=True)
    print(f"lip sync    {decision.reason}")
    if not (args.skip_generate and synced.is_file()):
        padded = pad_to(line_audio, duration_of(clip), args.out / "line_padded.mp3")
        storage = S3Storage(bucket=bucket_from_env())
        persona_id = persona_storage_id(config.persona.persona.id)
        video_key = key_for(persona_id, "take", "single-take.mp4")
        audio_key = key_for(persona_id, "voice", "single-line.mp3")
        storage.put(video_key, clip.read_bytes(), content_type="video/mp4", overwrite=True)
        storage.put(audio_key, padded.read_bytes(), content_type="audio/mpeg", overwrite=True)
        assert sync_slot.model is not None

        def presigned() -> tuple[str, str]:
            return (
                storage.presign_get(video_key, expires_in=3600),
                storage.presign_get(audio_key, expires_in=3600),
            )

        take_url, voice_url = presigned()
        lip_sync(
            client,
            queue_root=QUEUE_ROOT,
            model=sync_slot.model,
            video_url=take_url,
            audio_url=voice_url,
            base=dict((sync_slot.request or {}).get("base") or {}),
            dest=synced,
            refresh_urls=presigned,
        )

    # ---------------------------------------------------------- disclosure --
    final = apply_disclosure(
        synced, args.out / "final.mp4", overlay=config.persona.persona.disclosure.overlay
    )
    print(f"disclosed   {final.path.name}")

    # ------------------------------------------------------------- the gate --
    verdict = assess(
        [ShotUnderTest(name="single", path=final.path, speaks=True, audio_source="voice")],
        reference=reference,
        embedder=embedder,
        threshold=threshold,
        disclosed=True,
    )
    print("\n" + "=" * 70)
    print(verdict.report())
    print("=" * 70)
    return 0 if verdict.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
