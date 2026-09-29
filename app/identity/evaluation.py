"""Evaluating a trained LoRA against held-out stills — task 1.4's acceptance criterion.

The whole method rests on one rule, and it is easy to break without noticing:

**Score against a centroid built from the HOLDOUT ONLY.**

Score against the full reference centroid and you are comparing generated images to
pictures the LoRA was trained on. That measures how well it memorised its training set,
which is always flattering and says nothing about whether it learned her face. The
holdout was excluded from training precisely so it can be an independent reference, and
using it inside the centroid too would throw that away.

`evaluate` therefore takes the split rather than a prepared centroid, and builds the
reference itself. A caller cannot pass the wrong one.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .dataset import TrainingSet
from .embedder import DlibEmbedder, Embedding, FaceOutcome
from .master_set import centroid, read_still


class HoldoutTooSmall(ValueError):
    """Not enough held-out stills to say anything.

    Raised rather than reported, because a mean over two images looks exactly like a
    mean over twenty and nothing downstream would know the difference.
    """


#: Below this the evaluation is not worth running. Not a statistical claim — a floor
#: under which a number would mislead more than it informs.
MIN_HOLDOUT = 5


@dataclass
class Evaluation:
    """How a trained LoRA scored against stills it never saw."""

    threshold: float
    scores: list[float] = field(default_factory=list)
    unusable: list[tuple[str, FaceOutcome]] = field(default_factory=list)
    holdout_size: int = 0

    @property
    def generated(self) -> int:
        return len(self.scores) + len(self.unusable)

    @property
    def passed(self) -> int:
        return sum(1 for score in self.scores if score >= self.threshold)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.generated if self.generated else 0.0

    @property
    def mean(self) -> float | None:
        return statistics.fmean(self.scores) if self.scores else None

    @property
    def minimum(self) -> float | None:
        return min(self.scores) if self.scores else None

    def summary(self) -> str:
        if not self.scores:
            return f"0 of {self.generated} generated images carried a usable face"
        assert self.mean is not None and self.minimum is not None
        return (
            f"{self.passed}/{self.generated} at or above {self.threshold:.4f} "
            f"({self.pass_rate:.0%}) · mean {self.mean:.4f} · min {self.minimum:.4f} "
            f"· against {self.holdout_size} held-out stills"
        )


def holdout_reference(
    split: TrainingSet, embedder: DlibEmbedder
) -> tuple[Embedding, list[tuple[str, FaceOutcome]]]:
    """The centroid of the held-out stills, and whatever could not be read.

    This is the independent reference. Nothing the LoRA trained on contributes to it.
    """
    if len(split.holdout) < MIN_HOLDOUT:
        raise HoldoutTooSmall(
            f"{len(split.holdout)} held-out stills is under the {MIN_HOLDOUT} this will "
            f"report on. A mean over a handful of images reads exactly like a mean over "
            f"many, and nothing downstream can tell them apart."
        )

    embeddings: list[Embedding] = []
    unusable: list[tuple[str, FaceOutcome]] = []
    for still in split.holdout:
        reading = read_still(still.path, embedder)
        if reading.embedding is None:
            unusable.append((still.path.name, reading.outcome))
            continue
        embeddings.append(reading.embedding)

    if len(embeddings) < MIN_HOLDOUT:
        raise HoldoutTooSmall(
            f"only {len(embeddings)} of {len(split.holdout)} held-out stills carried a "
            f"usable face, which is under the {MIN_HOLDOUT} floor."
        )
    return centroid(embeddings), unusable


def evaluate(
    generated: Sequence[Path],
    *,
    split: TrainingSet,
    embedder: DlibEmbedder,
    threshold: float,
) -> Evaluation:
    """Score generated images against the held-out stills.

    Takes the split rather than a centroid so the reference cannot be the wrong one —
    the mistake that makes an evaluation flattering and meaningless.
    """
    from .embedder import cosine

    reference, unusable_holdout = holdout_reference(split, embedder)
    result = Evaluation(
        threshold=threshold, holdout_size=len(split.holdout) - len(unusable_holdout)
    )

    for path in generated:
        reading = read_still(path, embedder)
        if reading.embedding is None:
            result.unusable.append((path.name, reading.outcome))
            continue
        result.scores.append(cosine(reading.embedding, reference))
    return result


def sanity_check(split: TrainingSet, embedder: DlibEmbedder, threshold: float) -> Evaluation:
    """Score the TRAINING stills against the holdout centroid, before any LoRA exists.

    This is the control that makes an evaluation interpretable. Her own training stills
    scored against the holdout give the score a perfect likeness would reach — the
    ceiling set by the scorer, the images and the split rather than by the LoRA. A
    trained LoRA scoring near it is doing well; one scoring near the threshold is not,
    even if it passes.

    Without this a pass rate is a number with nothing to compare it to.
    """
    return evaluate(
        [still.path for still in split.train],
        split=split,
        embedder=embedder,
        threshold=threshold,
    )
