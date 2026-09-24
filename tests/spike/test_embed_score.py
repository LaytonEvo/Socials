"""Embedding bookkeeping and the clip pass rule.

The pass rule is the harness's most consequential piece of logic: it decides
which takes a human ever sees, and in Phase 3 it becomes auto-reject.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from scripts.spike.calibrate import Calibration
from scripts.spike.embed import (
    MULTI_FACE,
    NO_FACE,
    EmbedderInfo,
    EmbeddingSet,
    FrameEmbedding,
    embed_images,
    l2_normalise,
)
from scripts.spike.errors import CalibrationMismatch
from scripts.spike.score import score_embedding_set
from tests.spike.conftest import make_stills

TODAY = dt.date(2026, 9, 22)


def _calibration(info: EmbedderInfo, threshold: float = 0.9) -> Calibration:
    return Calibration(
        embedder_key=info.key(),
        embedder_is_stub=info.is_stub,
        calibrated_on=TODAY,
        threshold=threshold,
        target_fpr=0.01,
        fpr_at_threshold=0.0,
        tpr_at_threshold=1.0,
        eer_threshold=threshold,
        eer=0.0,
        auc=1.0,
        d_prime=5.0,
        overlap=0.0,
        verdict="EXCELLENT",
    )


def _frames(info: EmbedderInfo, sims: list[float | None], base: np.ndarray) -> EmbeddingSet:
    """Build frames whose similarity to ``base`` is approximately ``sims``."""
    out = []
    for i, s in enumerate(sims):
        if s is None:
            out.append(FrameEmbedding(i, i / 2, NO_FACE, faces=0))
            continue
        orth = np.zeros_like(base)
        orth[1] = 1.0
        orth = l2_normalise(orth - np.dot(orth, base) * base)
        vec = l2_normalise(s * base + np.sqrt(max(0.0, 1 - s * s)) * orth)
        out.append(FrameEmbedding(i, i / 2, "ok", faces=1, vector=vec))
    return EmbeddingSet(frames=out, info=info, label="clip")


def test_no_face_and_multi_face_are_counted_not_dropped(embedder, tmp_path):
    stills = make_stills(tmp_path / "s", "look-a", 2)
    (tmp_path / "s" / "f__noface.png").write_bytes(stills[0].read_bytes())
    (tmp_path / "s" / "f__multiface.png").write_bytes(stills[0].read_bytes())
    es = embed_images(embedder, sorted((tmp_path / "s").glob("*.png")), fps=2.0)
    counts = es.counts()
    assert counts["frames"] == 4
    assert counts["usable"] == 2
    assert counts[NO_FACE] == 1
    assert counts[MULTI_FACE] == 1


def test_centroid_is_none_when_nothing_usable(embedder):
    info = embedder.info
    es = EmbeddingSet([FrameEmbedding(0, 0.0, NO_FACE, faces=0)], info)
    assert es.centroid() is None


def test_clip_fails_when_min_score_is_below_threshold(embedder, master):
    info = embedder.info
    base = master.centroid()
    clip = _frames(info, [0.99, 0.99, 0.80, 0.99], base)
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.passed is False
    assert score.failure_reason is not None
    assert "below threshold" in score.failure_reason


def test_face_loss_makes_a_clip_indeterminate_not_failed(embedder, master):
    """Losing the face is missing evidence, not evidence of a problem.

    Every frame where the face IS found scores 0.99. Taking min/mean over only
    the usable frames would call this a clean pass on a clip half of which was
    never inspected, so it must not pass. But it must not fail either: a
    detector finding nothing cannot distinguish "she turned away" from "her
    face melted", and calling absence a failure threw away a good clip for
    real (see the module docstring).
    """
    info = embedder.info
    base = master.centroid()
    clip = _frames(info, [0.99, None, None, 0.99], base)
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.identity_score_min == pytest.approx(0.99, abs=1e-6)
    assert score.passes_threshold is True
    assert score.verdict == "indeterminate"
    assert score.passed is False
    assert score.needs_review is True
    assert score.failure_reason is not None
    assert "seen were fine" in score.failure_reason


def test_a_bad_frame_fails_the_clip_however_little_was_seen(embedder, master):
    """Seeing a bad frame IS evidence, unlike not seeing a face.

    Low coverage downgrades a clean clip to indeterminate; it must never
    upgrade a clip with an observed bad frame out of failing.
    """
    info = embedder.info
    clip = _frames(info, [0.55, None, None, None], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.face_presence == pytest.approx(0.25)
    assert score.verdict == "fail"
    assert score.failure_reason is not None
    assert "below threshold" in score.failure_reason


def test_a_clip_with_no_face_at_all_is_unverified_not_failed(embedder, master):
    info = embedder.info
    clip = _frames(info, [None, None, None, None], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.identity_score_min is None
    assert score.verdict == "indeterminate"
    assert score.failure_reason is not None
    assert "unverified" in score.failure_reason


def test_full_coverage_certifies_a_clip_too_short_for_the_frame_floor(embedder, master):
    """The absolute floor bounds UNSEEN frames; a short clip has none."""
    info = embedder.info
    clip = _frames(info, [0.99, 0.98], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.frames_usable == 2 < 4
    assert score.face_presence == pytest.approx(1.0)
    assert score.verdict == "pass"


def test_clip_passes_when_both_rules_hold(embedder, master):
    info = embedder.info
    clip = _frames(info, [0.99, 0.98, 0.97], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.passed is True
    assert score.failure_reason is None


def test_scoring_refuses_a_calibration_from_a_different_embedder(embedder, master):
    other = EmbedderInfo("other", "m", "9", 256)
    clip = _frames(embedder.info, [0.99], master.centroid())
    with pytest.raises(CalibrationMismatch, match="amendment A3"):
        score_embedding_set(clip, master, _calibration(other), ref="r")


def test_worst_frame_is_the_one_a_reviewer_should_see(embedder, master):
    info = embedder.info
    clip = _frames(info, [0.99, 0.70, 0.95], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.identity_score_min == pytest.approx(0.70, abs=1e-6)
