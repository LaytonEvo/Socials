# ADR 0003 — Content format constraints and their effect on the persona concept

- **Status:** **Evidence in (2026-09-28). The premise was wrong; the D1 question survives and is the owner's.** Informs D1.
- **Superseded in part:** the sections below dated 2026-09-22 assume swing and ball flight are blocked. They are not. Read the 2026-09-28 section first.
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


---

# 2026-09-28 — the evidence, and what it overturns

Task S0.7 ran. **The constraint this ADR was written around does not exist.**

## The premise was wrong, and so was mine

`BUILD_PLAN` expected *"full swing and ball flight blocked"*. This ADR agreed —
*"that expectation is very likely correct"* — and reasoned from there to a
golf-*personality* concept. Both of us treated the limit as a property of **video
generation**.

It is a property of **the provider.**

`veo3.1`, the only model the spike tested until 2026-09-25, cannot render
club-ball contact. Its failures were not cosmetic: on the owner's inspection the
club missed the ball and the ball moved anyway, and a putting clip took practice
strokes behind the ball and never addressed it. Causality, not detail.

`minimax/h3-max-turbo`, on the same prompts and the same portrait keyframes,
renders address over a teed ball, backswing, downswing, contact, follow-through
and ball flight. The owner's verdict on six takes: **"Swings are good."**

It costs **$0.0125/s against veo3.1 fast's $0.15/s** — a twelfth.

## Owner-rated evidence, by provider and class

Ratings are the owner's, on clips they watched. Below 4 is a discard.

| | Clips rated | Usable | Rejected |
|---|---|---|---|
| `veo3.1` club-and-ball | 11 | 7 | **4** — physics |
| `veo3.1` face-forward | 6 | **6** | 0 |
| `turbo` club-and-ball | 11 | **10** | 1 — identity, not golf |
| `turbo` face-forward | 2 | 0 | 2 — **see caveat** |

**Caveat on that last row, which would otherwise read backwards.** Those two
clips were the pinned-audio experiment and were rejected for *"lip sync is off"* —
an audio defect from a test of `target_audio_url`, not a judgement on turbo's
face-forward video. **Turbo's face-forward output is effectively unrated by the
owner.** The automated gate scores it well (8 pass, 3 indeterminate, 1 fail
across 12 clips, mean face presence 0.925), but the gate is not the instrument
that decides this.

## The decision this ADR asked for

> **If swing and ball flight are confirmed blocked, does the concept still work?**

**They are not blocked, so the question does not arise in that form.** The D1
decision it was protecting is still live and still the owner's, but it is now a
free choice rather than one forced by the stack:

- **Golf personality** — talking head, reaction, equipment, apparel, course,
  travel. 6 of 6 usable on `veo3.1`, and the reliable half of the system
  throughout the spike.
- **Golf player** — swing, contact, ball flight, shot-making. 10 of 11 usable on
  `turbo`, on nine takes across three formats.
- **Hybrid** (D2's contracted, disclosed performer) — unchanged, and no longer
  the only route to swing content.

**This ADR does not choose.** That is a Section 1 decision and not the build
agent's to make. What it can now say is that the choice is not constrained by
what can be rendered.

## The constraint that replaces it

The old constraint was *"club and ball physics cannot be rendered"*. The measured
one is narrower and different in kind:

1. **Identity, not physics, is the binding limit on club-and-ball shots.** On
   turbo, 4 of 14 such clips fall below the 0.9609 threshold at best
   configuration; on `veo3.1` it was 3 of 13, but `veo3.1` could not render the
   shot at all. A golf shot is composed to show a club striking a ball, which is
   a composition that does not show a face.
2. **The identity gate must route, not reject.** Against the owner's verdicts it
   has 1 true positive, 2 false positives and 0 false negatives: a gate FAIL is
   right one time in three, while it has never missed a clip the owner rejected.
   Used as an auto-reject it destroys usable footage at twice the rate it
   prevents a bad publish. This is D-A's answer and it is now measured rather
   than argued.
3. **Club geometry is still wrong and still unmeasured.** *"The driver in the
   last video doesn't look real"* — `club_distortion`, one of this ADR's original
   predicted failure modes, surviving the change of model. Nothing in the harness
   sees it.
4. **Audio must be governed on every clip.** Turbo generates a soundtrack
   unconditionally, in an unidentified language, with no off switch.
   `target_audio_url` replaces it, verified bit-exact. It does **not** condition
   the video, so it does not remove the lip-sync stage (ADR 0005 answered: no).

## What this does not license

**The no-real-swing-footage rule in `BUILD_PLAN` Section 2 stands, and matters
more now, not less.** It was written to remove the temptation to cut real footage
in when the persona could not swing. She can swing, so that particular temptation
is gone — but motion transfer reaches the same place by another route, and a real
person's swing presented as hers is the thing the rule exists to prevent however
the pixels arrive. See `motion-transfer-options-2026-09-25.md`.

The financial-products exclusion (D4) is unaffected.

## Recommended next step for task 2.5

`allowed_formats` / `blocked_formats` **should not be written yet.** Nine takes
across three formats is not a yield rate, turbo's face-forward output has no
owner rating at all, and the identity numbers are the weakest part of the case.
What task 2.5 needs is a second owner-rated pass over the full 13 formats on
turbo — the clips exist, 26 of them, and cost $1.625 — after which the catalogue
can be written from ratings rather than from automated verdicts.
