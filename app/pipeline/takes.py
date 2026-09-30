"""Choosing between takes on something measurable.

The generator is not steerable enough to ask for a still head and get one — a take
asked to keep its head "completely still and upright, no tilting" came back with 8.9
degrees of roll variation, which reads as a glitch rather than as a person. Prompting
harder did not fix it and there is no seed that is honoured (SeedSupport: accepted, not
honoured).

So the answer is the one production has always used: shoot several takes and pick. This
measures what the prompt failed to control, so the pick is a number rather than an
opinion, and cheap — a take costs $0.0625 where the lip sync that follows costs $0.50,
so choosing well before syncing is eight times cheaper than syncing the wrong one.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class TakeMeasurement:
    """What can be measured about a take without a human watching it."""

    path: Path
    frames_with_face: int
    head_roll_sd_deg: float
    mouth_activity: float

    @property
    def usable(self) -> bool:
        return self.frames_with_face >= 3


def sample_frames(clip: Path, fps: float = 8.0) -> list[Path]:
    directory = Path(tempfile.mkdtemp())
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(clip),
            "-vf",
            f"fps={fps}",
            str(directory / "f_%04d.png"),
        ],
        check=True,
        capture_output=True,
    )
    return sorted(directory.glob("*.png"))


def measure(
    clip: Path, detector: object, predictor: object, *, fps: float = 8.0
) -> TakeMeasurement:
    """Head roll and mouth activity, both measured INSIDE the detected face box.

    Inside the box, not at fixed frame coordinates: a walking or swinging shot moves the
    whole picture, and a fixed region reads that as a moving mouth. The first attempt at
    this measured b-roll as more talkative than the talking take.
    """
    rolls: list[float] = []
    crops: list[np.ndarray] = []
    for frame in sample_frames(clip, fps):
        image = np.asarray(Image.open(frame).convert("RGB"))
        faces = detector(image, 1)  # type: ignore[operator]
        if not faces:
            continue
        box = faces[0]
        shape = predictor(image, box)  # type: ignore[operator]
        points = (
            np.array(
                [[shape.part(i).x, shape.part(i).y] for i in range(shape.num_parts)], dtype=float
            )
            if hasattr(shape, "num_parts")
            else np.array([[shape.part(i).x, shape.part(i).y] for i in range(4)], dtype=float)
        )
        if len(points) >= 3:
            dx, dy = points[0] - points[2]
            rolls.append(float(np.degrees(np.arctan2(dy, dx))))

        grey = np.asarray(Image.open(frame).convert("L"), dtype=float)
        height, width = box.bottom() - box.top(), box.right() - box.left()
        patch = grey[
            max(box.top() + int(height * 0.60), 0) : box.top() + int(height * 0.92),
            max(box.left() + int(width * 0.25), 0) : box.left() + int(width * 0.75),
        ]
        if patch.size:
            crops.append(
                np.asarray(Image.fromarray(patch.astype("uint8")).resize((48, 32)), dtype=float)
            )

    activity = (
        float(np.mean([np.abs(crops[i + 1] - crops[i]).mean() for i in range(len(crops) - 1)]))
        if len(crops) > 1
        else 0.0
    )
    return TakeMeasurement(
        path=clip,
        frames_with_face=len(crops),
        head_roll_sd_deg=float(np.std(rolls)) if rolls else float("nan"),
        mouth_activity=activity,
    )


def steadiest(takes: list[TakeMeasurement]) -> TakeMeasurement:
    """The take whose head moves least, among those with a face to measure.

    Refuses rather than guesses when nothing is measurable: picking arbitrarily and
    calling it a choice is worse than saying no take could be assessed.
    """
    usable = [t for t in takes if t.usable and not np.isnan(t.head_roll_sd_deg)]
    if not usable:
        raise ValueError("no take had enough detectable face to measure head movement")
    return min(usable, key=lambda t: t.head_roll_sd_deg)
