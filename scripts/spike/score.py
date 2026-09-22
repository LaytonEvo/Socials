"""Scoring a clip against the master set.

The scoring rule is where a quiet mistake would do the most damage, so it is
spelled out here rather than left implicit.

A clip passes only if **both** hold:

1. its lowest per-frame similarity clears the calibrated threshold, and
2. a face was actually found in at least ``min_face_presence`` of sampled frames.

Condition 2 exists because condition 1 alone is gameable by the failure mode we
most care about. If the model loses the face for two seconds, those frames yield
no vector; taking min/mean over only the *usable* frames would score that clip
on the frames where it behaved, and report a clean pass on a clip with a
two-second hole in it. The plan's own acceptance criteria for task 1.2 -- handle
no-face and multi-face frames "explicitly" -- is what this implements.

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

DEFAULT_MIN_FACE_PRESENCE = 0.9


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
    def passes_presence(self) -> bool:
        return self.face_presence >= self.min_face_presence

    @property
    def passed(self) -> bool:
        return self.passes_threshold and self.passes_presence

    @property
    def failure_reason(self) -> str | None:
        if self.passed:
            return None
        if self.frames_usable == 0:
            return "no face found in any sampled frame"
        reasons = []
        if not self.passes_threshold:
            assert self.identity_score_min is not None
            reasons.append(
                f"min similarity {self.identity_score_min:.4f} below threshold {self.threshold:.4f}"
            )
        if not self.passes_presence:
            reasons.append(
                f"face present in only {self.face_presence:.0%} of sampled frames "
                f"(need {self.min_face_presence:.0%})"
            )
        return "; ".join(reasons)

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["face_presence"] = self.face_presence
        out["passed"] = self.passed
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
                level, {"clips": 0, "passed": 0, "min_scores": []}
            )
            bucket["clips"] += 1
            bucket["passed"] += int(score.passed)
            if score.identity_score_min is not None:
                bucket["min_scores"].append(score.identity_score_min)
    for levels in out.values():
        for stats in levels.values():
            mins = stats.pop("min_scores")
            stats["pass_rate"] = stats["passed"] / stats["clips"] if stats["clips"] else 0.0
            stats["worst_min_score"] = min(mins) if mins else None
            stats["mean_min_score"] = float(np.mean(mins)) if mins else None
    return out
