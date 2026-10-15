"""Recast a real golf video so the golfer is her: the golf is filmed, not generated.

Three weeks of golf faults were all properties of a scene the model invented — a full
swing from 30 yards, the club missing the ball while the ball moved anyway, a bag and a
trolley on the green, two flagsticks, a hole cut in the fringe. `minimax/h3-max/recast`
does not invent the scene. It replaces the people in a real video from reference photos
and keeps the source motion, camera, cuts and audio.

So the swing is a real swing, the ball flight is real ball flight, the etiquette is
whatever the course actually looked like, and the only synthetic thing in frame is her.
Identity becomes the only risk, which is the one thing this project can measure.

    python -m scripts.recast_test --source my-pitch.mp4 --budget 6

**The source video must be yours.** Footage you filmed, of yourself: your likeness is the
input and does not survive into the output. Stock needs its licence read — using a clip as
an editorial cutaway and feeding it to a model are different permissions, and plenty of
licences now name the second. Footage of a real golfer off the internet is not an option.

**It is not cheap.** $0.45 per second of output at 1080p, read from the model's own
billing message on 2026-10-15. A ten-second pitch is $4.50, which is eleven times the
per-second rate of the generation chain. That is the price of the golf being right.

Before anything is submitted the source is measured: `app.pipeline.swing` reports the
swing length of the footage, because a driving video is only useful if the swing in it is
the length the shot needs — and a source that is itself a full swing would hand back
exactly the fault we are trying to leave behind.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.identity.dataset import NO_FACE_STILLS, collect, split
from app.identity.embedder import DlibEmbedder
from app.identity.evaluation import holdout_reference
from app.pipeline.acceptance import ShotUnderTest, assess
from app.pipeline.assembler import duration_of
from app.pipeline.disclosure import apply_disclosure
from app.pipeline.swing import CEILING, SwingKind
from app.pipeline.swing import check as check_swing
from app.pipeline.takes import measure
from app.providers.fal import QUEUE_ROOT, api_key
from app.providers.pose import MediapipePose
from app.storage.keys import key_for
from app.storage.s3 import S3Storage, bucket_from_env
from scripts.make_single_shot import REFERENCE_ROOT
from scripts.train_lora import persona_storage_id

ROOT = Path(__file__).resolve().parents[1]

#: How many reference photos to send. The endpoint takes 1-4 at no extra charge, and
#: more angles is the only lever on identity that costs nothing.
REFERENCES = 4


def submit_recast(
    client: httpx.Client, model: str, video_url: str, refs: list[str], shape: dict[str, Any]
) -> str:
    arguments: dict[str, Any] = {
        str(shape.get("video_field", "video_url")): video_url,
        str(shape.get("reference_field", "reference_image_urls")): refs,
        **dict(shape.get("base") or {}),
    }
    response = client.post(f"{QUEUE_ROOT}/{model}", json=arguments)
    if response.status_code >= 400:
        raise SystemExit(f"recast submit failed {response.status_code}: {response.text[:400]}")
    submitted = response.json()
    for _ in range(400):
        if client.get(submitted["status_url"]).json().get("status") in {
            "COMPLETED",
            "FAILED",
            "ERROR",
        }:
            break
        time.sleep(3)
    result = client.get(submitted["response_url"]).json()
    url = (result.get("video") or {}).get("url")
    if not url:
        raise SystemExit(f"recast finished with no video: {str(result)[:400]}")
    return str(url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="your own golf footage")
    parser.add_argument(
        "--declared",
        choices=sorted(CEILING),
        default="pitch",
        help="what the swing in the SOURCE is meant to be; measured before submitting",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "recast")
    parser.add_argument("--takes", type=int, default=1)
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"no source video at {args.source}")

    config = load_all(ROOT / "config")
    guard = BudgetGuard(config.budget, config.providers)
    slot, _, _ = guard.price("video", "recast")
    assert slot.model is not None

    seconds = duration_of(args.source)
    low, high = (slot.capabilities.get("source_seconds") or [5, 30])[:2]
    if not low <= seconds <= high:
        raise SystemExit(
            f"source is {seconds:.1f}s; this model takes {low}-{high}s. Trim it and retry."
        )
    estimate = guard.estimate("video", "recast", Decimal(str(round(seconds, 3))) * args.takes)

    print(f"source      {args.source.name}  {seconds:.2f}s")
    print(
        f"  model     {slot.model}  (${slot.price_usd_per_second}/s at "
        f"{(slot.request.get('base') or {}).get('resolution')})"
    )
    print(f"  takes     {args.takes}")
    print(f"ESTIMATE    ${estimate}")

    # ---------------------------------------------- measure the source first --
    # A driving video is only useful if the swing in it is the length the shot needs.
    pose = MediapipePose(ROOT / str(config.providers.pose.pose_model))
    source_swing = check_swing(cast(SwingKind, args.declared), pose.frames(args.source))
    print(f"\nsource swing  {source_swing.explain()}")
    if source_swing.above_shoulder_line and args.declared != "full":
        raise SystemExit(
            f"the SOURCE footage is a full swing and you declared a {args.declared}. "
            f"Recasting it would hand back the exact fault we are leaving behind. "
            f"Re-film it, or pass --declared full if that is what you meant."
        )
    if not source_swing.verifiable:
        print("  (warning: the source gave too little pose to judge its swing)")

    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0

    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(
        timeout=1800.0, headers={"Authorization": f"Key {api_key()}"} if api_key() else {}
    )

    # --------------------------------------------------- inputs to the bucket --
    embedder = DlibEmbedder(config.providers)
    dataset = split(
        collect(
            {k: REFERENCE_ROOT / k for k in ("master_v2", "outfit", "lighting", "body")},
            exclude=NO_FACE_STILLS,
        ),
        trigger_word="mollie",
    )
    reference, _ = holdout_reference(dataset, embedder)
    stills = sorted(p for p in (REFERENCE_ROOT / "master_v2").iterdir() if p.suffix == ".png")
    chosen_stills = random.Random(0).sample(stills, min(REFERENCES, len(stills)))

    storage = S3Storage(bucket=bucket_from_env())
    persona_id = persona_storage_id(config.persona.persona.id)
    video_key = key_for(persona_id, "source", "recast-source.mp4")
    storage.put(video_key, args.source.read_bytes(), content_type="video/mp4", overwrite=True)
    video_url = storage.presign_get(video_key, expires_in=3600)
    ref_urls = []
    for index, still in enumerate(chosen_stills):
        key = key_for(persona_id, "reference", f"recast-ref-{index}.png")
        storage.put(key, still.read_bytes(), content_type="image/png", overwrite=True)
        ref_urls.append(storage.presign_get(key, expires_in=3600))
    print(f"references  {', '.join(p.name for p in chosen_stills)}")

    # ------------------------------------------------------------- generate --
    shape = dict(slot.request or {})
    threshold = float(config.persona.persona.look.identity_threshold_video or 0.0)
    results: list[Path] = []
    for index in range(args.takes):
        take = args.out / f"take_{index}.mp4"
        url = submit_recast(client, slot.model, video_url, ref_urls, shape)
        take.write_bytes(client.get(url, timeout=900.0).content)
        results.append(take)
        print(f"  take {index + 1}/{args.takes}  {take.name}  {duration_of(take):.2f}s")

    print(f"\n{'take':<12} {'cov':>6} {'below':>6} {'mean':>9}  swing")
    for take in results:
        m = measure(
            take, embedder._detector, embedder._predictor, embedder=embedder, reference=reference
        )
        out_swing = check_swing(cast(SwingKind, args.declared), pose.frames(take))
        peak = f"{out_swing.measurement.peak:.2f}" if out_swing.measurement.peak else "--"
        print(
            f"{take.name:<12} {m.coverage:>5.0%} {m.frames_below(threshold):>6} "
            f"{m.identity_mean:>9.5f}  peak {peak}"
        )

    disclosed = apply_disclosure(
        results[0], args.out / "final.mp4", overlay=config.persona.persona.disclosure.overlay
    )
    print(f"disclosed   {disclosed.path.name}")
    verdict = assess(
        [
            ShotUnderTest(
                name="recast",
                path=disclosed.path,
                speaks=False,
                audio_source="none",
                swing=cast(SwingKind, args.declared),
            )
        ],
        reference=reference,
        embedder=embedder,
        threshold=threshold,
        disclosed=True,
        pose=pose,
    )
    print("\n" + "=" * 70)
    print(verdict.report())
    print("=" * 70)
    return 0 if verdict.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
