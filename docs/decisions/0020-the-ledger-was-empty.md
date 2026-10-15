# ADR 0020 — The ledger was empty, so the ceiling was decorative

**Date** 2026-10-15
**Status** accepted
**Amends** nothing. Implements a CLAUDE.md rule that was half-built.

## What was found

While pre-flighting the bunker run, `cost_ledger` was queried for month-to-date spend.
It returned no rows. Not a small number — **zero rows, ever**, after three weeks of live
provider calls across keyframes, takes, voice lines, lip sync and a LoRA training run.
Every other table in the schema is empty too: `persona`, `content_piece`, `shot`,
`generation`, `keyframe`, `voice_line`.

CLAUDE.md, non-negotiable: *"Every paid API call goes through the cost guard and writes a
`cost_ledger` row in the same transaction."* Half of that was built. `BudgetGuard` exists,
is good, and every spike script uses it to price a slot and bound a run. `record_call`
also exists, with tests. The two were never connected: `record_call` had no caller outside
its own module and `tests/app/test_costs.py`.

## Why it matters more than "spend is unaudited"

`BudgetGuard.check` enforces `monthly_usd` by reading `spend_this_month`, which reads the
ledger. An empty ledger means every call compared its cost against **zero** spent, so
every call was under the $100 ceiling by construction. The guard was not lenient; it was
blind, and it reported compliance it had no way to check.

This is the same defect shape the render work has now hit four times: a check that reads
something other than the thing it claims to check. `golf.py` reads prompt text and calls
it golf correctness. The acceptance gate read identity and called it a good shot while
swing length went unmeasured. The seam detector was calibrated on portraits and applied to
full-body stills. And here, the budget guard read an empty table and called it spend.

A second finding came with it: the DB-backed tests skip when `DATABASE_URL` is unset, and
it was unset, so `make check` had been reporting **686 passed, 83 skipped** while 76 of
those skips were the persistence suite. With the database up it is 762 passed, 17 skipped.
A green check that silently drops a sixth of itself is the same problem again.

## Decision

`app/pipeline/recording.py` connects them. `open_run` creates the persona, content piece
and shot rows **before** any money is spent, so the first paid call is not the one that
cannot be recorded. `RunRecorder.keyframe`, `.take` and `.voice` each write their entity
row and its ledger row and commit that pair.

Three choices worth stating:

- **One transaction per paid call, not per run.** A run makes fifteen to twenty billed
  calls over half an hour and can die mid-way. Spend that has happened must be durable
  when it happens. The "same transaction" rule is about the two writes landing together.
- **Rejected attempts are recorded.** A keyframe redraw and an unpicked take were billed.
  Recording only the keepers understates this pipeline by most of its bill — at three
  takes a shot, two thirds of the video spend is takes nobody uses.
- **Lip sync is recorded as a `generation`.** `ck_ref_table_vocabulary` has no "lipsync"
  value, and adding one would put that spend outside the vocabulary the ledger is checked
  against. A lip-synced clip is a derived take: same shot, different model, its own bill.

## What this does not fix

**The ledger starts from a false zero.** Everything spent before today is unrecorded and
cannot be reconstructed from here — the amounts are in fal's invoices, not in anything
this repo holds. So the first month under a working ceiling will undercount by whatever
was spent to date. Backfilling from the invoice is an owner decision, not something to
invent: a ledger row is a record of a billed call, and writing rows for calls whose
details are gone would make the audit trail worse, not better.

**The pairing lives in the script, not the pipeline.** `make_bunker.py` calls
`guard.check` before each provider call and the recorder after it. That belongs in the
orchestrator (BUILD_PLAN 3.4), which does not exist yet. Until it does, every script that
spends has to do this itself, and a new script that forgets will reopen exactly this hole.
The orchestrator should make it impossible to call a provider without both halves — the
same way `FinalRender` can only be made by `apply_disclosure`.
