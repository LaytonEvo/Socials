"""Measure the swing in a clip, and say whether it is the shot that was asked for.

For checking a render without running the whole gate — and for checking footage the
owner has filmed, which is the other half of the motion-transfer plan: a driving video
is only useful if the swing in it is the length the shot needs.

    python -m scripts.swing_check pitch spike/runs/broll/address_strike_take_0.mp4

Reads the weights path and visibility floor from `config/providers.yaml`, so the numbers
here are the same numbers the gate will produce.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

from app.config import load_all
from app.pipeline.swing import CEILING, SHOULDER_LINE, SwingKind, check
from app.providers.pose import MediapipePose

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "declared", choices=sorted(CEILING), help="the shot the clip is meant to be"
    )
    parser.add_argument("clips", type=Path, nargs="+")
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    pose_config = config.providers.pose
    if not pose_config.pose_model:
        raise SystemExit("config/providers.yaml has no pose.pose_model; run `make fetch-models`")
    source = MediapipePose(
        ROOT / str(pose_config.pose_model), min_visibility=pose_config.min_visibility
    )

    print(f"declared a {args.declared} (ceiling {CEILING[args.declared]:g})")
    print(f"shoulder line is {SHOULDER_LINE:g}; hands above it are a full swing\n")
    refused = 0
    for clip in args.clips:
        declared = cast(SwingKind, args.declared)
        result = check(declared, source.frames(clip))
        m = result.measurement
        peak = f"{m.peak:.2f}" if m.peak is not None else "--"
        verdict = (
            "CANNOT SAY"
            if not result.verifiable
            else "FULL SWING"
            if result.above_shoulder_line
            else "LONGER"
            if result.longer_than_declared
            else "ok"
        )
        if verdict != "ok":
            refused += 1
        print(
            f"  {clip.name:<32} peak {peak:>5}  "
            f"cov {m.coverage:>4.0%} of {m.frames_sampled:>3}  "
            f"above-line {m.frames_above_shoulder:>3}  {verdict}"
        )
        print(f"  {'':<32} {result.explain()}")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
