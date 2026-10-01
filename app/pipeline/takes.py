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

from app.identity.embedder import DlibEmbedder, Embedding, cosine


@dataclass(frozen=True)
class TakeMeasurement:
    """What can be measured about a take without a human watching it."""

    path: Path
    frames_with_face: int
    frames_sampled: int
    head_roll_sd_deg: float
    mouth_activity: float
    identity_scores: tuple[float, ...] = ()

    @property
    def usable(self) -> bool:
        return self.frames_with_face >= 3

    @property
    def coverage(self) -> float:
        """The share of sampled frames the gate could score.

        Counted with `embedder.read`, not with a bare face detection, because those two
        disagree and the disagreement mattered. Measured 2026-10-01: `measure` reported
        63-98% coverage on takes where only 26-39% of frames could be embedded — the
        detector finds a face at 63px that `read` refuses as TOO_SMALL under its 80px
        floor, and it takes `faces[0]` where `read` refuses a multi-face frame outright.
        A take could clear this floor and still be unscorable by the gate, which made the
        floor measure something other than the thing it protects.

        The ratio and not the count: 14 frames is most of a short take and a third of a
        longer one, and only the ratio says whether the numbers describe the take or just
        the part of it that was visible.
        """
        if self.frames_sampled <= 0:
            return 0.0
        return self.frames_with_face / self.frames_sampled

    def frames_below(self, threshold: float) -> int:
        """How many scored frames the gate would refuse."""
        return sum(1 for s in self.identity_scores if s < threshold)

    @property
    def identity_mean(self) -> float:
        if not self.identity_scores:
            return float("nan")
        return float(np.mean(self.identity_scores))

    @property
    def identity_min(self) -> float:
        if not self.identity_scores:
            return float("nan")
        return float(min(self.identity_scores))

    def would_pass_gate(self, *, threshold: float, min_coverage: float) -> bool:
        """Whether the gate would accept this take's identity as it stands.

        The sync that follows shifts the mean by a few thousandths in either direction
        (+0.0041 measured once, -0.003 another time), so this is the gate's own rule
        applied early rather than a prediction with a margin. A margin would be a number
        invented rather than calibrated.
        """
        return (
            bool(self.identity_scores)
            and self.coverage >= min_coverage
            and self.frames_below(threshold) == 0
        )


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


GATE_SAMPLE_FPS = 2.0


def measure(
    clip: Path,
    detector: object,
    predictor: object,
    *,
    fps: float = 8.0,
    embedder: DlibEmbedder | None = None,
    reference: Embedding | None = None,
    identity_fps: float = GATE_SAMPLE_FPS,
) -> TakeMeasurement:
    """Head roll and mouth activity, both measured INSIDE the detected face box.

        Inside the box, not at fixed frame coordinates: a walking or swinging shot moves the
        whole picture, and a fixed region reads that as a moving mouth. The first attempt at
        this measured b-roll as more talkative than the talking take.

        Given an `embedder` and a `reference`, each frame is also scored for identity, so a
        take can be compared against the threshold the gate will apply to it *before* the
        sync is paid for. Coverage is then counted as frames the embedder could actually
        read, which is the number the gate uses.

    **Two sampling rates, deliberately, because the two measurements want opposite things.**

        Head roll is a standard deviation and wants samples: estimated over 10 frames instead
        of 41 it is simply noisier, and nothing about the geometry cares how densely it was
        measured. So roll and mouth activity use the dense `fps`.

        Identity cannot be sampled denser than the threshold it is compared against. The video
        threshold of 0.951 was calibrated as the *minimum of a 21-frame sample at 2 fps*, so it
        is an order statistic of that sample size — sample three times as densely and you reach
        further into the tail and find frames the calibration never saw. Measured: at 6 fps
        every one of twenty takes failed a rule the gate passed four of five times at 2 fps.
        That is the calibration-space error this project has now made three times, so
        `identity_fps` defaults to `GATE_SAMPLE_FPS` and raising it to "look harder" makes the
        answer wrong rather than stricter.
    """
    # Identity and coverage, at the gate's rate, over its own extraction.
    scores: list[float] = []
    scorable = 0
    identity_frames: list[Path] = []
    if embedder is not None:
        identity_frames = sample_frames(clip, identity_fps)
        for frame in identity_frames:
            reading = embedder.read(np.asarray(Image.open(frame).convert("RGB")))
            if reading.embedding is None:
                continue
            scorable += 1
            if reference is not None:
                scores.append(cosine(reading.embedding, reference))

    # Geometry, densely, since a standard deviation over 10 frames is just a noisier one.
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
        # When an embedder is given, coverage is what *it* could read, because that is
        # what the gate will be able to score. Without one this falls back to detections.
        frames_with_face=scorable if embedder is not None else len(crops),
        frames_sampled=len(identity_frames) if embedder is not None else len(frames),
        head_roll_sd_deg=float(np.std(rolls)) if rolls else float("nan"),
        mouth_activity=activity,
        identity_scores=tuple(scores),
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


def best_take(
    takes: list[TakeMeasurement],
    *,
    threshold: float,
    min_coverage: float = MIN_TAKE_COVERAGE,
) -> TakeMeasurement:
    """The take the gate would accept, steadiest first. Refuses if there is none.

    Identity is a constraint and head roll is a preference, in that order, because they
    fail differently. A take the gate will refuse on identity cannot become acceptable by
    having a still head — the sync only moves the mean by thousandths — so spending $0.50
    syncing it buys a refusal. A take with an unsteady head is merely a worse shot.

    Measured 2026-10-01, and this is why the function exists: run 5 of the pass-rate
    battery had its take chosen on head roll alone (2.78 degrees, the steadiest of four)
    while that take was already failing identity before the sync. The gate refused the
    finished render for exactly the reason a free local measurement would have given
    beforehand.

    Refusing is a real outcome here, not a defensive branch. Over those five runs no take
    of twenty would have qualified, which is the honest state of the pipeline rather than
    a bug in this rule: four of the five finished renders were accepted only because the
    gate could not measure them at all.
    """
    if not takes:
        raise ValueError("no takes to choose between")
    eligible = [
        t for t in takes if t.would_pass_gate(threshold=threshold, min_coverage=min_coverage)
    ]
    if eligible:
        return min(eligible, key=lambda t: t.head_roll_sd_deg)

    # The refusal names the nearest miss, because which constraint failed decides what to
    # do next: thin coverage means she moved out of frame and the motion prompt is the
    # lever, where frames below threshold means the generator drifted off her face.
    scored = [t for t in takes if t.identity_scores]
    if not scored:
        raise ValueError(
            f"no take could be scored for identity at all — best coverage "
            f"{max(t.coverage for t in takes):.0%} against a {min_coverage:.0%} floor. "
            "She is not visible enough in any take to verify, so none can be used."
        )
    covered = [t for t in scored if t.coverage >= min_coverage]
    if not covered:
        best = max(scored, key=lambda t: t.coverage)
        raise ValueError(
            f"no take cleared the {min_coverage:.0%} coverage floor — best was "
            f"{best.path.name} at {best.coverage:.0%} "
            f"({best.frames_with_face}/{best.frames_sampled} frames scorable). "
            "A take the gate cannot measure is not a take it can accept."
        )
    best = min(covered, key=lambda t: t.frames_below(threshold))
    raise ValueError(
        f"no take passes identity at {threshold} — best was {best.path.name} with "
        f"{best.frames_below(threshold)} of {len(best.identity_scores)} frames below "
        f"(min {best.identity_min:.5f}, mean {best.identity_mean:.5f}). "
        "Syncing it would buy a refusal; shoot more takes."
    )
