# ADR 0009 — No golf knowledge base. A persona memory instead.

- **Status:** Proposed 2026-09-28. Shapes `BUILD_PLAN.md` task 3.1; nothing built yet.
- **Date:** 2026-09-28
- **Deciders:** Layton (owner)
- **Relates to:** `BUILD_PLAN.md` tasks 3.1, 3.6; `docs/spec/persona-spec-v1.md` §1, §3, §4; `config/persona.yaml`

## Context

The question was whether the persona needs golf knowledge fed into it — a
retrieval layer, a corpus, a knowledge base.

**The video model needs none.** `h3-max` renders pictures and never knows what
a handicap is. Her words come from a different stage: task 3.1's shot-list
generator, brief in, schema-validated JSON shot list out, via the Claude API,
with `dialogue` on each shot. That is the only place golf knowledge could
matter.

## Decision

**Build no golf knowledge base. Build a persona memory.**

### 1. General golf knowledge needs no retrieval

Rules, etiquette, equipment, course architecture, slow play, club politics, the
terminology she would tease — the model writing her dialogue already has all of
it. A retrieval layer would add cost, latency and a corpus to maintain in order
to fetch what the model can already say.

### 2. More knowledge would make the persona worse, not better

This is the part that is easy to get backwards. Spec v1 §1: **"She is not a
coach, not a pro"**, 14 handicap, honest about it. §4 is funny about *"men
explaining her own swing to her"*.

A retrieval-backed generator produces an **authority**. That is the register the
spec spends an entire section avoiding, and the differentiator in §4 is tone,
not facts. Golf content is already, in the spec's own words, *"mostly men being
earnest at each other"*; a knowledge pipeline is a machine for producing more of
it.

A 14 handicap should occasionally be slightly wrong about something. That is
characterisation, and a knowledge base actively removes it.

### 3. What actually needs feeding is continuity, and the store already exists

The thing that breaks a recurring character is not missing world knowledge. It
is **contradicting herself**: a handicap that moves the wrong way, a course she
has already "played", a joke told twice, a claim she made in week two and
forgets in week nine.

`BUILD_PLAN`'s schema already records every word she has spoken — `shot.dialogue`
across every `content_piece` — and every persona decision in `decision_log`.

**The gap is not storage. Nothing reads it back into the generator.** That is a
real hole in task 3.1 as specified, and naming it is most of the value of this
ADR.

### 4. Current events are out of scope — decided by the owner, 2026-09-28

*"No current events to consider."*

Tournament results and equipment launches sit past any model's training cutoff,
so they would have needed the **`web_search` server tool at request time**
(`web_search_20260209` on Claude Opus 5, scoped with `allowed_domains`) — never
a corpus, but still a live dependency.

They are out. Nothing in spec §3's content strands needs them: the
England/Florida contrast, trips home, the improvement arc and Dad's bafflement
are all evergreen, which is why the question was worth asking rather than
assuming.

**This is a larger simplification than it looks.** With current events out and
no retrieval layer, **task 3.1 has no external data dependency at all.** Its
inputs are the brief, `persona.yaml`, the locked fragments and her own prior
`shot.dialogue` — every one of them local and under version control.

Three things follow:

- The shot-list generator can be **tested offline against fakes**, which is the
  pattern the whole spike harness already uses.
- There is **no network failure mode** at generation time beyond the Claude API
  call itself, and no third-party rate limit, outage or scraped source to
  degrade against.
- **Nothing dates.** A brief written today produces the same shot list next
  month, so the persona's voice does not drift with whatever the web returned
  that morning.

Evergreen content is also the right shape for a five-a-week Shorts calendar,
where a piece may be generated well before it is published.

### 5. Product data only if she reviews equipment

And §7 forbids claiming a product she has not used on screen, which caps how
much specification detail is even usable.

## Shape for task 3.1

Not an implementation, and not to be built before Phase 3:

**System prompt** carries the locked fragments plus `persona.yaml` — stable
across every request, and therefore the cacheable prefix. Prompt caching is a
**prefix match** in render order `tools` → `system` → `messages`, so stable
content goes first and anything volatile goes after the last breakpoint.

