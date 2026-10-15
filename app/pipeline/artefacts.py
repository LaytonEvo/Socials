"""Finding the seam where an edit pasted a rectangle in.

`spike/runs/shot1-final/keyframe.png` — the still our one approved video was built from
— has a hard composite boundary running across its lower third, where `nano-banana-2/edit`
dropped a wedge-and-ball foreground into a master still. Every frame of every clip built
from it inherits the seam. Nobody caught it because ADR 0011 screens a keyframe for
IDENTITY and nothing else, and a pasted rectangle scores a perfectly good identity number.

**The metric is coverage times isolation.** For each row, take the share of columns where
the row-to-row difference exceeds the image's own 99th-percentile gradient — that is the
*coverage*, how much of the width jumps at once. Then divide by the same quantity in a
ring of neighbouring rows, skipping the two either side — that is the *isolation*, whether
the jump happens at exactly one row.

Both halves are needed, and coverage alone was tried first and discarded. A tree line
running across a real photograph of her scores 0.178 on coverage, above the 0.197 of the
known-bad keyframe's seam by only a whisker — because a tree line really does change most
of the width at once. What it does not do is change it at a single row: natural structure
is spread over several rows and its isolation is low, while a pasted edge is one pixel
wide by construction and its isolation is in the hundreds.

**Measured 2026-10-15** over 101 images — her 96 master, outfit, lighting and body stills
plus the 5 keyframes with no visible seam:

    clean population      max 4.22   p99 3.76   p95 2.40
    known composites      9.83 (shot1-final/keyframe)  13.74 (broll/address_strike)

**Run this BEFORE the overlay pass, never after.** The disclosure band and the caption
box are hard-edged rectangles drawn onto the picture, and this cannot tell our own overlay
from a model's paste: measured on the 2026-10-15 rebuild, the lip-synced take scores 0.91
and the same frame after `apply_disclosure` scores 18.82 at the row where the disclosure
band begins. That is the detector working, on the wrong input. It belongs on keyframes and
on raw takes.

`SEAM_LIMIT` sits in the empty gap between those.

**The margin is narrower on landscape frames than that table suggests.** The clean
population above is almost all portraits of her. The b-roll keyframe regenerated on
2026-10-15 — a ball on a green with the mown edge running dead straight across a uniform
foreground — scored **6.63** and has no seam in it at all: a flat horizon over featureless
turf is both wide coverage and isolated. So on landscape content the headroom is a few
percent rather than the 66% the portrait population implies. A near miss is recorded here
rather than used to move the bar on one example, and it is the first thing to revisit.

**The negative class is well sampled and
the positive class is two images**, so the bar is justified by what clean images do NOT do
rather than by a model of what seams DO. Revisit it when there are more examples.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import numpy as np
from PIL import Image

Axis = Literal["horizontal", "vertical"]

#: Above this, no clean image in the 101 measured comes close and both known composites
#: are well past it. Blocking for a keyframe: a false refusal costs one more draw at
#: $0.08, and a seam that gets through costs every frame of everything built on it.
SEAM_LIMIT: Final = 7.0

#: The gradient percentile that counts as "a jump". Not tuned — it is the same 99th
#: percentile the coverage figures above were measured at.
JUMP_PERCENTILE: Final = 99.0

#: Ignore the outermost share of rows and columns. A discontinuity in the very last row
#: is a border or a letterbox, not a composite: one master still scored 0.609 on raw
#: coverage at its second-to-last row and is perfectly clean.
EDGE_MARGIN: Final = 0.03

#: The neighbour ring, in rows. The two rows either side are skipped because a real
#: paste often bleeds a pixel; FAR bounds how much natural structure counts as context.
RING_NEAR: Final = 2
RING_FAR: Final = 6

#: Isolation is a ratio with a small denominator and can run to thousands on a perfectly
#: uniform neighbourhood. Capped so that one empty ring cannot dominate the score.
MAX_ISOLATION: Final = 50.0


@dataclass(frozen=True)
class SeamReading:
    """The strongest axis-aligned discontinuity in an image."""

    axis: Axis
    #: Row index for a horizontal seam, column index for a vertical one.
    index: int
    #: Share of the perpendicular span that jumps at this line.
    coverage: float
    #: How much more it jumps here than in the neighbouring lines.
    isolation: float
    score: float

    @property
    def seamed(self) -> bool:
        return self.score > SEAM_LIMIT

    def explain(self) -> str:
        where = "row" if self.axis == "horizontal" else "column"
        return (
            f"a {self.axis} discontinuity at {where} {self.index}: "
            f"{self.coverage:.1%} of the line jumps at once, {self.isolation:.0f} times "
            f"more than the rows around it (score {self.score:.1f}, limit {SEAM_LIMIT:g})"
        )


def _scan_axis(grey: np.ndarray, axis: int) -> tuple[float, int, float, float]:
    """Worst (score, index, coverage, isolation) along one axis."""
    difference = np.abs(np.diff(grey, axis=axis))
    jumps = difference > np.percentile(difference, JUMP_PERCENTILE)
    coverage = jumps.mean(axis=1 - axis)

    count = len(coverage)
    low = int(count * EDGE_MARGIN)
    best = (0.0, 0, 0.0, 0.0)
    for index in range(low, count - low):
        ring = np.r_[
            coverage[max(0, index - RING_FAR) : max(0, index - RING_NEAR)],
            coverage[index + RING_NEAR + 1 : index + RING_FAR + 1],
        ]
        if ring.size == 0:
            continue
        isolation = float(coverage[index]) / max(float(ring.mean()), 1e-4)
        score = float(coverage[index]) * min(isolation, MAX_ISOLATION)
        if score > best[0]:
            best = (score, index, float(coverage[index]), isolation)
    return best


def scan(image: Path | np.ndarray) -> SeamReading:
    """The strongest seam in an image, whichever axis it runs along.

    Takes a path or an already-loaded greyscale array, so the tests can build an image
    with a known paste in it rather than shipping a fixture.
    """
    if isinstance(image, Path):
        grey = np.asarray(Image.open(image).convert("L"), dtype=np.float32)
    else:
        grey = np.asarray(image, dtype=np.float32)
    if grey.ndim != 2:
        raise ValueError(f"expected a 2-D greyscale image, got shape {grey.shape}")

    horizontal = _scan_axis(grey, 0)
    vertical = _scan_axis(grey, 1)
    axis: Axis = "horizontal" if horizontal[0] >= vertical[0] else "vertical"
    score, index, coverage, isolation = horizontal if axis == "horizontal" else vertical
    return SeamReading(axis=axis, index=index, coverage=coverage, isolation=isolation, score=score)
