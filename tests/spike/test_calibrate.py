"""Calibration statistics, including a regression for a real bug."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from scripts.spike.calibrate import (
    calibrate,
    equal_error_rate,
    ks_statistic,
    overlap_coefficient,
    roc_auc,
    threshold_at_fpr,
    verdict_for,
)
from scripts.spike.embed import EmbedderInfo

INFO = EmbedderInfo("test", "m", "1", 256, licence="x")
STUB_INFO = EmbedderInfo("stub", "pixel-stats", "0", 256)
TODAY = dt.date(2026, 9, 22)


def test_overlap_survives_a_tiny_gap_at_the_top_of_the_range():
    """Regression: fixed-width bins reported 0.5 overlap on disjoint data.

    Same-face similarities cluster just under 1.0 while the different-face tail
    runs down towards -1.0. With 50 fixed bins across that range, each bin was
    ~0.04 wide -- far wider than the real gap between the distributions -- so
    perfectly separated data landed in one shared bin and scored 0.5. The
    statistic was measuring bin resolution, and it reported POOR on a clean
    separation, which at Gate A would kill a viable approach for no reason.
    """
    positives = np.linspace(0.9910, 1.0000, 45)
    negatives = np.concatenate([np.linspace(-0.99, -0.90, 80), np.linspace(0.980, 0.9906, 80)])
    assert roc_auc(positives, negatives) == 1.0
    assert overlap_coefficient(positives, negatives) == pytest.approx(0.0, abs=1e-9)
    assert verdict_for(1.0, overlap_coefficient(positives, negatives)) == "EXCELLENT"


def test_overlap_is_one_for_identical_distributions():
    x = np.linspace(0.3, 0.9, 200)
    assert overlap_coefficient(x, x) == pytest.approx(1.0)


def test_overlap_is_zero_for_disjoint_distributions():
    assert overlap_coefficient(np.linspace(0.8, 0.9, 50), np.linspace(0.1, 0.2, 50)) == 0.0


def test_auc_handles_ties_at_a_half():
    x = np.zeros(10)
    assert roc_auc(x, x) == pytest.approx(0.5)


def test_auc_is_one_when_separated_and_zero_when_inverted():
    hi, lo = np.linspace(0.8, 0.9, 20), np.linspace(0.1, 0.2, 20)
    assert roc_auc(hi, lo) == 1.0
    assert roc_auc(lo, hi) == 0.0


def test_ks_equals_best_achievable_tpr_minus_fpr():
    rng = np.random.default_rng(0)
    pos, neg = rng.normal(0.8, 0.1, 300), rng.normal(0.5, 0.1, 300)
    best = max(
        float((pos >= t).mean() - (neg >= t).mean()) for t in np.unique(np.concatenate([pos, neg]))
    )
    assert ks_statistic(pos, neg) == pytest.approx(best, abs=1e-9)


def test_threshold_meets_the_target_false_positive_rate():
    rng = np.random.default_rng(1)
    pos, neg = rng.normal(0.9, 0.02, 500), rng.normal(0.4, 0.05, 500)
    _thr, fpr, tpr = threshold_at_fpr(pos, neg, 0.01)
    assert fpr <= 0.01
    assert tpr > 0.9


def test_equal_error_rate_balances_the_two_errors():
    rng = np.random.default_rng(2)
    pos, neg = rng.normal(0.7, 0.1, 400), rng.normal(0.5, 0.1, 400)
    thr, eer = equal_error_rate(pos, neg)
    assert 0.0 <= eer <= 0.5
    assert float(neg.min()) <= thr <= float(pos.max())


def test_poor_separation_is_called_out_as_a_finding():
    rng = np.random.default_rng(3)
    cal = calibrate(rng.normal(0.6, 0.12, 300), rng.normal(0.55, 0.12, 300), INFO, today=TODAY)
    assert cal.verdict == "POOR"
    assert cal.trustworthy is False
    assert any("advisory rather than gating" in w for w in cal.warnings)


def test_small_samples_are_flagged():
    cal = calibrate(np.linspace(0.8, 0.9, 10), np.linspace(0.1, 0.2, 10), INFO, today=TODAY)
    assert any("Small sample" in w for w in cal.warnings)


def test_stub_calibration_is_marked_as_not_evidence():
    cal = calibrate(np.linspace(0.8, 0.9, 80), np.linspace(0.1, 0.2, 80), STUB_INFO, today=TODAY)
    assert cal.embedder_is_stub is True
    assert any("must not reach a Gate A report" in w for w in cal.warnings)


def test_disagreement_between_d_prime_and_auc_is_flagged():
    """Non-normal distributions make d' misleading; say so rather than hide it."""
    # The shape the real fixtures produce: positives packed just under 1.0,
    # negatives BIMODAL at the two extremes. d' assumes normality and reads
    # ~1.4 here, while the distributions are in fact perfectly separated.
    positives = np.concatenate([np.full(40, 0.999), np.full(5, 0.9911)])
    negatives = np.concatenate([np.full(80, -0.99), np.full(80, 0.98)])
    cal = calibrate(positives, negatives, INFO, today=TODAY)
    assert cal.auc >= 0.99
    assert any("disagree" in w for w in cal.warnings)


def test_calibration_needs_both_distributions():
    with pytest.raises(ValueError, match="same-face and different-face"):
        calibrate([0.9, 0.8], [], INFO, today=TODAY)


def test_target_finer_than_the_control_set_can_express_is_clamped():
    """The 2026-09-24 gate bug: a target below 1/n silently becomes FPR = 0.

    With 50 different-face samples the achievable rates are 0, 2%, 4%, ... so a
    request for 1% is satisfiable only at 0%, which pushes the threshold above
    the highest-scoring control and throws away same-face images to get there.
    Nothing warned at the time, because the achieved FPR was *inside* the
    target. The shape below is the real one in miniature: one low positive and
    one high negative, each an outlier that would otherwise set the gate.
    """
    positives = np.array([0.95] + [0.98] * 49)
    negatives = np.array([0.90] * 49 + [0.96])

    cal = calibrate(positives, negatives, INFO, target_fpr=0.01, today=TODAY)

    assert cal.fpr_resolution == pytest.approx(0.02)
    assert any("finer than" in w for w in cal.warnings)
    # Clamped to 2%: the threshold sits below the lone high control rather than
    # above it, and the lone low positive is kept.
    assert cal.threshold == pytest.approx(0.95)
    assert cal.tpr_at_threshold == pytest.approx(1.0)
    assert any("2.0% of the same-face images" in w for w in cal.warnings)


def test_a_target_the_control_set_can_express_is_left_alone():
    rng = np.random.default_rng(11)
    cal = calibrate(rng.normal(0.9, 0.02, 300), rng.normal(0.4, 0.05, 300), INFO, today=TODAY)
    assert cal.fpr_resolution == pytest.approx(1 / 300)
    assert not any("finer than" in w for w in cal.warnings)


def test_the_raw_distributions_are_kept_not_just_their_summaries():
    """Summary stats cannot be re-analysed; recovering them costs a re-embed."""
    cal = calibrate([0.9, 0.95, 0.99], [0.1, 0.2], INFO, today=TODAY)
    assert cal.positive_values == [0.9, 0.95, 0.99]
    assert cal.negative_values == [0.1, 0.2]
    assert cal.to_json()["positive_values"] == [0.9, 0.95, 0.99]
