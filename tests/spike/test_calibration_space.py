"""The calibrated threshold must live in the space the scorer reads.

Regression for a bug that made every threshold systematically too lenient:
`calibrate` built its distributions from *pairwise* similarities while
`score.py` compares each frame to the master *centroid*. Centroid similarity
runs higher than pairwise similarity — averaging cancels noise that a single
other image still carries — so the cut point sat below where the scorer reads,
and takes that should have been rejected passed.

It was not caught by any statistic. Overlap, AUC and TPR were all computed
inside the pairwise space and were all internally consistent and excellent
there. It surfaced only when per-image centroid scores were printed next to
the threshold and a stranger's score sat above it.
"""

from __future__ import annotations

import numpy as np

from scripts.spike.embed import (
    EmbedderInfo,
    centroid_similarities,
    cosine,
    l2_normalise,
    leave_one_out_centroid_similarities,
    pairwise_similarities,
)

INFO = EmbedderInfo("test", "m", "1", 128, licence="x")


def _cluster(rng, base, spread, n):
    return [l2_normalise(base + spread * rng.normal(size=128).astype(np.float32)) for _ in range(n)]


def test_centroid_similarity_runs_higher_than_pairwise():
    """The gap that made the old threshold too lenient. It is not small."""
    rng = np.random.default_rng(0)
    base = l2_normalise(rng.normal(size=128).astype(np.float32))
    vecs = _cluster(rng, base, 0.35, 28)

    assert np.mean(leave_one_out_centroid_similarities(vecs)) > np.mean(pairwise_similarities(vecs))


def test_a_stranger_the_calibration_rejects_is_rejected_by_the_scorer():
    """The invariant that ties the two halves together.

    If calibration and scoring ever drift into different spaces again, the
    threshold stops meaning what the scorer thinks it means and this fails.
    """
    from scripts.spike.calibrate import calibrate

    rng = np.random.default_rng(7)
    her = l2_normalise(rng.normal(size=128).astype(np.float32))
    master = _cluster(rng, her, 0.30, 28)
    # Strangers, but close ones — the hard control set, not random people.
    stranger = l2_normalise(her + 0.55 * rng.normal(size=128).astype(np.float32))
    control = _cluster(rng, stranger, 0.30, 15)

    centroid = l2_normalise(np.stack(master).mean(axis=0))
    positives = leave_one_out_centroid_similarities(master)
    negatives = centroid_similarities(control, centroid)
    cal = calibrate(positives, negatives, INFO, target_fpr=0.01)

    # Every control image the calibration counted as a rejection must also be
    # rejected when scored the way score.py scores it.
    for vec in control:
        scored = cosine(vec, centroid)
        if scored < cal.threshold:
            continue
        # A control image at or above the threshold is a false accept, and the
        # calibration must have owned up to it in its reported FPR.
        assert cal.fpr_at_threshold > 0.0, (
            f"a control image scores {scored:.4f} against the master centroid, "
            f"at or above the threshold {cal.threshold:.4f}, yet the calibration "
            f"reported fpr {cal.fpr_at_threshold:.4f}. The threshold was measured "
            "in a different space from the one the scorer reads."
        )


def test_a_vector_is_not_compared_against_a_centroid_it_helped_build():
    """Leave-one-out. Including it flatters the positives for the same reason."""
    rng = np.random.default_rng(3)
    base = l2_normalise(rng.normal(size=128).astype(np.float32))
    vecs = _cluster(rng, base, 0.4, 12)

    loo = leave_one_out_centroid_similarities(vecs)
    full = centroid_similarities(vecs, l2_normalise(np.stack(vecs).mean(axis=0)))
    assert np.mean(loo) < np.mean(full)


def test_too_few_images_yields_no_positive_distribution():
    assert leave_one_out_centroid_similarities([]) == []
    assert leave_one_out_centroid_similarities([np.ones(128, dtype=np.float32)]) == []


def test_no_master_centroid_yields_no_negatives():
    assert centroid_similarities([np.ones(128, dtype=np.float32)], None) == []
