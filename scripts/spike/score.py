"""Scoring a clip against the master set.

The scoring rule is where a quiet mistake would do the most damage, so it is
spelled out here rather than left implicit.

Scoring is three-valued, because two of the questions it answers are different
questions:

* **fail** -- a frame we actually looked at scored below the calibrated
  threshold. Positive evidence that identity broke. Regenerate.
* **indeterminate** -- nothing we looked at failed, but we did not see enough
  of the face to certify the clip. Send it to the human who has to approve it
  anyway.
* **pass** -- enough of the face was seen, and all of it cleared the threshold.

The middle case is why this is not a boolean. **A missing face is
uninformative.** When the detector finds nothing we cannot tell "she turned
away from camera" from "her face melted": both produce zero vectors. Treating
absence as failure therefore throws away good footage, and it did. Measured
2026-09-24: ``battery-walking_fairway`` scored 0.9914, 0.9899 and 0.9761 on its
first three frames and then showed her from behind for the remaining five, as a
shot of someone walking away down a fairway is supposed to. The clip was fine.
The old rule -- face present in >= 90% of frames or fail -- rejected it, and the
0.9 was never derived from anything.

So coverage no longer fails a clip. It decides whether the verdict is
trustworthy: below ``min_face_presence`` of sampled frames, or fewer than
``MIN_USABLE_FRAMES`` usable ones, the clip is *indeterminate* rather than
passed. An observed bad frame still fails the clip outright, whatever the
coverage -- seeing a bad frame is evidence, unlike not seeing a face.

This keeps what the old condition 2 was actually protecting: a clip with a hole
in it is never silently certified on the frames where it behaved. It just stops
calling that certification failure. The plan's acceptance criteria for task 1.2
-- handle no-face and multi-face frames "explicitly" -- is what this implements.

A clip fails when **too large a fraction of the frames we could read** fall
below the calibrated threshold -- not when its single worst frame does.

The minimum was the rule until 2026-09-24 and it is unusable, because `min`
only decreases as you sample more. Denser sampling gets closer to the instant
the detector loses the face, which is the most extreme pose in the clip and so
the lowest-scoring frame: the verdict was handed to the *least* informative
frame, and which frame that was depended on the sampling rate rather than on
the clip. Measured across 31 clips at 2 and 8 fps, `min` changed its verdict on
3 of them and rejected both clips the owner had confirmed were good.

`mean < threshold` scores identically well on that data and is still wrong: the
threshold is calibrated on the distribution of INDIVIDUAL image-to-centroid
similarities, and the mean of several frames has a different, narrower
distribution. Comparing it to that threshold repeats the calibration-space
error of `calibration-2026-09-23-corrected.md` -- a threshold is only
meaningful in the space it was measured in. Counting frames below the
threshold uses it in exactly that space.

Similarity is cosine against the L2-normalised centroid of the master set.
Max-similarity to any single master image is also recorded, because the two
disagreeing is itself informative: it means the master set is not internally
coherent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .calibrate import Calibration
from .embed import MULTI_FACE, NO_FACE, Embedder, EmbeddingSet, cosine, embed_images
from .errors import CalibrationMismatch
from .frames import FrameSource, default_frame_source

# Coverage below which a verdict is not trusted. NOT a pass mark: see the
# module docstring. The 28 clips generated in the spike sit at 100% or 87.5%
# presence, and the one legitimate low-coverage clip sits at 37.5%, so the
# evidence brackets this value to (0.375, 0.875] and does not pin it further.
# 0.5 is chosen within that bracket on the principle that a verdict should rest
# on the majority of the frames sampled, and is cheap to revisit -- being wrong
# here now costs a human glance, not a discarded clip.
DEFAULT_MIN_FACE_PRESENCE = 0.5

# Longest CONTIGUOUS stretch of readable frames that may fall below the
# threshold, as a share of the readable frames, before the clip is a failure.
#
# Contiguity is the point. Scattered frames below the threshold are a head
# passing through its most extreme pose and coming back; a sustained run is the
# identity going and not returning, which is the failure this gate exists for.
# That is the same distinction as everything else measured on 2026-09-24.
#
# Derived 2026-09-24 across 31 clips scored at 2 and 8 fps: the
# two clips that are a visibly different woman sit at 100% at both rates and one
# drifted clip at 75/76%, while every clip believed good stays at or below 33%.
# To be stable the allowance must not fall inside any clip's own 2-to-8 fps
# span. On this data the run and the plain fraction are indistinguishable --
# the below-threshold frames in these clips are contiguous anyway -- but the
# run stays stable down to 0.4 where the fraction flips at 0.33, so it is
# stricter at equal stability. The bracket rests on two confirmed-bad clips,
# so it is wide and provisional.
MAX_RUN_BELOW_THRESHOLD = 0.4

# Absolute floor on evidence, independent of clip length. At 2 fps a short clip
# can clear a 50% ratio on two adjacent frames, which is one moment seen twice.
MIN_USABLE_FRAMES = 4

PASS = "pass"
FAIL = "fail"
INDETERMINATE = "indeterminate"


@dataclass
class FrameScore:
    index: int
    timestamp_s: float
    status: str
    similarity: float | None
    source: str | None


@dataclass
class ClipScore:
    """One take, scored. Mirrors BUILD_PLAN's `generation` identity fields."""

    ref: str
    label: str
    embedder_key: str
    threshold: float
    min_face_presence: float
    max_run_below: float
    frames_sampled: int
    frames_usable: int
    no_face_frames: int
    multi_face_frames: int
    frames_below_threshold: int
    longest_run_below_threshold: int
    identity_score_min: float | None
    identity_score_mean: float | None
    max_similarity_any_master: float | None
    worst_frame_source: str | None
    per_frame: list[FrameScore] = field(default_factory=list)
    condition: dict[str, str] | None = None

    @property
    def face_presence(self) -> float:
        if self.frames_sampled == 0:
            return 0.0
        return self.frames_usable / self.frames_sampled

    @property
    def fraction_below_threshold(self) -> float | None:
        """Share of readable frames that did not look like her. None if no face."""
        if not self.frames_usable:
            return None
        return self.frames_below_threshold / self.frames_usable

    @property
    def longest_run_fraction(self) -> float | None:
        """Longest unbroken stretch below threshold, as a share of readable frames."""
        if not self.frames_usable:
            return None
        return self.longest_run_below_threshold / self.frames_usable

    @property
    def passes_threshold(self) -> bool:
        """Whether the identity held for long enough at a stretch.

        Deliberately NOT ``identity_score_min >= threshold``; see the module
        docstring for why the minimum cannot carry a verdict.
        """
        run = self.longest_run_fraction
        return run is None or run <= self.max_run_below

    @property
    def has_enough_coverage(self) -> bool:
        """Whether enough of the face was seen for the verdict to be trusted."""
        if self.frames_sampled and self.frames_usable == self.frames_sampled:
            # Nothing went unseen. The frame count is then a property of clip
            # length and sample rate -- the harness's business, not the clip's
            # -- so a short fully-visible clip is certifiable like any other.
            return True
        return (
            self.face_presence >= self.min_face_presence and self.frames_usable >= MIN_USABLE_FRAMES
        )

    @property
    def identity_verdict(self) -> str:
        """One of PASS, FAIL, INDETERMINATE -- about IDENTITY, nothing else.

        Named for its scope because the unscoped name caused a real error. A
        clip marked a bare ``pass`` was read as "this clip is good"; it was in
        fact visibly AI-generated, and the scorer had answered the only
        question it can answer -- is this her face in the frames sampled --
        correctly. See docs/reports/identity-gate-blind-spot-2026-09-24.md.
        """
        if self.frames_usable and not self.passes_threshold:
            # A frame we looked at was not her. Coverage cannot rescue that.
            return FAIL
        if not self.has_enough_coverage:
            return INDETERMINATE
        return PASS

    @property
    def identity_passed(self) -> bool:
        """Identity verified. NOT a judgement that the clip is usable."""
        return self.identity_verdict == PASS

    @property
    def needs_review(self) -> bool:
        return self.identity_verdict == INDETERMINATE

    @property
    def failure_reason(self) -> str | None:
        """Why the clip is not a clean pass. Present for FAIL and INDETERMINATE."""
        if self.identity_verdict == PASS:
            return None
        if self.identity_verdict == FAIL:
            run = self.longest_run_fraction
            assert run is not None
            return (
                f"{self.longest_run_below_threshold} readable frames in a row "
                f"({run:.0%} of {self.frames_usable}) below threshold "
                f"{self.threshold:.4f}, over the {self.max_run_below:.0%} allowed"
            )
        if self.frames_usable == 0:
            return "no face found in any sampled frame, so identity is unverified"
        reasons = []
        if self.face_presence < self.min_face_presence:
            reasons.append(
                f"face present in only {self.face_presence:.0%} of sampled frames "
                f"(need {self.min_face_presence:.0%} to certify)"
            )
        if self.frames_usable < MIN_USABLE_FRAMES:
            reasons.append(f"only {self.frames_usable} usable frame(s) (need {MIN_USABLE_FRAMES})")
        seen = (
            ""
            if self.identity_score_min is None
            else (
                f"; the {self.frames_usable} frame(s) seen were fine "
                f"(min {self.identity_score_min:.4f})"
            )
        )
        return "; ".join(reasons) + seen

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["face_presence"] = self.face_presence
        out["fraction_below_threshold"] = self.fraction_below_threshold
        out["longest_run_fraction"] = self.longest_run_fraction
        out["identity_verdict"] = self.identity_verdict
        out["identity_passed"] = self.identity_passed
        out["needs_review"] = self.needs_review
        out["failure_reason"] = self.failure_reason
        return out


