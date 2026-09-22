# ADR 0002 — Face-embedding model and licence route

- **Status:** **Open — human decision required.** Blocks Spike 0.
- **Date:** 2026-09-22
- **Deciders:** Layton (owner), supervising engineer; likely touches counsel under D7
- **Relates to:** `BUILD_PLAN.md` Section 3 (stack), tasks 1.2 and 1.3

## Context

The identity scorer is the measuring instrument for the entire project. It gates every take (task 3.4), produces the evidence for the Phase 1 gate, and defines the threshold that auto-reject depends on. It cannot be chosen provisionally and swapped later without invalidating everything measured with it — see amendment A3 in `docs/BUILD_ORDER.md`.

`BUILD_PLAN.md` flags the problem in a single table cell:

> Face scoring | Face-embedding model (ArcFace-class) | **Check licence for commercial use** — some popular pretrained weights are non-commercial only

That undersells it. The best-known ArcFace-class pretrained weight sets in open circulation are distributed under research-or-non-commercial terms. This is a commercial venture. A licence that forbids commercial use is not a footnote to clear later; it is a blocker on the critical path of the first task that spends money.

Two further points shape the choice:

1. **This is an unusual application of face recognition.** These models are trained to discriminate between *real* identities. We are measuring whether two synthetic renders depict the same invented person. Cosine similarity is a proxy, and its discriminative power in this setting is an open empirical question — which is why task 1.3's calibration against a control set of different faces is essential and why Gate A reports distribution *overlap*, not just a threshold.
2. **The master set is itself synthetic.** Similarity measured within it partly reflects the consistency of the image generator rather than identity as such. This does not invalidate the method, but it means the threshold must be read as "consistent with our generator's rendering of this look", not as an identity guarantee.

## Options

**(a) Permissively-licensed open weights.** A face-embedding model whose licence permits commercial use, self-hosted.
*For:* no per-call cost, no vendor dependency, embeddings stay in our infrastructure, reproducible forever. *Against:* the permissively-licensed options are generally not the best-performing ones; needs its own evaluation before it is trusted as the instrument.

**(b) Commercial licence for a high-performing weight set.** Pay the rights-holder for commercial terms on a model that would otherwise be research-only.
*For:* best accuracy, clean legal position, self-hosted. *Against:* cost and procurement lead time; may not be offered at a sensible scale for a single-persona project.

**(c) Hosted face-comparison API.** A cloud provider's face-similarity endpoint.
*For:* no licence question, no weights to host, fast to start. *Against:* per-call cost across thousands of frames at 2 fps — likely the dominant line item; a hard external dependency for a core QA function; provider terms of service around face data may restrict this use; embeddings may not be retrievable, which breaks the stored-embedding design in Section 4 and the threshold calibration in 1.3.

**(d) Train or fine-tune our own.** Build an embedding model from a commercially usable dataset.
*For:* fully owned. *Against:* a project in itself, wildly disproportionate to the need, and reintroduces dataset licensing questions rather than removing them.

## Recommendation

**Option (a), with (b) as the fallback if (a) evaluates poorly.**

The reasoning: this instrument runs on every frame of every take forever, so per-call pricing (c) compounds badly against exactly the workload we have. It also needs to be reproducible years out for provenance purposes, which argues for self-hosted weights over a hosted endpoint that can change or be withdrawn beneath us. And because the task is an unusual one — synthetic-to-synthetic comparison, calibrated against our own control set — raw benchmark ranking matters less here than it would for real-identity recognition. A permissively-licensed model that separates our distributions cleanly is sufficient; a state-of-the-art model that we cannot legally use is not.

(d) is out of proportion. (c) is a reasonable *cross-check* during calibration — a second opinion on a sample — but should not be the production scorer.

## Required before this closes

1. Shortlist two or three candidate models under option (a) and **read the actual current licence text** for each, not a summary. Record the licence verbatim and the date checked, per the `CLAUDE.md` rule on model weights.
2. Run task S0.3's calibration on the shortlist. Choose on measured separation between same-face and different-face distributions, not on published benchmarks.
3. Record the chosen model, version, embedding dimension and licence in this ADR, and pin them in config. A change to any of them forces re-calibration (amendment A3).
4. If the outcome is (b) or (c), raise it under the `CLAUDE.md` rule requiring approval before adding a paid service.

## Consequences

Until this is decided, Spike 0 cannot start: S0.2 onward all depend on the scorer. It is the single highest-priority open item.

If no commercially usable option separates the distributions adequately, that is itself a Gate A finding — automated identity scoring would become advisory rather than gating, and the human review load in Phase 3 rises substantially. Task 3.4's auto-reject design would need rework before it is built.
