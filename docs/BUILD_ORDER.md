# Revised Build Order

**Supersedes:** `BUILD_PLAN.md` Section 10 (Suggested order of work)
**Amends:** `BUILD_PLAN.md` Sections 4 and 6 (see [Plan amendments](#plan-amendments))
**Leaves unchanged:** Sections 0–3, 5, 7–9. The architecture, adapter contract, compliance requirements and data model are sound. Only the sequencing and a short list of concrete gaps change.
**Rationale:** `docs/decisions/0001-spike-first-build-order.md`
**Status:** **Accepted 2026-09-22.** Spike 0 is the current stage; its harness is built (`scripts/spike/`). Phase 0 has not started and does not start until Gate A passes.

---

## 1. Why the order changes

`BUILD_PLAN.md` states the problem correctly in Section 0:

> Generation is cheap; identity consistency is the hard problem.

And Phase 1's gate is explicit that a failure ends the project:

> **Gate:** ... If identity doesn't hold, stop. Nothing downstream matters.

But Section 10 opens with "Phase 0 in full" — a 16-table schema, migrations, object storage, a job queue, adapter protocols, fakes and a cost ledger — *before* that question is answered. If the answer is no, all of it is discarded. If the answer is yes, it was built without the evidence that should have shaped it: real retry rates, a calibrated threshold, actual cost per usable second, and measured operator time.

The same applies to Phase 2. "Where do the models break on golf content?" is a question about provider behaviour, not about our software. It needs a prompt list, a GPU and a spreadsheet. It does not need a review UI.

Both questions are answerable in under a week with scripts and a folder of files. So they move first, and they merge, because they share one harness.

There is a second reason to merge them. Phase 2's expected result — full swing and ball flight blocked — constrains **D1** (persona name, look, backstory, voice), which `BUILD_PLAN.md` schedules *earlier* than the gate that produces the constraint. Running the format battery up front means D1 is made with the evidence rather than ahead of it. See `docs/decisions/0003-content-format-constraints.md`.

## 2. The revised sequence

Phase numbers from `BUILD_PLAN.md` are preserved. One new stage is inserted ahead of them and two existing phases shrink because Spike 0 absorbs their experimental content.

| Order | Stage | Nature | Gate |
|---|---|---|---|
| 1 | **Spike 0** — Identity & format feasibility | Experiment. Scripts only. | **Gate A** — go / no-go on the whole approach |
| 2 | Phase 0 — Foundations | Build, sized by Spike 0 evidence | As written (§6) |
| 3 | Phase 1 — Identity productionised *(reduced)* | Build | As written (§6) |
| 4 | Phase 2 — Format confirmation *(reduced)* | Short experiment | As written (§6) |
| 5 | Phase 3 — Production pipeline | Build | As written (§6) |
| 6 | Phase 4 — Audience test | Experiment | As written (§6) |
| 7 | Phase 5 — Scale and harden | Build | As written (§6) |

What moves out of Phase 1 into Spike 0: tasks 1.2, 1.3, 1.6, and a minimal throwaway version of 1.4 and 1.5.
What remains in Phase 1: 1.1 (master set ingestion, on the **real** persona look once D1 lands), 1.4 and 1.5 productionised, 1.7 (gate report), plus re-validation of the calibrated threshold against the real look.
What moves out of Phase 2 into Spike 0: task 2.1 (golf shot battery) and a manual-spreadsheet version of 2.2.
What remains in Phase 2: 2.3 (structured rating in the review UI), a confirmation run on the real persona and final provider set, 2.4 and 2.5.

Phase 3 onward is unchanged in content, with the specific fixes in [Plan amendments](#plan-amendments) folded into the relevant tasks.

---

## 3. Spike 0 — Identity & format feasibility

**Target:** 3–5 working days.
**Question 1:** Does a LoRA-anchored face survive image-to-video animation across realistic shooting conditions, at a threshold that separates it from other faces?
**Question 2:** Which golf formats do the video models render usably, and which break?

### Standing constraints

- **No infrastructure.** No Postgres, no Redis, no FastAPI, no Alembic, no adapter protocols, no `Fake*` providers. Files on disk under `spike/runs/<run_id>/`, one JSONL run log, contact sheets as PNG. Vendor SDKs may be imported directly in `scripts/spike/` — the no-SDK-outside-`app/providers/` rule in `CLAUDE.md` binds `app/`, which does not exist yet.
- **Everything is throwaway.** No code from Spike 0 is promoted to `app/` without being rewritten against the adapter contract in `BUILD_PLAN.md` Section 5. The deliverable is evidence, not software.
- **Every run logs cost.** A line per API call: provider, model, units, unit price, total, and the `verified_on` date of the price used. This is the input to the Phase 0 cost guard and to the budget model in Section 9.
- **Every run logs wall-clock operator time.** Manually, in the run log. See amendment A1.
- **Budget cap:** `SPIKE_BUDGET_USD` — **human decision required, see §3.4**. Hard-stop the harness when the running total reaches it.

### 3.1 Use a throwaway look, not the persona

D1 (persona name, look, backstory, voice) is a human decision and is not yet made. Spike 0 does **not** wait for it.

What Spike 0 measures is whether the *technique* holds, not whether *this particular face* holds. A throwaway look answers that, and it avoids burning the real persona's look on an experiment before the approach is proven — the same reasoning `BUILD_PLAN.md` applies to the test identity in task 4.1.

**Caveat, and it is a real one:** identity retention is partly face-dependent. Distinctive bone structure and colouring hold better than a generic look. So Gate A validates the *approach*; the calibrated threshold and the pass rates must be re-measured against the real persona look in Phase 1 before they are trusted. Budget for that re-run.

### 3.2 Tasks

| Task | Output | Acceptance |
|---|---|---|
| **S0.1** Throwaway master set | 12–20 stills of one invented look, tagged angle / distance / light | Covers at least front + 3/4 + profile, and two lighting conditions |
| **S0.2** Embedding harness | `scripts/spike/embed.py`: image or video in, per-frame embeddings at 2 fps out | No-face and multi-face frames handled explicitly and counted, never silently dropped |
| **S0.3** Threshold calibration | Similarity distribution within the master set vs. a control set of different faces; proposed pass threshold with separation statistics | Reports overlap between the two distributions, not just a threshold. If they overlap materially, say so — that is a finding, and a serious one |
| **S0.4** Minimal LoRA run | One (at most three) training runs on a hosted GPU from the throwaway set | Base model licence permits commercial use and is recorded verbatim. Blocks on ADR 0002 |
| **S0.5** Keyframe generation | Start frames for every cell of the condition matrix, each scored | Every keyframe carries a score before any video spend |
| **S0.6** Identity condition matrix | ≥20 clips: angle (front, 3/4, profile) × distance (close, medium, wide) × light (midday, golden hour, overcast, indoor) × motion (static, walking, turning) | Per-clip min and mean score; contact sheet of the worst frame per clip |
| **S0.7** Golf format battery | `BUILD_PLAN.md` task 2.1 prompt set, 2 takes each, on 2 providers | Rated 1–5 by hand in a spreadsheet with the failure tags from task 2.3. No UI |
| **S0.8** Lip-sync drift probe | 3 accepted face-forward clips, lip sync applied, re-scored | Quantifies score delta introduced by lip sync. Directly answers amendment A5 |
| **S0.9** Gate A report | `docs/reports/gate-a.md` | Contains everything in §3.3 |

S0.7 piggybacks on the harness built for S0.6 — same generation path, different prompts and a human rating column instead of an automated one. That sharing is the reason to merge the two phases.

### 3.3 Gate A report contents

1. Threshold calibration: both distributions plotted, separation statistic, proposed threshold, and an explicit statement of how much the distributions overlap.
2. Identity pass rate at that threshold, broken down by each axis of the condition matrix — not a single headline number. The plan's own instinct in task 1.7 is right: the breakdown is where the decision lives.
3. Contact sheet of worst frames, so a human can check whether the score agrees with their eye. **If the scorer passes clips a human rejects, the scorer is the finding**, and Phase 3's auto-reject design needs rethinking before it is built.
4. Lip-sync score delta (S0.8).
5. Golf format matrix: format × provider, usable rate, dominant failure tags.
6. Cost: total spend, spend per *usable* second, and discard rate — the real input to `BUILD_PLAN.md` Section 9, replacing the brief's assumed 3-in-5.
7. Measured operator time across the spike.
8. Recommendation: proceed / change approach / stop.

### 3.4 Budget — human decision (extends D8)

`SPIKE_BUDGET_USD` is a placeholder. The arithmetic below is offered so the number can be set deliberately; it is not a recommendation to spend any particular amount.

Working from the *unverified* prices in `BUILD_PLAN.md` Section 5 (USD 0.036–0.40 per second — the plan's own instruction is not to trust these, and they have **not** been checked against current provider documentation as part of this draft):

- Identity matrix: ~24 clips × 5 s
- Golf battery: ~10 prompts × 2 takes × 2 providers = ~40 clips × 5 s
- Subtotal at face value: ~320 s of video → roughly USD 12–128 depending on model mix
- Discards: assume 2.5× until prompts settle → roughly USD 30–320
- Keyframes: ~100 images, low tens of dollars
- LoRA training: 1–3 hosted GPU runs
- Voice and lip sync for S0.8: small

A cap somewhere in the low hundreds buys the evidence. Set it, and make the harness refuse to exceed it.

### 3.5 Blocking dependencies

| Blocker | Resolves via | Blocks |
|---|---|---|
| Face-embedding model **choice** | `docs/decisions/0004-identity-scorer-dlib-resnet.md` — **settled 2026-09-23 on measured separation**: dlib ResNet | Unblocks S0.2 onward |
| Face-embedding model **licence** | ADR 0004 "The bill" — **open, human decision**: accept the FaceScrub caveat, buy a commercial licence, or revert and accept MARGINAL | Publication, not measurement. Spike scoring proceeds; a published render does not |
| `SPIKE_BUDGET_USD` | §3.4 above, extends D8 | Any paid call |
| Provider access and current pricing | Verify against official docs at implementation time, record in `docs/decisions/` per `CLAUDE.md` | S0.5 onward |
| LoRA base model licence | Checked as part of S0.4, recorded verbatim | S0.4 |

D1, D2, D3, D5, D6 and D7 do **not** block Spike 0. D4 (financial products) is a content policy decision with no bearing on a feasibility spike, but the recommended answer in `BUILD_PLAN.md` is yes and nothing here depends on it.

---

## 4. Gate A

A human reads `docs/reports/gate-a.md` and decides. The three outcomes:

- **Proceed** — identity holds at a threshold that separates, the scorer agrees with human judgement, and enough golf formats survive to support a content concept. Build Phase 0, sized by the evidence.
- **Change approach** — identity holds only in a narrow band of conditions, or the scorer is unreliable. The architecture may still be right; the shot vocabulary, provider mix, or the role of automated scoring needs rework before Phase 0 is built around it.
- **Stop** — identity does not hold, or the surviving formats cannot carry the concept.

**A failed Gate A is a successful spike.** It costs under a week and a few hundred dollars to learn something that would otherwise be discovered three weeks and a full production system later.

---

## 5. Plan amendments

Gaps found in `BUILD_PLAN.md` that are independent of the reordering. Each names the task or table it lands in.

### A1 — Operator time has nowhere to live *(Section 4)*

Section 9 states plainly:

> **The real cost is operator time.** ... That number decides whether the operation is viable.

The data model has no field for it. Task 3.14 reports cost by provider, not labour.

Add: `review.time_spent_s`; `content_piece.brief_started_at` and `content_piece.render_completed_at`. Surface both in the Phase 3 cost report. Start logging it manually in Spike 0.

### A2 — No job table *(Section 4)*

Provider calls that fail or time out still cost money and have no home. `generation` rows only exist for calls that produced something.

Add a `job` table: provider, provider job id, status, submitted/completed timestamps, `cost_usd`, error, and a nullable link to `generation`. The adapter contract in Section 5 should surface failed-call cost so the ledger stays complete.

### A3 — Embedding storage and versioning *(Section 4)*

`reference_asset.embedding` has no stated type. Use `pgvector` (available on the recommended hosting), with the dimension pinned to the chosen model.

More importantly: **a calibrated threshold is valid only for one embedding model at one version.** Changing the scorer silently invalidates every stored vector and the threshold with them. Add `embedding_model` and `embedding_model_version` to `reference_asset`, `keyframe` and `generation`, and store the calibration evidence against that version. Re-calibration must be forced when it changes.

### A4 — The disclosure constraint cannot be a plain CHECK *(Section 4)*

Section 4 requires:

> `render.disclosure_applied` must be `true` for any render referenced by a `publication`.

Postgres CHECK constraints cannot reference another table, so this will quietly become an application-level rule — exactly what `CLAUDE.md` forbids ("enforce in the schema, not just the code").

Implement it as: `UNIQUE (id, disclosure_applied)` on `render`; `publication` carries its own `disclosure_applied` column with a composite foreign key `(render_id, disclosure_applied) REFERENCES render (id, disclosure_applied)` and `CHECK (disclosure_applied)`. The database then makes the invalid state unrepresentable.

`publication.ai_label_set = true` and `approved_by IS NOT NULL` are single-table and remain ordinary CHECKs. Add a test that each constraint actually rejects the bad row — task 0.3 says "constraints tested", and this is what that means.

### A5 — Identity is not re-scored after lip sync *(tasks 3.7, 3.10)*

Task 3.7 applies lip sync to *already-accepted* takes, and nothing scores the result. So `generation.identity_score_*` does not describe what ships — the number on record is from before the last transformation of the face.

Add `render.identity_score_min` and `render.identity_score_mean`, scored after lip sync and after the overlay pass, and gate the render on it. S0.8 sizes the effect before the pipeline is built around it.

### A6 — No moderation or audience-interaction surface *(Section 6, Phase 3 or 4)*

A persona account generates comments, DMs, people who treat her as real despite the disclosure, and harassment. The plan has no module, no policy and no data model for any of it.

This is not a side issue: it is a large share of the operator time that Section 9 identifies as the deciding cost line, and it is unbudgeted. Either scope a moderation surface into Phase 3, or state explicitly in Phase 4 who handles it and how their time is logged. Deciding it is out of scope is a legitimate answer; leaving it unnamed is not.

### A7 — No hard rule against unbudgeted live calls *(`CLAUDE.md`)*

`CLAUDE.md` makes live *tests* opt-in via `pytest -m live`, but nothing stops an ordinary pipeline or script run from spending money. The cost guard (task 0.7) catches budget *ceilings*, not unintended runs.

Suggested addition to the non-negotiable rules:

> - **No live provider call outside an explicitly budgeted run.** Scripts and pipelines that call a paid provider require an explicit budget argument and refuse to start without one. `pytest -m live` remains separately opt-in.

### A8 — Schedule is optimistic *(Section 6)*

Not a defect in the plan's content, but the targets will set expectations that the work cannot meet.

Phase 0 as scoped — scaffold, CI, config validation, a 16-table schema with migrations, storage wrapper, queue, adapter protocols, fakes, cost ledger, secrets — is not "week 1, days 1–3". It is a week or more. Phase 3 is fourteen tasks including a full review UI, assembler, captions, C2PA and platform cuts; "weeks 2–4" is optimistic by roughly two to three times for one engineer with an agent.

Suggest re-baselining after Gate A, when Spike 0 has produced real throughput numbers instead of estimates.

### A9 — C2PA expectations *(task 3.11, Section 7.3)*

Worth recording so effort is sized correctly rather than changing the requirement:

- Most platforms re-encode on upload, which typically strips the manifest. C2PA is a provenance record **for us**, not a disclosure signal the audience sees. The on-video overlay (3.10) and the platform label (7.2) do the disclosure work.
- A manifest that verifies as *trusted* rather than self-signed needs a certificate from a recognised authority. That is a procurement item with lead time, not a library install. Raise it early; it is cheap to start and annoying to discover late.

Keep the requirement. Do not over-invest in it relative to the overlay.

### A10 — Platform API access is gated *(tasks 4.3, 5.1)*

Posting and analytics APIs generally require app review or business-account status, and access for a new, small account is frequently not granted. The plan's "where access permits" hedge is correct; the amendment is only that the manual CSV path in 4.3 should be treated as the **primary** route and built first, with API ingestion as an upgrade. Do not let Phase 4 depend on access that may not arrive.

---

## 6. What this does not change

Worth stating explicitly, because the list above is all criticism and the plan is mostly right:

- The adapter-per-provider contract with prices in config and a `verified_on` date. Correct for a domain that churns quarterly.
- Disclosure enforced in the schema rather than in a flag. Correct, and the reason amendment A4 matters.
- The two-stage identity pipeline. The flagship video models do not accept custom LoRAs; keyframe-then-animate is the way to own the identity layer rather than rent it.
- The provenance backbone — prompt, seed, model, references and cost per artefact. This is the right spine and everything else hangs off it.
- Human approval before any publication, permanently.
- Section 9's judgement that operator time, not generation spend, decides viability. Amendment A1 exists only to make that measurable.

---

## 7. Open decisions this draft creates

| # | Decision | Where | Blocks |
|---|---|---|---|
| ~~A~~ | ~~Accept or reject the spike-first reordering~~ | **Closed 2026-09-22: accepted** | — |
| ~~B~~ | ~~Face-embedding model and licence route~~ | **Closed 2026-09-22: DINOv2** (ADR 0002) | — |
| C | `SPIKE_BUDGET_USD` | §3.4 | Spike 0 |
| D | Whether the concept survives a likely swing/ball-flight block | ADR 0003, informed by S0.7 | D1 |
| E | Moderation: in scope for Phase 3, or explicitly owned elsewhere | A6 | Phase 4 |
