"""Threshold calibration (BUILD_PLAN task 1.3 / spike task S0.3).

Produces a pass threshold from two measured distributions:

* **positives** -- similarities between images of the same identity (within the
  master set)
* **negatives** -- similarities between the master set and a control set of
  different faces

The output that matters is not the threshold. It is how much the two
distributions *overlap*. A threshold drawn across two distributions that sit on
top of each other is a number with no meaning, and reporting it without the
overlap would be the most dangerous thing this harness could do -- every
downstream measurement would inherit false confidence.

So :func:`calibrate` reports separation first and the threshold second, and
stamps a verdict that says plainly when the instrument is not good enough.

A note on what is being measured, carried from ADR 0002: the master set is
itself synthetic, so the positive distribution partly reflects the consistency
of the image generator rather than identity as such. Read the threshold as
"consistent with our generator's rendering of this look", not as an identity
guarantee.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .embed import EmbedderInfo

# Triage cut-offs. Deliberately conservative: they decide whether a human is
# told the instrument is trustworthy, and the cost of a false "fine" is every
# later measurement.
VERDICT_BANDS = (
    ("EXCELLENT", 0.99, 0.05),
    ("ADEQUATE", 0.95, 0.20),
    ("MARGINAL", 0.85, 0.40),
)
MIN_SAMPLES_FOR_CONFIDENCE = 50


def _average_ranks(values: np.ndarray) -> np.ndarray:
    """Ranks with ties averaged, so AUC is correct on tied scores."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    sorted_vals = values[order]
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        ranks[order[i : j + 1]] = avg
        i = j + 1
    return ranks


def roc_auc(positives: np.ndarray, negatives: np.ndarray) -> float:
    """P(a random positive scores above a random negative). Ties count a half."""
    n_pos, n_neg = len(positives), len(negatives)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    combined = np.concatenate([positives, negatives])
    ranks = _average_ranks(combined)
    rank_sum_pos = float(ranks[:n_pos].sum())
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def d_prime(positives: np.ndarray, negatives: np.ndarray) -> float:
    """Separation in pooled standard deviations."""
    if len(positives) < 2 or len(negatives) < 2:
        return float("nan")
    var = (positives.var(ddof=1) + negatives.var(ddof=1)) / 2.0
    if var <= 0:
        return float("inf") if positives.mean() != negatives.mean() else 0.0
    return float((positives.mean() - negatives.mean()) / math.sqrt(var))


