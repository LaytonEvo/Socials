"""The schema from BUILD_PLAN Section 4, with amendments A1-A5 folded in.

Every generated artefact traces back to the exact prompt, model, seed, reference
assets and cost that produced it. That is the provenance backbone and also the
continuity record, so the foreign keys are the point of this module rather than
an implementation detail.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import (
    Base,
    CreatedAt,
    JsonDict,
    Money,
    OptionalMoney,
    OptionalStorageKey,
    PrimaryKey,
    Score,
    StorageKey,
    one_of,
    score_in_unit_range,
)

#: Pinned to the configured scorer: dlib ResNet, 128-d (config/providers.yaml,
#: `embedder.dim`). Amendment A3 requires the dimension to be pinned to the
#: chosen model, so changing the scorer is a migration and not a config edit —
#: which is the point, because a threshold calibrated against one model means
#: nothing under another. `tests/app/test_models.py` asserts this matches config,
#: so the two cannot drift silently.
EMBEDDING_DIM = 128

# --------------------------------------------------------------- identity ----


class Persona(Base):
    """One row for now; the schema supports several."""

    __tablename__ = "persona"
    __table_args__ = (one_of("status", "draft", "active", "retired"),)

    id: Mapped[PrimaryKey]
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")
    #: Set once a LoRA version exists, so the FK is added in a later migration
    #: rather than creating a circular dependency between two empty tables.
    active_lora_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[CreatedAt]


class ReferenceAsset(Base):
    """The master still set. **[A3]** carries the embedding and its provenance."""

    __tablename__ = "reference_asset"
    __table_args__ = (
        one_of("kind", "face", "body", "outfit", "lighting"),
        # A vector without the model that produced it is a number with no
        # meaning, and the pair is what makes re-calibration enforceable.
        CheckConstraint(
            "(embedding IS NULL) OR "
            "(embedding_model IS NOT NULL AND embedding_model_version IS NOT NULL)",
            name="ck_reference_asset_embedding_has_provenance",
        ),
        Index("ix_reference_asset_persona_master", "persona_id", "is_master"),
    )

    id: Mapped[PrimaryKey]
    persona_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("persona.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[StorageKey]
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_master: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    created_at: Mapped[CreatedAt]


class LoraVersion(Base):
    """Versioned identity layer. The base model's licence must permit commercial use."""

    __tablename__ = "lora_version"

    id: Mapped[PrimaryKey]
    persona_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("persona.id", ondelete="CASCADE"), nullable=False
    )
    base_model: Mapped[str] = mapped_column(String(256), nullable=False)
    #: CLAUDE.md requires the licence be checked and recorded. NOT NULL is the
    #: schema saying a version cannot exist without one.
    base_model_licence: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    storage_key: Mapped[StorageKey]
    eval_score: Mapped[Score]
    created_at: Mapped[CreatedAt]


# ------------------------------------------------------------- production ----


class ContentPiece(Base):
    """One finished video. **[A1]** the two timestamps give per-piece labour."""

    __tablename__ = "content_piece"
    __table_args__ = (
        one_of(
            "status",
            "brief",
            "shotlist",
            "generating",
            "review",
            "assembled",
            "published",
            "abandoned",
        ),
        CheckConstraint(
            "render_completed_at IS NULL OR brief_started_at IS NULL "
            "OR render_completed_at >= brief_started_at",
            name="ck_content_piece_timestamps_ordered",
        ),
    )

    id: Mapped[PrimaryKey]
    persona_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("persona.id", ondelete="RESTRICT"), nullable=False
    )
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="brief")
    target_platforms: Mapped[JsonDict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    #: **[A1]** Operator time is the cost line that decides viability
    #: (BUILD_PLAN Section 9) and nothing recorded it before these.
    brief_started_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    render_completed_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[CreatedAt]


class Shot(Base):
    """One shot from the shot list."""

    __tablename__ = "shot"
    __table_args__ = (
        one_of("shot_type", "face", "broll"),
        UniqueConstraint("content_piece_id", "order_index", name="uq_shot_order"),
        CheckConstraint("duration_s > 0", name="ck_shot_duration_positive"),
    )

    id: Mapped[PrimaryKey]
    content_piece_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_piece.id", ondelete="CASCADE"), nullable=False
    )
    #: BUILD_PLAN calls this `order`. Renamed because ORDER is a reserved word:
    #: SQLAlchemy quotes it correctly, but every hand-written query and every
    #: psql session afterwards has to remember to, and one that forgets is a
    #: syntax error at the worst moment.
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    duration_s: Mapped[float] = mapped_column(nullable=False)
    camera: Mapped[str | None] = mapped_column(Text, nullable=True)
    lighting: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    shot_type: Mapped[str] = mapped_column(String(16), nullable=False)


