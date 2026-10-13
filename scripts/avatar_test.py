"""One test: does an audio-driven avatar beat animate-then-paste-a-mouth-on?

ADR 0017. The chain in `make_single_shot.py` generates head motion from a still with a
model that never hears the line, then replaces the mouth with HeyGen. Motion and speech
are unrelated by construction, which is the owner's report — *"weird head tilt at the end
again"* — and the gate has said the rest out loud since 2026-09-24:

    [REVIEW] lip sync: whether the mouth matches the words is not measurable here.

This sends the same keyframe and the same voice line to `video.avatar`, which generates
mouth and head motion together from the audio, and reports the same numbers the current
chain reported so the two can be compared rather than admired:

    current chain, shot1-final, 2026-10-01
      6 takes, picked on head roll   swing 19.2 deg, ends -1.7 from start
      identity                       13/13 scorable, 0 below 0.951, mean 0.96529
      cost                           6 x 6.58s x $0.04 + $0.10/s sync = $2.24

Nothing here replaces anything. It writes clips, measures them, and stops.
"""

from __future__ import annotations

import argparse
import subprocess
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
from app.pipeline.assembler import duration_of
from app.pipeline.disclosure import apply_disclosure
from app.pipeline.takes import measure
from app.providers.fal import QUEUE_ROOT, api_key
from app.storage.keys import key_for
from app.storage.s3 import S3Storage, bucket_from_env
from scripts.make_single_shot import REFERENCE_ROOT
from scripts.train_lora import persona_storage_id

ROOT = Path(__file__).resolve().parents[1]

#: What the current chain produced, for the comparison this test exists to make.
BASELINE = {
    "swing_deg": 19.2,
    "return_deg": -1.7,
    "identity_mean": 0.96529,
    "coverage": 1.0,
    "cost_usd": Decimal("2.2452"),
}


