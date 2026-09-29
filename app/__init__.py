"""Persona Studio — the production application.

`scripts/spike/` is the Spike 0 harness and is throwaway by design. This package
is the system BUILD_PLAN specifies, and the two share nothing but the repo.

Boundaries that are rules, not conventions (CLAUDE.md), and are enforced by
`tests/app/test_scaffold.py`:

- **No vendor SDK outside `app.providers`.** Everything else uses the adapter
  protocols. A pipeline module that imports a provider's client directly makes
  the provider unswappable and the call untestable.
- **Disclosure cannot be disabled.** `app.compliance` owns the overlay and the
  C2PA manifest, and no flag, env var or code path skips either.
- **No paid call outside the cost guard.** `app.costs` writes a `cost_ledger`
  row in the same transaction as the call it is paying for.
"""