**Two traps worth recording now:**

- **The minimum cacheable prefix is 512–4096 tokens depending on model.** The
  locked fragments plus persona config may fall under it, in which case caching
  **silently does not happen** — no error, just full price. Verify with
  `usage.cache_read_input_tokens`; if it is zero across repeated requests, the
  prefix is too short or something is invalidating it.
- **Anything varying in the prefix invalidates everything after it.** A
  timestamp, a per-request id, an unsorted dict. The persona block must be
  byte-stable between calls.

**Messages** then carry the brief, and recent `shot.dialogue` for continuity.

**Output** is schema-validated per task 3.1 — `output_config.format`, not the
deprecated `output_format` parameter.

## Consequences

**If accepted:** no corpus to build, license, host or keep current. Task 3.1
gains one requirement it did not have — read `shot.dialogue` back — and that is
cheaper than any retrieval layer. The persona stays a 14 handicap rather than
drifting into a golf encyclopedia.

**If rejected:** a corpus needs sourcing, licensing and maintaining, and the
tone risk in §2 above needs managing in the prompt instead — which is the harder
of the two problems, because it is invisible until the content is already dull.

**Either way:** the continuity gap is real and stands independently of the
knowledge decision. Even a retrieval-backed generator contradicts itself about
her own history unless something feeds her own words back.

**One thing to watch, given §4.** Evergreen content ages differently from dated
content: it does not go stale, but it also cannot reference anything. If the
persona is ever asked — by a comment, a trend, a moment in the sport — to have
an opinion about something that happened, the pipeline has no way to give her
one, and that is a content-strategy limit rather than a bug.

## Open

**Nothing.** The only item needing an owner decision — current events — was
answered on 2026-09-28 and is recorded in §4. The ADR is ready to move from
Proposed to Accepted on the owner's word.

---

## Amendment, 2026-09-30 — the stage this ADR did not examine

**The decision stands. Its scope was too narrow, and the gap showed up in rendered
frames rather than in dialogue.**

### What happened

The first assembled golf piece put her **carrying a golf bag across a putting green**.
The bag also carried invented brand lettering, and an earlier take rendered a real Nike
swoosh on her visor unprompted. The owner's reaction was that the model needed "filling
with golf knowledge".

### Why this ADR did not catch it

§ "Context" dismisses the image stage in one line:

> **The video model needs none.** `h3-max` renders pictures and never knows what a
> handicap is.

That is true and beside the point. The image model does not need to know what a handicap
is. It needs to know that **a bag does not go on the putting surface** — and it does not,
because nothing ever told it.

This ADR asked "does the persona need golf facts to SAY?" and answered correctly. It
never asked "does the generator need golf facts to DRAW?", which is a different question
with a different answer.

### The distinction worth keeping

| | Knowledge of | Where it lives | This ADR |
|---|---|---|---|
| **Dialogue** | rules, etiquette, equipment, terminology | already in the model writing her words | correct: no corpus |
| **Picture** | what a golf photograph may contain | nowhere | **missed** |

The second is not a corpus either. It is a short, fixed list of things a golfer would
notice, and it belongs in the prompt — now `app/pipeline/golf.py`, applied to every
image and motion prompt, with a check that refuses a prompt describing an implausible
frame rather than paying to render one.

### A correction to how this ADR was applied

Separately from the gap above: I read this ADR as *"keep golf out of her mouth"* and
wrote her three lines of nothing — "Long way to the green from here" — which the owner
correctly called a video with no point.

That is not what it says. §1 states the model writing her dialogue **already has** the
rules, the etiquette and the equipment. What this ADR constrains is **register, not
subject**: spec §1 has her a 14 handicap, *"not a coach, not a pro"*, and §4 is pointed
about men explaining her own swing to her. She should talk about golf constantly — from
her own round, occasionally wrong, never instructing.

An empty line is not a safe reading of this ADR. It is a failure to read it.

### Unchanged

No corpus, no retrieval layer, no current events. The continuity gap in §3 — nothing
reads `shot.dialogue` back into the generator — is still real and still unbuilt.