def dimensions_of(video: Path) -> str:
    """Width x height, read from the file.

    Checked first and reported loudly because `video.avatar` takes no aspect or
    resolution parameter: the config records `canvas: follows_image_unverified`, and our
    shot is 1080x1920. A 16:9 clip back from a 9:16 keyframe would end the test here.
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def submit_avatar(
    client: httpx.Client, model: str, image_url: str, audio_url: str, shape: dict[str, Any]
) -> str:
    """Submit one avatar generation and return the finished video URL."""
    arguments: dict[str, Any] = {
        str(shape.get("image_field", "image_url")): image_url,
        str(shape.get("audio_field", "audio_url")): audio_url,
        **dict(shape.get("base") or {}),
    }
    response = client.post(f"{QUEUE_ROOT}/{model}", json=arguments)
    if response.status_code >= 400:
        raise SystemExit(f"avatar submit failed {response.status_code}: {response.text[:400]}")
    submitted = response.json()
    for _ in range(200):
        status = client.get(submitted["status_url"]).json().get("status")
        if status in {"COMPLETED", "FAILED", "ERROR"}:
            break
        time.sleep(3)
    result = client.get(submitted["response_url"]).json()
    url = (result.get("video") or {}).get("url")
    if not url:
        raise SystemExit(f"avatar finished with no video: {str(result)[:400]}")
    return str(url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    shot1 = ROOT / "spike" / "runs" / "shot1-final"
    parser.add_argument("--keyframe", type=Path, default=shot1 / "keyframe.png")
    parser.add_argument("--voice", type=Path, default=shot1 / "line.mp3")
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "avatar")
    parser.add_argument("--takes", type=int, default=3)
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    guard = BudgetGuard(config.budget, config.providers)
    slot, _, _ = guard.price("video", "avatar")
    assert slot.model is not None

    for needed in (args.keyframe, args.voice):
        if not needed.is_file():
            raise SystemExit(f"missing {needed}; run make_single_shot first")
    seconds = duration_of(args.voice)
    estimate = guard.estimate("video", "avatar", Decimal(str(round(seconds, 3))) * args.takes)

    print(f"one talking shot, {args.takes} takes, audio-driven")
    print(f"  model     {slot.model}  (${slot.price_usd_per_second}/s)")
    print(f"  keyframe  {args.keyframe.name}  (the still shot 1 was built from)")
    print(f"  voice     {args.voice.name}  {seconds:.2f}s — the clip length follows this")
    print(f"ESTIMATE    ${estimate}   vs ${BASELINE['cost_usd']} for the current chain")
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0

    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(
        timeout=900.0, headers={"Authorization": f"Key {api_key()}"} if api_key() else {}
    )

    # fal fetches both inputs itself, so they go to the bucket and are handed over as
    # presigned URLs — same route the lip-sync stage uses, and it keeps the still private.
    storage = S3Storage(bucket=bucket_from_env())
    persona_id = persona_storage_id(config.persona.persona.id)
    image_key = key_for(persona_id, "keyframe", "avatar-keyframe.png")
    audio_key = key_for(persona_id, "voice", "avatar-line.mp3")
    storage.put(image_key, args.keyframe.read_bytes(), content_type="image/png", overwrite=True)
    storage.put(audio_key, args.voice.read_bytes(), content_type="audio/mpeg", overwrite=True)
    image_url = storage.presign_get(image_key, expires_in=3600)
    audio_url = storage.presign_get(audio_key, expires_in=3600)

    shape = dict(slot.request or {})
    takes: list[Path] = []
    for index in range(args.takes):
        take = args.out / f"take_{index}.mp4"
        if not (args.skip_generate and take.is_file()):
            url = submit_avatar(client, slot.model, image_url, audio_url, shape)
            take.write_bytes(client.get(url, timeout=600.0).content)
        takes.append(take)
        print(
            f"  take {index + 1}/{args.takes}  {take.name}  {dimensions_of(take)}  "
            f"{duration_of(take):.2f}s"
        )

    # Identity against the same reference, threshold and sampling rate the gate uses, so
    # this test and the gate cannot disagree. Amendment A5 wants the score taken after the
    # last transformation of the face — here there is only one stage, which is the point.
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

    print(f"\n{'take':<12} {'swing':>7} {'ends':>7} {'cov':>6} {'below':>6} {'mean':>9}")
    measured = [
        measure(t, embedder._detector, embedder._predictor, embedder=embedder, reference=reference)
        for t in takes
    ]
    for m in measured:
        print(
            f"{m.path.name:<12} {m.roll_swing_deg:>6.1f}d {m.roll_return_deg:>+6.1f}d "
            f"{m.coverage:>5.0%} {m.frames_below(threshold):>6} {m.identity_mean:>9.5f}"
        )
    print(
        f"{'BASELINE':<12} {BASELINE['swing_deg']:>6.1f}d {BASELINE['return_deg']:>+6.1f}d "
        f"{BASELINE['coverage']:>5.0%} {0:>6} {BASELINE['identity_mean']:>9.5f}"
        "   <- current chain, 2026-10-01"
    )

    # Every take is kept. Head roll is no longer a free variable to rank on — the motion
    # comes from the audio — so there is no criterion here beyond identity, and lip sync
    # is the thing being judged and is not measurable. A human picks.
    usable = [m for m in measured if m.frames_below(threshold) == 0 and m.coverage >= 0.6]
    print(f"\n{len(usable)} of {len(measured)} takes pass identity outright")
    chosen = (usable[0] if usable else measured[0]).path
    disclosed = apply_disclosure(
        chosen, args.out / "final.mp4", overlay=config.persona.persona.disclosure.overlay
    )
    print(f"disclosed   {disclosed.path.name}  (from {chosen.name}; a human picks the take)")

    verdict = assess(
        [ShotUnderTest("talk", disclosed.path, speaks=True, audio_source="voice")],
        reference=reference,
        embedder=embedder,
        threshold=threshold,
        disclosed=True,
    )
    print("\n" + "=" * 70)
    print(verdict.report())
    print("=" * 70)
    print("\nThe question this cannot answer: whether the mouth matches the words, and")
    print("whether the head moves like a person. Watch it. That is the whole test.")
    return 0 if verdict.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