class Keyframe(Base):
    """A shot's start frame. **[A3]** records which scorer produced its score."""

    __tablename__ = "keyframe"
    __table_args__ = (score_in_unit_range("identity_score"),)

    id: Mapped[PrimaryKey]
    shot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), nullable=False
    )
    lora_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lora_version.id", ondelete="RESTRICT"), nullable=True
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int | None] = mapped_column(nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    storage_key: Mapped[StorageKey]
    identity_score: Mapped[Score]
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[CreatedAt]


class Generation(Base):
    """One take."""

    __tablename__ = "generation"
    __table_args__ = (
        one_of("status", "queued", "generating", "scored", "auto_rejected", "ready", "failed"),
        score_in_unit_range("identity_score_min"),
        score_in_unit_range("identity_score_mean"),
        CheckConstraint(
            "identity_score_min IS NULL OR identity_score_mean IS NULL "
            "OR identity_score_min <= identity_score_mean",
            name="ck_generation_min_not_above_mean",
        ),
        CheckConstraint("cost_usd >= 0", name="ck_generation_cost_not_negative"),
    )

    id: Mapped[PrimaryKey]
    shot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), nullable=False
    )
    keyframe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("keyframe.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int | None] = mapped_column(nullable=True)
    params: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    duration_s: Mapped[float] = mapped_column(nullable=False)
    storage_key: Mapped[OptionalStorageKey]
    identity_score_min: Mapped[Score]
    identity_score_mean: Mapped[Score]
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="queued")
    cost_usd: Mapped[Money]
    created_at: Mapped[CreatedAt]


class Job(Base):
    """**[A2]** Every provider call, including the ones that produced nothing.

    `generation` rows only exist for calls that returned something, so a timeout
    or a refusal after billing had no home and the ledger was quietly incomplete.
    A job with a null `generation_id` is exactly the case that was previously
    unrepresentable.
    """

    __tablename__ = "job"
    __table_args__ = (
        one_of("status", "submitted", "running", "succeeded", "failed", "timed_out", "cancelled"),
        CheckConstraint("cost_usd >= 0", name="ck_job_cost_not_negative"),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= submitted_at",
            name="ck_job_completed_after_submitted",
        ),
        # A finished call must say what it cost, even if that cost is zero. This
        # is what keeps the ledger complete: "we do not know" is not an option
        # the schema offers once the call has ended.
        CheckConstraint(
            "status IN ('submitted', 'running') OR cost_usd IS NOT NULL",
            name="ck_job_finished_has_cost",
        ),
        Index("ix_job_provider_job_id", "provider", "provider_job_id"),
    )

    id: Mapped[PrimaryKey]
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_job_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="submitted")
    submitted_at: Mapped[CreatedAt]
    completed_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    cost_usd: Mapped[OptionalMoney]
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generation.id", ondelete="SET NULL"), nullable=True
    )


class Review(Base):
    """Human QA. **[A1]** `time_spent_s` is the labour measurement."""

    __tablename__ = "review"
    __table_args__ = (
        one_of("decision", "accept", "reject"),
        CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)", name="ck_review_rating_range"
        ),
        CheckConstraint(
            "time_spent_s IS NULL OR time_spent_s >= 0", name="ck_review_time_not_negative"
        ),
    )

    id: Mapped[PrimaryKey]
    generation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generation.id", ondelete="CASCADE"), nullable=False
    )
    reviewer: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Pipe-separated, from `FAILURE_TAG_GROUPS`. Not a native enum array
    #: because the vocabulary has already been rewritten once.
    failure_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_spent_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[CreatedAt]


class VoiceLine(Base):
    """One rendered line of dialogue."""

    __tablename__ = "voice_line"
    __table_args__ = (CheckConstraint("cost_usd >= 0", name="ck_voice_line_cost_not_negative"),)

    id: Mapped[PrimaryKey]
    shot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shot.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    voice_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[StorageKey]
    cost_usd: Mapped[Money]
    created_at: Mapped[CreatedAt]


# --------------------------------------------------------------- delivery ----


