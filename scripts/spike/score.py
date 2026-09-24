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
    frames_sampled: int
    frames_usable: int
    no_face_frames: int
    multi_face_frames: int
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
    def passes_threshold(self) -> bool:
        return self.identity_score_min is not None and self.identity_score_min >= self.threshold

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
    def verdict(self) -> str:
        """One of PASS, FAIL, INDETERMINATE. See the module docstring."""
        if self.identity_score_min is not None and not self.passes_threshold:
            # A frame we looked at was not her. Coverage cannot rescue that.
            return FAIL
        if not self.has_enough_coverage:
            return INDETERMINATE
        return PASS

    @property
    def passed(self) -> bool:
        """Strict pass. Indeterminate is not a pass -- nor is it a failure."""
        return self.verdict == PASS

    @property
    def needs_review(self) -> bool:
        return self.verdict == INDETERMINATE

    @property
    def failure_reason(self) -> str | None:
        """Why the clip is not a clean pass. Present for FAIL and INDETERMINATE."""
        if self.verdict == PASS:
            return None
        if self.verdict == FAIL:
            assert self.identity_score_min is not None
            return (
                f"min similarity {self.identity_score_min:.4f} below threshold {self.threshold:.4f}"
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
        out["verdict"] = self.verdict
        out["passed"] = self.passed
        out["needs_review"] = self.needs_review
        out["failure_reason"] = self.failure_reason
        return out


def score_embedding_set(
    embeddings: EmbeddingSet,
    master: EmbeddingSet,
    calibration: Calibration,
    ref: str,
    min_face_presence: float = DEFAULT_MIN_FACE_PRESENCE,
    condition: dict[str, str] | None = None,
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
        frames_sampled=counts["frames"],
        frames_usable=counts["usable"],
        no_face_frames=counts[NO_FACE],
        multi_face_frames=counts[MULTI_FACE],
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
) -> ClipScore:
    """Extract frames from a clip, embed them, and score against the master set."""
    clip = Path(clip)
    source = frame_source or default_frame_source(clip)
    dest = Path(frames_dir) if frames_dir else clip.parent / f"{clip.stem}_frames"
    frame_paths = source.extract(clip, dest, fps)
    embeddings = embed_images(embedder, frame_paths, label=clip.name, fps=fps)
    return score_embedding_set(embeddings, master, calibration, ref, min_face_presence, condition)


def pass_rate_by_condition(scores: list[ClipScore]) -> dict[str, dict[str, dict[str, Any]]]:
    """Pass rate broken down by each axis level.

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
                {"clips": 0, "passed": 0, "failed": 0, "indeterminate": 0, "min_scores": []},
            )
            bucket["clips"] += 1
            bucket["passed"] += int(score.verdict == PASS)
            bucket["failed"] += int(score.verdict == FAIL)
            bucket["indeterminate"] += int(score.verdict == INDETERMINATE)
            if score.identity_score_min is not None:
                bucket["min_scores"].append(score.identity_score_min)
    for levels in out.values():
        for stats in levels.values():
            mins = stats.pop("min_scores")
            stats["pass_rate"] = stats["passed"] / stats["clips"] if stats["clips"] else 0.0
            # Of the clips we could actually judge. Reported alongside, not
            # instead of, pass_rate: which denominator is right depends on
            # whether the indeterminates are a property of the shot or the model.
            judged = stats["passed"] + stats["failed"]
            stats["pass_rate_of_judged"] = stats["passed"] / judged if judged else None
            stats["worst_min_score"] = min(mins) if mins else None
            stats["mean_min_score"] = float(np.mean(mins)) if mins else None
    return out
