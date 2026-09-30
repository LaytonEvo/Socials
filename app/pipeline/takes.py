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
    frames_sampled: int
    head_roll_sd_deg: float
    mouth_activity: float

    @property
    def usable(self) -> bool:
        return self.frames_with_face >= 3

    @property
    def coverage(self) -> float:
        """The share of sampled frames a face was found in.

        The count alone is not comparable between takes: 14 frames is most of a short
        take and a third of a longer one, and only the ratio says whether the numbers
        below describe the take or just the part of it that was visible.
        """
        if self.frames_sampled <= 0:
            return 0.0
        return self.frames_with_face / self.frames_sampled


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
    frames = sample_frames(clip, fps)
    for frame in frames:
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
        frames_sampled=len(frames),
        head_roll_sd_deg=float(np.std(rolls)) if rolls else float("nan"),
        mouth_activity=activity,
    )


MIN_TAKE_COVERAGE = 0.6


def steadiest(
    takes: list[TakeMeasurement], *, min_coverage: float = MIN_TAKE_COVERAGE
) -> TakeMeasurement:
    """The take whose head moves least, among those seen well enough to say.

    Coverage is checked before the score, for the same reason the acceptance gate checks
    it: a low roll figure measured over a third of the frames is not a steadier take, it
    is a less observed one, and comparing it against a take measured over all of them
    rewards whichever take the detector lost track of. The first run picked exactly that
    way — 3.43 degrees over 14 frames beat 4.60 over 37 — and the take it chose was then
    refused downstream, which is the same fact arriving later and dearer: a face dlib can
    only find in 38% of frames is one the sync provider cannot track either.

    Refuses rather than guesses when no take clears the floor. Another take costs $0.0625
    against $0.50 for the sync, so shooting again is the cheap side of this decision.
    """
    usable = [t for t in takes if t.usable and not np.isnan(t.head_roll_sd_deg)]
    if not usable:
        raise ValueError("no take had enough detectable face to measure head movement")
    covered = [t for t in usable if t.coverage >= min_coverage]
    if not covered:
        best = max(usable, key=lambda t: t.coverage)
        raise ValueError(
            f"no take had a face in {min_coverage:.0%} of its frames — best was "
            f"{best.path.name} at {best.coverage:.0%} "
            f"({best.frames_with_face}/{best.frames_sampled}); shoot more takes"
        )
    return min(covered, key=lambda t: t.head_roll_sd_deg)
