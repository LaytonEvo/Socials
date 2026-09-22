# ADR 0003 — Content format constraints and their effect on the persona concept

- **Status:** **Open — pending Spike 0 evidence (task S0.7).** Informs D1.
- **Date:** 2026-09-22
- **Deciders:** Layton (owner)
- **Relates to:** `BUILD_PLAN.md` Section 1 (D1, D4), Phase 2, task 2.5

## Context

`BUILD_PLAN.md` states its own expectation for the Phase 2 gate:

> **Expected result:** full swing and ball flight blocked; talking head, course, equipment, apparel, lifestyle, reaction allowed.

That expectation is very likely correct. Club geometry, grip and finger articulation, club-ball contact physics, and ball flight are exactly where current video models break, and they break in ways that are immediately obvious to anyone who plays golf — which is the audience.

The ordering problem: **D1 (persona name, look, backstory, voice) is scheduled to unblock the Phase 1 master set, while the evidence that constrains D1 arrives at the Phase 2 gate afterwards.** The concept would be chosen before it is known what the system can render.

This matters more than a normal sequencing wrinkle, because the constraint is severe. If swing and ball flight are blocked, the persona cannot demonstrate golf. Not instruction, not shot-making, not "here's how to fix your slice", not on-course play. What remains is:

- talking head on course or at the clubhouse
- walking, scenery, atmosphere
- equipment and apparel presentation
- lifestyle, travel, reaction and commentary

That is a viable content concept — a golf *personality* rather than a golf *player* — but it is a different proposition from what "golf personality" might imply when the concept is being written, and it should be chosen deliberately rather than discovered at a gate.

There is also a correctness dimension. A persona presented as a golfer who never demonstrably swings a club invites the obvious workaround — cutting real swing footage in. `BUILD_PLAN.md` already forbids this, and rightly:

> **Content rule regardless of result:** never cut real swing footage of an unnamed person into the persona's content in a way that implies she is the one swinging.

Naming the constraint up front removes the pressure to reach for that workaround later, when a content calendar is running and the gap is inconvenient.

## Decision (proposed)

1. Run the golf format battery (`BUILD_PLAN.md` task 2.1) inside **Spike 0** as task S0.7, rather than waiting for Phase 2. It shares the generation harness with the identity matrix, so the marginal cost is prompts and rating time.
2. Treat the resulting format matrix as an **input to D1**, not an output of a later gate. The concept is written knowing what can be rendered.
3. Record the outcome in `decision_log` and `config/content_policy.yaml` as `allowed_formats` / `blocked_formats`, as task 2.5 already specifies. Phase 2 retains the confirmation run on the real persona and the final provider set.

## Open question for the owner

**If swing and ball flight are confirmed blocked, does the concept still work?**

This is a D1-class decision and is explicitly not the build agent's to make. Framing it:

- A golf-adjacent personality — course atmosphere, equipment, apparel, travel, commentary, reaction — is renderable today and is a real content category with a real audience.
- A golf-instruction or shot-making personality is not renderable today and cannot be faked without breaking the plan's own content rule.
- The hybrid path in D2 (a contracted performer for swing footage, disclosed) exists precisely to reopen this, but it changes the operation from a software project into one with contracts, scheduling and a second disclosure surface. It is a different business, not a feature flag.

Deciding "golf-adjacent lifestyle is the concept" is a perfectly good answer. Deciding it *before* the look, voice and backstory are written is the point of this ADR.

## Consequences

**If accepted:** D1 is made with evidence; the format constraint is known in week one rather than week two; Phase 2 shrinks to a confirmation run and the rating-UI work.

**If rejected:** the plan proceeds as written, D1 is made on expectation rather than measurement, and there is a real chance the persona concept is rewritten after the master set and possibly the first LoRA have already been produced against it.

**Either way:** the no-real-swing-footage rule in Phase 2 stands, and the financial-products exclusion (D4) is unaffected.