def _longest_run_below(sims: list[float], threshold: float) -> int:
    """Longest unbroken stretch of consecutive frames scoring under threshold.

    Contiguity is what separates a head turning through an extreme pose, which
    dips for a frame or two and recovers, from the identity going and staying
    gone. Scattered dips and a sustained run can share a frame count.
    """
    best = run = 0
    for sim in sims:
        run = run + 1 if sim < threshold else 0
        best = max(best, run)
    return best


def score_embedding_set(
    embeddings: EmbeddingSet,
    master: EmbeddingSet,
    calibration: Calibration,
    ref: str,
    min_face_presence: float = DEFAULT_MIN_FACE_PRESENCE,
    condition: dict[str, str] | None = None,
    max_run_below: float = MAX_RUN_BELOW_THRESHOLD,
) -> ClipScore:
    """Score already-extracted embeddings against the master set."""
    if embeddings.info.key() != calibration.embedder_key:
        raise CalibrationMismatch(
            f"Calibration was produced with {calibration.embedder_key!r} but these "
            f"embeddings come from {embeddings.info.key()!r}. A threshold is valid for "
            f"exactly one embedding model at one version (BUILD_ORDER amendment A3). "
            f"Re-run calibration before scoring."
        )
    centroid = master.centroid()
    if centroid is None:
        raise ValueError("Master set produced no usable embeddings; cannot score against it.")
    master_vectors = master.vectors

    per_frame: list[FrameScore] = []
    sims: list[float] = []
    worst: tuple[float, str | None] = (float("inf"), None)
    best_any = None

    for fe in embeddings.frames:
        if not fe.usable:
            per_frame.append(FrameScore(fe.index, fe.timestamp_s, fe.status, None, fe.source))
            continue
        assert fe.vector is not None
        sim = cosine(fe.vector, centroid)
        sims.append(sim)
        per_frame.append(FrameScore(fe.index, fe.timestamp_s, fe.status, sim, fe.source))
        if sim < worst[0]:
            worst = (sim, fe.source)
        if len(master_vectors):
            any_sim = float(np.max(master_vectors @ fe.vector))
            best_any = any_sim if best_any is None else max(best_any, any_sim)

    counts = embeddings.counts()
    return ClipScore(
        ref=ref,
        label=embeddings.label,
        embedder_key=embeddings.info.key(),
        threshold=calibration.threshold,
        min_face_presence=min_face_presence,
        max_run_below=max_run_below,
        frames_sampled=counts["frames"],
        frames_usable=counts["usable"],
        no_face_frames=counts[NO_FACE],
        multi_face_frames=counts[MULTI_FACE],
        frames_below_threshold=sum(1 for sim in sims if sim < calibration.threshold),
        longest_run_below_threshold=_longest_run_below(sims, calibration.threshold),
        identity_score_min=min(sims) if sims else None,
        identity_score_mean=float(np.mean(sims)) if sims else None,
        max_similarity_any_master=best_any,
        worst_frame_source=worst[1],
        per_frame=per_frame,
        condition=condition,
    )


