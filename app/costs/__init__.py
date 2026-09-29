"""Cost ledger and budget guard.

Every paid API call goes through the guard and writes a `cost_ledger` row in the
same transaction (CLAUDE.md). The guard refuses a job that would exceed
`budget.monthly_usd` or `budget.per_piece_usd` *before* the call is made.

Two rules the spike learned the hard way:

- **A price without a `verified_on` date is refused**, as is one older than
  `price_max_age_days`. A stale price is a silent overspend.
- **Where a provider publishes more than one rate, the guard takes the
  higher.** A guard that understates lets a run sail past the cap while
  reporting it is inside it; over-reserving spends less than budgeted, which is
  the safe direction to be wrong in.

Amendment A7, proposed: no live provider call outside an explicitly budgeted
run. The spike already works this way — budgets are passed per command, never
read from the environment.
"""
