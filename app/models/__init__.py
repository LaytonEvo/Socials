"""SQLAlchemy 2.x models and queries — BUILD_PLAN Section 4.

Amendments A1-A5 are folded into that section and hold here:

- `job` rows exist for calls that produced nothing, so the ledger stays whole.
- Every row holding an embedding also records the model and its version: a
  calibrated threshold is valid for exactly one model at one version.
- The disclosure rule is a composite foreign key, not a CHECK and not an
  application rule. Postgres refuses a publication pointing at an undisclosed
  render.
"""

from __future__ import annotations

from .base import Base
from .session import (
    DatabaseNotConfigured,
    database_url,
    make_engine,
    make_session_factory,
    session_scope,
)
from .tables import (
    EMBEDDING_DIM,
    ContentPiece,
    CostLedger,
    DecisionLog,
    Generation,
    Job,
    Keyframe,
    LoraVersion,
    MetricSnapshot,
    Persona,
    Publication,
    ReferenceAsset,
    Render,
    Review,
    Shot,
    VoiceLine,
)

__all__ = [
    "EMBEDDING_DIM",
    "Base",
    "ContentPiece",
    "CostLedger",
    "DatabaseNotConfigured",
    "DecisionLog",
    "Generation",
    "Job",
    "Keyframe",
    "LoraVersion",
    "MetricSnapshot",
    "Persona",
    "Publication",
    "ReferenceAsset",
    "Render",
    "Review",
    "Shot",
    "VoiceLine",
    "database_url",
    "make_engine",
    "make_session_factory",
    "session_scope",
]
