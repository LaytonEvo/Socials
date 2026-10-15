# ADR 0018 — A keyframe is screened for what it looks like, not only for who is in it

- **Status**: accepted, 2026-10-15
- **Extends**: ADR 0011, which screens a keyframe and screens it for identity alone
- **Relates to**: ADR 0015 (the keyframe is an edited photograph), ADR 0012

## Context

`spike/runs/shot1-final/keyframe.png` — the still the owner's one approved video was built
from — has a hard composite boundary across its lower third, where `nano-banana-2/edit`
pasted a wedge-and-ball foreground into a master still. The grass texture changes abruptly
along a straight line at row 961, with a vertical edge running down past her hip.

Every frame of everything built on it carries that seam: shot 1, the two-shot piece, and
the b-roll keyframe that was itself an edit of it (13.74, the worst score measured).

The old chain partly smoothed it. The audio-driven avatar model reproduces a still more
faithfully, so running the same keyframe through it on 2026-10-15 put the seam in plain
view — which is how it was finally noticed, three weeks and one approval late.

**It was screened and it passed.** ADR 0011 screens a keyframe for identity before the
chain underneath is paid for, and a pasted rectangle scores a perfectly good identity
number. The screen measured one thing and the keyframe failed at another.

That is the third instance of the same shape in two weeks: swing length unmeasured while
identity was measured (ADR 0016), golf scene content unmeasured while swing length was,
and now this.

## Decision

**Screen a keyframe for composite seams as well as for identity, and refuse on either.**

### The metric is coverage times isolation

For each row, the share of columns where the row-to-row difference exceeds the image's own
99th-percentile gradient — *coverage*, how much of the width jumps at once — divided by the
same quantity in a neighbouring ring, skipping the two rows either side — *isolation*,
whether it jumps at exactly one row. Both axes; the worst wins.

**Coverage alone was tried first and discarded.** A tree line across a real photograph of
her covers 17.8% of the width at a single row, against the bad keyframe's 19.7%. The two
do not separate. What separates them is that natural structure spreads over several rows
while a paste is one pixel wide by construction: isolation 14 against 201.

### Measured, 2026-10-15

| population | n | max |
|---|---|---|
| her master, outfit, lighting and body stills | 96 | **4.22** |
| keyframes with no visible seam | 5 | 1.76 |
| `shot1-final/keyframe.png` | 1 | **9.83** |
| `broll/address_strike_keyframe.png` | 1 | **13.74** |

`SEAM_LIMIT = 7.0` sits in the empty gap: 1.7× above anything the 101 clean images do, and
1.4× below the better of the two composites.

**The negative class is well sampled and the positive class is two images.** The bar is
justified by what clean images do *not* do rather than by a model of what seams do, and it
says so in the module. Revisit it when there are more examples.

**Amended the same day.** The clean population above is almost all portraits of her. The
b-roll keyframe regenerated on 2026-10-15 — a ball on a green, mown edge dead straight
across a uniform foreground — scored **6.63** with no seam in it, because a flat horizon
over featureless turf is both wide coverage and isolated. On landscape content the
headroom is a few percent, not the 66% the portrait numbers imply. Recorded rather than
acted on: one example is not grounds to move a bar, and it is the first thing to revisit.

### Blocking, not review

A keyframe is $0.08 and a false refusal costs one more draw. A seam that gets through costs
every frame of everything built on it, and nothing downstream can see it — the identity
scorer certainly cannot. The asymmetry is not close.

`best_still` will not return a seamed candidate even when it scores highest on identity,
and a still whose seam cannot be scanned does not pass, which is ADR 0012 in a third place.

## Consequences

- Of seven keyframes on disk, two are seamed and both are in the shot-1 lineage. The other
  five are clean, so this is a bad edit rather than a broken path and **ADR 0015 stands**.
- Shot 1 has to be rebuilt from a screened keyframe. The approved video was approved on a
  damaged still.
- It measures axis-aligned seams. A pasted region with a soft or irregular boundary, a
  warped composite, or a blend would not be caught. It is one named defect, not a
  general-purpose "does this look wrong" check, and the gate should not be read as one.
