# CLAUDE.md — Persona Studio

Production system for a recurring, openly-AI golf personality. Full spec: `BUILD_PLAN.md`. Read it before starting any task.

## Non-negotiable rules

- **Never hardcode model names, endpoints, or prices.** They live in `config/providers.yaml` with a `verified_on` date. Verify every provider against its current official docs before implementing an adapter, and record what you found in `docs/decisions/`.
- **No vendor SDK outside `app/providers/`.** Pipeline code uses the adapter protocols only.
- **Disclosure cannot be disabled.** Every final render gets the on-video disclosure overlay and a C2PA manifest. Don't add a flag, env var, or code path that skips either.
- **No publishing without a human.** Publication records require `ai_label_set=true` and a named approver. Never auto-post.
- **Financial products are out of scope permanently.** The policy guard blocks them. Don't weaken it.
- **Every paid API call goes through the cost guard** and writes a `cost_ledger` row in the same transaction.
- **Secrets from environment only.** Keep `.env.example` current.
- **Check licences** for any model weights you pull in (face embeddings, LoRA base models). Commercial use must be permitted; record the licence.

## Working style

- Stop at every phase gate in `BUILD_PLAN.md` Section 6. Write the gate report to `docs/reports/` and wait for human review.
- Don't make the human decisions in `BUILD_PLAN.md` Section 1. Use the placeholders and flag them.
- Build and test on `Fake*` providers first. Live-provider tests are opt-in (`pytest -m live`) and budget-capped.
- Ask before adding any new paid service or infrastructure component.
- Significant deviation from the plan or stack → write a short ADR in `docs/decisions/`.

## Commands

- `make check` — lint, types, tests
- `make dev` — run web + worker locally
- `make migrate` — apply migrations