def score_clip(
    clip: Path,
    embedder: Embedder,
    master: EmbeddingSet,
    calibration: Calibration,
    ref: str,
    fps: float = 2.0,
    frames_dir: Path | None = None,
    frame_source: FrameSource | None = None,
    min_face_presence: float = DEFAULT_MIN_FACE_PRESENCE,
    condition: dict[str, str] | None = None,
    max_run_below: float = MAX_RUN_BELOW_THRESHOLD,
) -> ClipScore:
    """Extract frames from a clip, embed them, and score against the master set."""
    clip = Path(clip)
    source = frame_source or default_frame_source(clip)
    dest = Path(frames_dir) if frames_dir else clip.parent / f"{clip.stem}_frames"
    frame_paths = source.extract(clip, dest, fps)
    embeddings = embed_images(embedder, frame_paths, label=clip.name, fps=fps)
    return score_embedding_set(
        embeddings, master, calibration, ref, min_face_presence, condition, max_run_below
    )


def identity_rate_by_condition(scores: list[ClipScore]) -> dict[str, dict[str, dict[str, Any]]]:
    """Identity pass rate broken down by each axis level.

    This is BUILD_PLAN task 1.7's actual deliverable. A single headline pass
    rate hides the thing the gate needs to know: *which* conditions fail.
    """
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for score in scores:
        if not score.condition:
            continue
        for axis, level in score.condition.items():
            if axis == "cell_id":
                continue
            bucket = out.setdefault(axis, {}).setdefault(
                level,
                {
                    "clips": 0,
                    "identity_passed": 0,
                    "identity_failed": 0,
                    "indeterminate": 0,
                    "min_scores": [],
                },
            )
            bucket["clips"] += 1
            bucket["identity_passed"] += int(score.identity_verdict == PASS)
            bucket["identity_failed"] += int(score.identity_verdict == FAIL)
            bucket["indeterminate"] += int(score.identity_verdict == INDETERMINATE)
            if score.identity_score_min is not None:
                bucket["min_scores"].append(score.identity_score_min)
    for levels in out.values():
        for stats in levels.values():
            mins = stats.pop("min_scores")
            stats["identity_pass_rate"] = (
                stats["identity_passed"] / stats["clips"] if stats["clips"] else 0.0
            )
            # Of the clips we could actually judge. Reported alongside, not
            # instead of, pass_rate: which denominator is right depends on
            # whether the indeterminates are a property of the shot or the model.
            judged = stats["identity_passed"] + stats["identity_failed"]
            stats["identity_pass_rate_of_judged"] = (
                stats["identity_passed"] / judged if judged else None
            )
            stats["worst_min_score"] = min(mins) if mins else None
            stats["mean_min_score"] = float(np.mean(mins)) if mins else None
    return out
