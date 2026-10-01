"""Does her face survive being animated? The question Phase 1 exists to answer.

Everything measured so far is stills. A LoRA that holds a likeness in a single frame
says nothing about whether it holds across 60 of them, and the spike's own worst finding
was that a defect can live inside a window where no face is detectable at all.

So: take LoRA-generated keyframes, animate each, sample every clip at 2 fps, and score
every frame against the holdout centroid. What matters is not the mean — it is the
**minimum** and the **coverage**. A clip that averages well and drops to 0.93 for four
frames is a clip with a visible glitch in it, and a clip where 3 frames in 10 contain no
findable face is a clip the gate cannot speak about.

Keyframes are reused from the LoRA evaluation rather than regenerated, because they only
need to be her and paying twice for that proves nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.identity.dataset import NO_FACE_STILLS, collect, split
from app.identity.embedder import DlibEmbedder, cosine
from app.identity.evaluation import holdout_reference
from app.identity.master_set import read_still
from app.providers.fal import QUEUE_ROOT, api_key, data_uri
from scripts.spike.frames import FfmpegFrames

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ROOT = ROOT / "spike" / "data"
EVAL_ROOT = ROOT / "spike" / "runs" / "lora"
GROUP, SLOT = "video", "golf"
SAMPLE_FPS = 2.0

#: Keyframe, motion prompt, and what the cell is testing. Keyframes come from the LoRA
#: evaluation runs, so every clip starts from a frame already scored as her.
CELLS: list[dict[str, str]] = [
    {
        "name": "talking_head",
        "keyframe": "eval/gen_00.png",
        "prompt": "she speaks to the camera, small natural head movements, shallow depth of field",
        "tests": "the core format — face-forward, minimal motion",
    },
    {
        "name": "walking",
        "keyframe": "eval/gen_05.png",
        "prompt": "she walks slowly towards the camera along a path, hair moving in the breeze",
        "tests": "walking, the worst motion axis in the spike matrix",
    },
    {
        "name": "golf_swing",
        "keyframe": "eval-golf-s13/gen_04_t0.png",
        "prompt": "she swings a golf club, full follow through, camera static",
        "tests": "the hard case — large motion, face turns away",
    },
]


#: Control clips: a DIFFERENT synthetic face, animated the same way, so the negatives
#: are drawn from the same population as the positives. Calibrating her video frames
#: against control STILLS is the calibration-space error this project has already made
#: twice — a threshold is only meaningful between two distributions measured alike.
#:
#: Synthetic throughout, as ADR 0002 Finding 4 requires: real faces would be Article 9
#: biometric data.
CONTROL_CELLS: list[dict[str, str]] = [
    {
        "name": "control_talking",
        "keyframe": "control_v2/c1_00.png",
        "prompt": "she speaks to the camera, small natural head movements, shallow depth of field",
        "tests": "negative — a different face, same motion as talking_head",
    },
    {
        "name": "control_walking",
        "keyframe": "control_v2/c2_00.png",
        "prompt": "she walks slowly towards the camera along a path, hair moving in the breeze",
        "tests": "negative — a different face, same motion as walking",
    },
    {
        "name": "control_portrait",
        "keyframe": "control_v2/c3_00.png",
        "prompt": "she turns her head slowly towards the camera and smiles",
        "tests": "negative — a different face, gentle motion",
    },
]


@dataclass
class ClipResult:
    name: str
    tests: str
    clip: Path
    frames: int = 0
    scores: list[float] = field(default_factory=list)
    no_face: int = 0

    @property
    def coverage(self) -> float:
        return len(self.scores) / self.frames if self.frames else 0.0

    @property
    def mean(self) -> float | None:
        return sum(self.scores) / len(self.scores) if self.scores else None

    @property
    def minimum(self) -> float | None:
        return min(self.scores) if self.scores else None


#: Below this, a clip's scores describe too few of its frames to stand for the clip.
#: Not a quality bar — a floor on whether there is anything to judge.
MIN_COVERAGE = 0.6


def _verdict(result: ClipResult, threshold: float) -> str:
    """What the scores actually license saying about this clip.

    Coverage is checked BEFORE the scores, because a high minimum over two frames is not
    a statement about a ten-frame clip. The first version of this function reported a
    clip with 1 scorable frame in 10 as "PASS every frame", which is true and useless:
    it is the spike's central finding — the gate is silent where it cannot see a face —
    dressed up as a pass.
    """
    if result.minimum is None:
        return "NO FACE in any frame — unmeasurable"
    if result.coverage < MIN_COVERAGE:
        return f"CANNOT SAY — face found in {len(result.scores)}/{result.frames} frames"
    if result.minimum >= threshold:
        return "holds every frame"
    return f"DIPS to {result.minimum:.5f}, below {threshold}"


def submit_clip(
    client: httpx.Client,
    model: str,
    prompt: str,
    keyframe: Path,
    shape: dict[str, Any],
    last_keyframe: Path | None = None,
) -> str:
    """Submit one image-to-video job and return the finished clip URL.

    `last_keyframe` pins the end of the motion (ADR 0007). Passing the SAME still as both
    ends makes the head return to the angle it started at, which is the lever against a
    tilt that develops and stays — the model interpolates between two known states rather
    than inventing the end.
    """
    arguments: dict[str, Any] = {"prompt": prompt, **dict(shape.get("base") or {})}
    image_field = shape.get("image_field")
    if not image_field:
        raise SystemExit(
            "video slot declares no request.image_field; sending the wrong name is a 422"
        )
    # A data URI, not an upload: fal's CDN is public and these frames are her face.
    arguments[str(image_field)] = data_uri(keyframe)
    if last_keyframe is not None:
        end_field = shape.get("end_image_field")
        if not end_field:
            raise SystemExit(
                "a last keyframe was given but the video slot declares no "
                "request.end_image_field; sending the wrong name is a 422"
            )
        arguments[str(end_field)] = data_uri(last_keyframe)
    duration_field = shape.get("duration_field", "duration")
    arguments[duration_field] = int(shape.get("duration_s", 5))

    r = client.post(f"{QUEUE_ROOT}/{model}", json=arguments)
    if r.status_code >= 400:
        raise RuntimeError(f"submit failed {r.status_code}: {r.text[:400]}")
    sub = r.json()
    status_url, response_url = sub["status_url"], sub["response_url"]
    for _ in range(180):
        if client.get(status_url).json().get("status") in {"COMPLETED", "FAILED", "ERROR"}:
            break
        time.sleep(5)
    resp = client.get(response_url)
    if resp.status_code >= 400:
        raise RuntimeError(f"generation failed {resp.status_code}: {resp.text[:400]}")
    video = resp.json().get("video") or {}
    url = video.get("url")
    if not url:
        raise RuntimeError(f"COMPLETED with no video: {resp.text[:400]}")
    return str(url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=EVAL_ROOT / "video")
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--controls",
        action="store_true",
        help="animate control faces instead, to measure the negative side",
    )
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    # The VIDEO threshold, not the stills one. They are separate measurements of
    # separate populations and using the stills figure here is the calibration-space
    # error that produced two false negatives on the talking-head clip.
    look = config.persona.persona.look
    configured = look.identity_threshold_video or look.identity_threshold
    if configured is None:
        raise SystemExit("no identity threshold configured")
    threshold = float(configured)
    basis = "video" if look.identity_threshold_video else "stills (no video threshold set)"

    dataset = split(
        collect(
            {k: REFERENCE_ROOT / k for k in ("master_v2", "outfit", "lighting", "body")},
            exclude=NO_FACE_STILLS,
        ),
        trigger_word="mollie",
    )
    embedder = DlibEmbedder(config.providers)
    reference, unusable = holdout_reference(dataset, embedder)
    print(f"threshold     {threshold}  ({basis})")
    print(f"reference     holdout centroid, {len(dataset.holdout) - len(unusable)} stills")

    guard = BudgetGuard(config.budget, config.providers)
    slot, unit_price, unit = guard.price(GROUP, SLOT)
    shape = dict(slot.request or {})
    cells = CONTROL_CELLS if args.controls else CELLS
    keyframe_root = REFERENCE_ROOT if args.controls else EVAL_ROOT
    if args.controls:
        args.out = args.out.parent / "video-controls"
    seconds = Decimal(str(shape.get("duration_s", 5))) * len(cells)
    estimate = guard.estimate(GROUP, SLOT, seconds)
    print(f"\nmodel         {slot.model}")
    print(f"price         ${unit_price} per {unit} x {seconds}s = ${estimate}")
    for cell in cells:
        print(f"  {cell['name']:<18} {cell['tests']}")
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0

    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Key {api_key()}"} if api_key() else {}
    client = httpx.Client(timeout=300.0, headers=headers)
    sampler = FfmpegFrames()
    results: list[ClipResult] = []

    for cell in cells:
        keyframe = keyframe_root / cell["keyframe"]
        if not keyframe.is_file():
            print(f"SKIP {cell['name']}: keyframe {keyframe} missing")
            continue
        print(f"\n-- {cell['name']} --\n   {cell['prompt']}")
        assert slot.model is not None
        url = submit_clip(client, slot.model, cell["prompt"], keyframe, shape)
        clip = args.out / f"{cell['name']}.mp4"
        clip.write_bytes(client.get(url, timeout=300.0).content)
        print(f"   clip -> {clip.name} ({clip.stat().st_size / 1048576:.2f} MB)")

        frame_dir = args.out / f"{cell['name']}_frames"
        frames = sampler.extract(clip, frame_dir, SAMPLE_FPS)
        result = ClipResult(cell["name"], cell["tests"], clip, frames=len(frames))
        for frame in frames:
            reading = read_still(frame, embedder)
            if reading.embedding is None:
                result.no_face += 1
                continue
            result.scores.append(cosine(reading.embedding, reference))
        results.append(result)
        print(
            f"   frames {result.frames} at {SAMPLE_FPS} fps, "
            f"coverage {result.coverage:.2f}, "
            f"min {result.minimum:.5f}"
            if result.minimum
            else "   no scorable frames"
        )

    print("\n" + "=" * 72)
    print(f"{'clip':<14} {'frames':>6} {'cover':>6} {'mean':>9} {'MIN':>9}  verdict")
    print("-" * 72)
    for r in results:
        verdict = _verdict(r, threshold)
        print(
            f"{r.name:<14} {r.frames:>6} {r.coverage:>6.2f} "
            f"{(r.mean or 0):>9.5f} {(r.minimum or 0):>9.5f}  {verdict}"
        )

    summary = {
        "threshold": threshold,
        "sample_fps": SAMPLE_FPS,
        "model": slot.model,
        "estimated_cost_usd": str(estimate),
        "clips": [
            {
                "name": r.name,
                "tests": r.tests,
                "frames": r.frames,
                "scored": len(r.scores),
                "no_face": r.no_face,
                "coverage": r.coverage,
                "mean": r.mean,
                "min": r.minimum,
                "scores": r.scores,
            }
            for r in results
        ],
    }
    (args.out / ("video_controls.json" if args.controls else "video_identity.json")).write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(f"\nrecorded      {(args.out / 'video_identity.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