def _ecdf_at(values: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Empirical CDF of ``values`` evaluated at ``points``."""
    return np.searchsorted(np.sort(values), points, side="right") / len(values)


def ks_statistic(positives: np.ndarray, negatives: np.ndarray) -> float:
    """Largest gap between the two empirical CDFs.

    Equals Youden's J -- the best (TPR - FPR) any single threshold achieves.
    1.0 when the distributions are disjoint, 0.0 when identical.
    """
    if len(positives) == 0 or len(negatives) == 0:
        return float("nan")
    points = np.unique(np.concatenate([positives, negatives]))
    return float(np.max(np.abs(_ecdf_at(positives, points) - _ecdf_at(negatives, points))))


def overlap_coefficient(positives: np.ndarray, negatives: np.ndarray) -> float:
    """How much the two distributions overlap: 0.0 disjoint, 1.0 identical.

    This is the headline number for Gate A. It answers "how often will the
    scorer be unable to tell the difference?" in a way a reader without a
    statistics background can act on, and it is defined as ``1 - KS``, so it
    has a direct operational meaning: the share of separation that no choice of
    threshold can recover.

    Deliberately NOT a fixed-bin histogram overlap. That was the first
    implementation and it was wrong in a way worth recording, because it is the
    exact failure this module warns about elsewhere. Similarities cluster very
    tightly near 1.0 while the different-face tail runs down towards -1.0, so
    fixed-width bins over the combined range are far wider than the gap between
    the distributions: perfectly separated data landed in a single shared bin
    and scored 0.5 overlap. The statistic was measuring bin resolution, not
    overlap, and it reported POOR on a clean separation -- which at Gate A
    would have killed a viable approach on an artefact of binning.
    """
    ks = ks_statistic(positives, negatives)
    return float("nan") if np.isnan(ks) else 1.0 - ks


def _rates_at(
    threshold: float, positives: np.ndarray, negatives: np.ndarray
) -> tuple[float, float]:
    """(false positive rate, false negative rate) for ``score >= threshold``."""
    fpr = float((negatives >= threshold).mean()) if len(negatives) else float("nan")
    fnr = float((positives < threshold).mean()) if len(positives) else float("nan")
    return fpr, fnr


def equal_error_rate(positives: np.ndarray, negatives: np.ndarray) -> tuple[float, float]:
    """(threshold, EER) at the point where FPR and FNR cross."""
    candidates = np.unique(np.concatenate([positives, negatives]))
    best_t, best_gap, best_eer = float("nan"), float("inf"), float("nan")
    for t in candidates:
        fpr, fnr = _rates_at(float(t), positives, negatives)
        gap = abs(fpr - fnr)
        if gap < best_gap:
            best_t, best_gap, best_eer = float(t), gap, (fpr + fnr) / 2.0
    return best_t, best_eer


def threshold_at_fpr(
    positives: np.ndarray, negatives: np.ndarray, target_fpr: float
) -> tuple[float, float, float]:
    """Lowest threshold whose FPR is within target. Returns (threshold, fpr, tpr).

    Low threshold is preferred among those that meet the target, because every
    point of threshold costs recall -- and recall here means usable takes that
    get thrown away and regenerated at real cost.
    """
    candidates = np.unique(np.concatenate([positives, negatives]))
    chosen = float(candidates.max())
    for t in candidates:
        fpr, _ = _rates_at(float(t), positives, negatives)
        if fpr <= target_fpr:
            chosen = float(t)
            break
    fpr, fnr = _rates_at(chosen, positives, negatives)
    return chosen, fpr, 1.0 - fnr


def _describe(values: np.ndarray) -> dict[str, float]:
    if len(values) == 0:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": float(values.mean()),
        "sd": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
        "min": float(values.min()),
        "p05": float(np.percentile(values, 5)),
        "median": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "max": float(values.max()),
    }


@dataclass
class Calibration:
    """The instrument's calibration record. Stamped with the embedder identity."""

    embedder_key: str
    embedder_is_stub: bool
    calibrated_on: dt.date
    threshold: float
    target_fpr: float
    fpr_at_threshold: float
    tpr_at_threshold: float
    eer_threshold: float
    eer: float
    auc: float
    d_prime: float
    overlap: float
    verdict: str
    positives: dict[str, float] = field(default_factory=dict)
    negatives: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["calibrated_on"] = self.calibrated_on.isoformat()
        return out

    @property
    def trustworthy(self) -> bool:
        return self.verdict in {"EXCELLENT", "ADEQUATE"}


def verdict_for(auc: float, overlap: float) -> str:
    for name, min_auc, max_overlap in VERDICT_BANDS:
        if auc >= min_auc and overlap <= max_overlap:
            return name
    return "POOR"


def calibrate(
    positives: list[float] | np.ndarray,
    negatives: list[float] | np.ndarray,
    info: EmbedderInfo,
    target_fpr: float = 0.01,
    today: dt.date | None = None,
) -> Calibration:
    pos = np.asarray(positives, dtype=np.float64)
    neg = np.asarray(negatives, dtype=np.float64)
    if len(pos) == 0 or len(neg) == 0:
        raise ValueError(
            f"Calibration needs both same-face and different-face similarities. "
            f"Got n_positive={len(pos)}, n_negative={len(neg)}."
        )

    auc = roc_auc(pos, neg)
    overlap = overlap_coefficient(pos, neg)
    d_prime_value = d_prime(pos, neg)
    threshold, fpr, tpr = threshold_at_fpr(pos, neg, target_fpr)
    eer_t, eer = equal_error_rate(pos, neg)
    verdict = verdict_for(auc, overlap)

    warnings: list[str] = []
    if len(pos) < MIN_SAMPLES_FOR_CONFIDENCE or len(neg) < MIN_SAMPLES_FOR_CONFIDENCE:
        warnings.append(
            f"Small sample: {len(pos)} same-face and {len(neg)} different-face pairs "
            f"(guide: {MIN_SAMPLES_FOR_CONFIDENCE}+ each). Treat these statistics as "
            f"indicative only."
        )
    if verdict == "POOR":
        warnings.append(
            "The same-face and different-face distributions overlap materially. Any "
            "threshold drawn here will both pass drifted takes and reject good ones. "
            "This is a Gate A finding in its own right: automated scoring would be "
            "advisory rather than gating, and BUILD_PLAN task 3.4's auto-reject design "
            "needs rework before it is built on top of this."
        )
    elif verdict == "MARGINAL":
        warnings.append(
            "Separation is weak. Check the worst-frame contact sheet before trusting "
            "the threshold: if the scorer passes clips your eye rejects, the scorer is "
            "the finding, not the clips."
        )
    if info.is_stub:
        warnings.append(
            "Calibrated against the STUB embedder, which is pixel statistics and not a "
            "face recognition model. These numbers describe the harness, not the "
            "identity approach, and must not reach a Gate A report."
        )
    if auc >= 0.99 and not math.isnan(d_prime_value) and d_prime_value < 2.0:
        warnings.append(
            f"d' ({d_prime_value:.2f}) and AUC ({auc:.4f}) disagree. d' assumes roughly "
            f"normal distributions; these are not, so read AUC and overlap and treat d' "
            f"as indicative only."
        )
    if fpr > target_fpr:
        warnings.append(
            f"No threshold reached the target false-positive rate of {target_fpr:.3f}; "
            f"the best available is {fpr:.3f}."
        )

    return Calibration(
        embedder_key=info.key(),
        embedder_is_stub=info.is_stub,
        calibrated_on=today or dt.date.today(),
        threshold=threshold,
        target_fpr=target_fpr,
        fpr_at_threshold=fpr,
        tpr_at_threshold=tpr,
        eer_threshold=eer_t,
        eer=eer,
        auc=auc,
        d_prime=d_prime_value,
        overlap=overlap,
        verdict=verdict,
        positives=_describe(pos),
        negatives=_describe(neg),
        warnings=warnings,
    )
