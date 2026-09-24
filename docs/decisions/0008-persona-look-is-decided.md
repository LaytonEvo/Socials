# ADR 0008 — The master set is the persona, not a throwaway look

**Status:** accepted by the owner, 2026-09-24
**Decides:** the *look* half of D1 (`BUILD_PLAN.md` Section 1). Name, backstory
and voice remain open.

## Context

`docs/BUILD_ORDER.md` §3.1 has Spike 0 running on a deliberately throwaway
look, so that the real persona is not burned on an experiment before the
approach is proven. It carries a consequence:

> identity retention is partly face-dependent ... So Gate A validates the
> *approach*; the calibrated threshold and the pass rates must be re-measured
> against the real persona look in Phase 1 before they are trusted. Budget for
> that re-run.

Over 2026-09-23/24 the master set grew to 105 usable stills with 92
condition-matched controls, and the whole identity gate was calibrated against
it. Asked whether that look was the throwaway or the persona, the owner
answered: **"This is her."**

## Decision

The `spike/data/master_v2` set is the persona's canonical reference set.
Spike 0 is not running on a throwaway.

## Consequences

**The Phase 1 re-measurement is released.** The threshold (0.9609), the master
centroid, the coverage floor and the run-below allowance were all measured
against this face, so they carry forward rather than being redone. The budget
§3.1 set aside for that re-run is not needed.

**Gate A now validates more than the plan expected.** It was scoped to
validate the approach and leave the face open. It validates both.

**Her look is now a hard dependency, in the same way the embedder is.**
BUILD_ORDER amendment A3 makes changing the embedding model invalidate every
stored vector and the threshold with it. Changing her face does exactly the
same: the master set, the centroid, the calibration and every measured pass
rate are defined against these 105 stills. This is not a setting to revisit
casually, and the moment to change it — if it were ever going to change — has
now passed by decision.

**One option is closed by that.** On 2026-09-24 the matched-control
calibration showed her own distribution and a set of generated lookalikes
touching at the extreme tails, and giving her a distinguishing feature was
raised as the only fix that would genuinely buy separation. It was withdrawn
on the evidence — the crossing is two images out of 197 — and it is now closed
by decision as well. The residual is documented in
`identity-threshold-correction-2026-09-24.md`: at the operating point, one of
her own stills in a hundred reads low and one stranger in ninety reads high.

**The reference set is source, not evidence.** `spike/data/` is tracked, so
the 105 stills are version-controlled rather than living only in a run
directory. That was already true and is now load-bearing.

**Still open in D1:** name, backstory and voice. Voice is the live one --
everything generated so far is silent, and whether Veo's native audio can
carry her or a separate voice is needed is untested.
