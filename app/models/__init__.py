"""SQLAlchemy 2.x models and queries — BUILD_PLAN Section 4.

Amendments A1-A5 are folded into that section and must hold here:

- `job` rows exist for calls that produced nothing, so the ledger stays whole.
- Every row holding an embedding also records the model and its version: a
  calibrated threshold is valid for exactly one model at one version.
- The disclosure rule is a composite foreign key, not a CHECK and not an
  application rule. Postgres refuses a publication pointing at an undisclosed
  render.
"""