class Render(Base):
    """An assembled output. **[A5]** carries scores taken after lip sync.

    The UNIQUE on (id, disclosure_applied) exists only so `publication` can point
    at it with a composite foreign key. It is redundant as a uniqueness claim —
    `id` is already the primary key — and that is fine: its job is to be a
    referencable target, which is the trick that makes **[A4]** enforceable in
    the database rather than in application code.
    """

    __tablename__ = "render"
    __table_args__ = (
        one_of("aspect", "9:16", "16:9", "1:1"),
        UniqueConstraint("id", "disclosure_applied", name="uq_render_id_disclosure"),
        score_in_unit_range("identity_score_min"),
        score_in_unit_range("identity_score_mean"),
        # A manifest cannot exist for a render that was never disclosed, because
        # the overlay pass is what sets the flag and signing happens after it.
        CheckConstraint(
            "c2pa_manifest_key IS NULL OR disclosure_applied",
            name="ck_render_manifest_requires_disclosure",
        ),
    )

    id: Mapped[PrimaryKey]
    content_piece_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_piece.id", ondelete="CASCADE"), nullable=False
    )
    edl_json: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    aspect: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Set true ONLY after the overlay pass has actually run (task 3.10).
    disclosure_applied: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    c2pa_manifest_key: Mapped[OptionalStorageKey]
    storage_key: Mapped[OptionalStorageKey]
    #: **[A5]** Scored after lip sync and after the overlay pass, because
    #: `generation.identity_score_*` describes the face before its last
    #: transformation.
    identity_score_min: Mapped[Score]
    identity_score_mean: Mapped[Score]
    created_at: Mapped[CreatedAt]


class Publication(Base):
    """A publishing record. **[A4]** and "no publishing without a human".

    Three constraints make the forbidden states unrepresentable rather than
    merely discouraged:

    - the composite foreign key can only resolve against a render whose
      `disclosure_applied` is true, paired with the CHECK below that pins this
      row's copy of the flag to true;
    - `ai_label_set` must be true;
    - `approved_by` is NOT NULL, so no row exists without a named approver.
    """

    __tablename__ = "publication"
    __table_args__ = (
        ForeignKeyConstraint(
            ["render_id", "disclosure_applied"],
            ["render.id", "render.disclosure_applied"],
            name="fk_publication_render_disclosed",
            ondelete="RESTRICT",
        ),
        CheckConstraint("disclosure_applied", name="ck_publication_disclosure_applied"),
        CheckConstraint("ai_label_set", name="ck_publication_ai_label_set"),
        CheckConstraint("length(trim(approved_by)) > 0", name="ck_publication_approver_named"),
        UniqueConstraint("platform", "url", name="uq_publication_platform_url"),
    )

    id: Mapped[PrimaryKey]
    render_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    #: This row's own copy, so the composite FK has something to match. Always
    #: true, by the CHECK above.
    disclosure_applied: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    account: Mapped[str] = mapped_column(String(128), nullable=False)
    ai_label_set: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    #: A named human (D6). Never a service account, never "system".
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[CreatedAt]


class MetricSnapshot(Base):
    """Analytics, ingested manually first (amendment A10)."""

    __tablename__ = "metric_snapshot"
    __table_args__ = (
        UniqueConstraint("publication_id", "captured_at", name="uq_metric_snapshot_capture"),
    )

    id: Mapped[PrimaryKey]
    publication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publication.id", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    watch_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_json: Mapped[JsonDict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    followers_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engagement: Mapped[int | None] = mapped_column(Integer, nullable=True)


# --------------------------------------------------------------------- ops ----


class CostLedger(Base):
    """All spend. One row per paid call, written in the call's own transaction.

    Polymorphic by `(ref_table, ref_id)` rather than by a column per table: the
    referencing tables are `generation`, `job`, `keyframe` and `voice_line`
    today, and a nullable FK per table would grow with every new cost source and
    still allow a row that points at none of them.
    """

    __tablename__ = "cost_ledger"
    __table_args__ = (
        one_of("ref_table", "generation", "job", "keyframe", "voice_line"),
        CheckConstraint("total_usd >= 0", name="ck_cost_ledger_total_not_negative"),
        CheckConstraint("units >= 0", name="ck_cost_ledger_units_not_negative"),
        # CLAUDE.md requires prices carry a verified_on date. The ledger records
        # the date of the price it actually charged against, so a reconciliation
        # against a real invoice can find the stale ones.
        Index("ix_cost_ledger_ref", "ref_table", "ref_id"),
        Index("ix_cost_ledger_created", "created_at"),
    )

    id: Mapped[PrimaryKey]
    ref_table: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    units: Mapped[Decimal] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(nullable=False)
    total_usd: Mapped[Money]
    #: The `verified_on` of the price this row charged against.
    price_verified_on: Mapped[dt.date | None] = mapped_column(nullable=True)
    created_at: Mapped[CreatedAt]


class DecisionLog(Base):
    """D1-D8 and the format decisions, recorded as they are made."""

    __tablename__ = "decision_log"
    __table_args__ = (Index("ix_decision_log_key", "key"),)

    id: Mapped[PrimaryKey]
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    #: A named human. These are the decisions BUILD_PLAN Section 1 reserves, so
    #: a row attributed to the system is a bug in whatever wrote it.
    decided_by: Mapped[str] = mapped_column(String(128), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[CreatedAt]
