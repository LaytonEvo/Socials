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


def test_one_low_frame_does_not_fail_a_clip(embedder, master):
    """The minimum cannot carry the verdict; see the score.py module docstring.

    One frame below the threshold out of four is the shape of a head turning
    through its most extreme pose, and rejecting on it threw away footage the
    owner confirmed was good.
    """
    info = embedder.info
    clip = _frames(info, [0.99, 0.99, 0.80, 0.99], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.frames_below_threshold == 1
    assert score.longest_run_below_threshold == 1
    assert score.longest_run_fraction == pytest.approx(0.25)
    # Not a failure -- but not certified either. The owner asked for the review
    # lane to widen rather than the failure lane (score.py, 2026-09-24).
    assert score.identity_verdict != "fail"
    assert score.identity_verdict == "indeterminate"
    assert score.needs_review is True


def test_a_sustained_run_below_threshold_fails_the_clip(embedder, master):
    info = embedder.info
    clip = _frames(info, [0.80, 0.80, 0.80, 0.99], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.longest_run_fraction == pytest.approx(0.75)
    assert score.identity_verdict == "fail"
    assert score.failure_reason is not None
    assert "3 readable frames in a row" in score.failure_reason


def test_the_same_dips_scattered_do_not_fail_the_clip(embedder, master):
    """Contiguity is the signal, not the count.

    Same number of frames under the threshold as the test above, spread out
    instead of consecutive: a head passing through an extreme pose and
    recovering, rather than the identity going and staying gone.
    """
    info = embedder.info
    clip = _frames(info, [0.80, 0.99, 0.80, 0.99, 0.80, 0.99], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.frames_below_threshold == 3
    assert score.longest_run_below_threshold == 1
    # Contiguity still decides failure: three scattered dips are not a drift.
    assert score.identity_verdict != "fail"
    assert score.identity_verdict == "indeterminate"


def test_the_verdict_does_not_move_when_the_same_clip_is_sampled_denser(embedder, master):
    """Stability under sampling density is the whole point of the change.

    `min` fails this: doubling the frames can only lower it, and on real clips
    it flipped 3 of 31 verdicts between 2 and 8 fps. A fraction does not move
    when the extra frames look like the ones already there.
    """
    info = embedder.info
    sparse = _frames(info, [0.99, 0.80, 0.99, 0.99], master.centroid())
    dense = _frames(info, [0.99, 0.985, 0.80, 0.78, 0.99, 0.99, 0.99, 0.99], master.centroid())
    cal = _calibration(info)
    a = score_embedding_set(sparse, master, cal, ref="a")
    b = score_embedding_set(dense, master, cal, ref="b")
    assert (b.identity_score_min or 0) < (a.identity_score_min or 0)  # the minimum sank
    assert a.identity_verdict == b.identity_verdict  # the verdict did not move
    assert a.identity_verdict != "fail"


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
    assert score.identity_verdict == "indeterminate"
    assert score.identity_passed is False
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
    assert score.identity_verdict == "fail"
    assert score.failure_reason is not None
    assert "below threshold" in score.failure_reason


def test_a_clip_with_no_face_at_all_is_unverified_not_failed(embedder, master):
    info = embedder.info
    clip = _frames(info, [None, None, None, None], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.identity_score_min is None
    assert score.identity_verdict == "indeterminate"
    assert score.failure_reason is not None
    assert "unverified" in score.failure_reason


def test_full_coverage_certifies_a_clip_too_short_for_the_frame_floor(embedder, master):
    """The absolute floor bounds UNSEEN frames; a short clip has none."""
    info = embedder.info
    clip = _frames(info, [0.99, 0.98], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.frames_usable == 2 < 4
    assert score.face_presence == pytest.approx(1.0)
    assert score.identity_verdict == "pass"


def test_clip_passes_when_both_rules_hold(embedder, master):
    info = embedder.info
    clip = _frames(info, [0.99, 0.98, 0.97], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.identity_passed is True
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


def test_the_verdict_never_serialises_under_an_unscoped_name(embedder, master):
    """The rename exists to stop a misreading, so pin it.

    A bare `pass` on a rating sheet was read as "this clip is good" for a clip
    that was visibly AI-generated. The scorer had answered its own question
    correctly; the name promised more than it measured. Nothing in the JSON a
    human or a later tool reads may say `verdict` or `passed` unqualified.
    """
    info = embedder.info
    clip = _frames(info, [0.99, 0.98, 0.97, 0.96], master.centroid())
    out = score_embedding_set(clip, master, _calibration(info), ref="r").to_json()

    assert out["identity_verdict"] == "pass"
    assert out["identity_passed"] is True
    assert "verdict" not in out
    assert "passed" not in out


def test_a_clean_clip_still_passes_outright(embedder, master):
    """Strictness must not collapse into 'everything needs a human'.

    Widening the review lane is only useful if clips with nothing wrong still
    clear it on their own.
    """
    info = embedder.info
    clip = _frames(info, [0.99, 0.98, 0.985, 0.99, 0.99], master.centroid())
    score = score_embedding_set(clip, master, _calibration(info), ref="r")
    assert score.frames_below_threshold == 0
    assert score.identity_verdict == "pass"
    assert score.needs_review is False
