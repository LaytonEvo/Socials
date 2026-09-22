# ADR 0001 — Spike-first build order

- **Status:** **Accepted 2026-09-22** by the owner.
- **Date:** 2026-09-22
- **Deciders:** Layton (owner), supervising engineer
- **Supersedes:** `BUILD_PLAN.md` Section 10

## Context

`CLAUDE.md` requires an ADR for significant deviation from the plan. This records one: the order of work in `BUILD_PLAN.md` Section 10 is replaced by the sequence in `docs/BUILD_ORDER.md`.

The plan is internally inconsistent about risk. Section 0 identifies identity consistency as *the* hard problem. Phase 1's gate says that if identity does not hold, the project stops and nothing downstream matters. Yet Section 10 instructs that Phase 0 — the full production foundation — is built first, before that question is asked.

Three consequences follow:

1. **Discarded work on a failed gate.** A 16-table schema, migrations, storage wrapper, job queue, adapter protocols, fakes and a cost ledger are built before the experiment that can invalidate all of them.
2. **Foundations built without evidence.** The cost guard needs a real discard rate. The orchestrator's retry cap needs real regeneration statistics. The auto-reject logic in task 3.4 needs a calibrated threshold *and* evidence that the threshold agrees with human judgement. All of these are outputs of Phase 1, and all of them are inputs to a well-designed Phase 0.
3. **A human decision made ahead of its evidence.** D1 (persona name, look, backstory, voice) is scheduled to unblock the Phase 1 master set. Phase 2 then determines which content formats the models can actually render, with the plan's own expectation being that full swing and ball flight are blocked. The persona concept is therefore chosen before the constraint that shapes it is known.

Phase 1's and Phase 2's questions are both about *provider behaviour*, not about our software. Neither requires a database, a queue, or an adapter abstraction to answer.

## Decision

Insert a new stage, **Spike 0**, ahead of Phase 0.

Spike 0 answers both experimental questions — identity retention through animation, and golf format viability — using scripts, local files and a spreadsheet. No Postgres, no Redis, no FastAPI, no migrations, no adapter protocols. It runs against a **throwaway look**, not the real persona, so it does not block on D1 and does not burn the persona's look on an experiment.

Spike 0 ends at **Gate A**, a human go/no-go. Only after Gate A passes is Phase 0 built, sized by the evidence Spike 0 produced.

Phase 1 and Phase 2 shrink accordingly: the experimental tasks (1.2, 1.3, 1.6, throwaway 1.4/1.5, 2.1, manual 2.2) move into Spike 0; the productionised versions and the review-UI-dependent rating work (2.3) remain.

Phase numbering in `BUILD_PLAN.md` is preserved. Nothing is renumbered.

## Consequences

**Positive**

- A failed approach costs under a week and a budget in the low hundreds, rather than three weeks and a full production system.
- Phase 0 is designed against measured discard rates, real costs per usable second, a validated threshold, and known operator time.
- D1 is made with format constraints in hand (see ADR 0003).
- The lip-sync drift gap (amendment A5) is sized cheaply, before the pipeline is architected around a score that does not describe the final render.
- The scorer itself is validated against human judgement before Phase 3's auto-reject logic is built on top of it. If the scorer disagrees with the eye, that is a finding that changes the design.

**Negative**

- Spike 0 code is throwaway by design. Some effort is spent twice. This is accepted: the second write is against the adapter contract and the real schema, which is a different piece of software, not a port.
- The throwaway look means the identity result is indicative, not final. Identity retention is partly face-dependent, so the threshold and pass rates must be re-measured against the real persona look in Phase 1. Budgeted, not skipped.
- Total elapsed time to a working pipeline is slightly longer *if* everything succeeds. Materially shorter in every other case.

**Neutral**

- Architecture, data model, adapter contract and compliance requirements are untouched. This ADR changes sequencing only.

## Alternatives considered

**Follow Section 10 as written.** Rejected: it builds the foundation before the question that decides whether the foundation is needed, and deprives that foundation of its design inputs.

**Spike inside Phase 0, reusing the real schema and adapters.** Rejected: the abstractions are precisely what the spike is meant to inform. Building them first to run the experiment through them defeats the purpose and is slower.

**Wait for D1 before spiking.** Rejected: the spike measures whether the technique works, which a throwaway look answers. Waiting serialises a human decision in front of a technical one for no gain, and risks burning the real look on a failed experiment.

## Log

**2026-09-22** — Accepted by Layton. Spike 0 is the current stage; Phase 0 is not
started and must not be, until Gate A passes. `BUILD_PLAN.md` Section 10 is
superseded by `docs/BUILD_ORDER.md` and carries a banner saying so.
