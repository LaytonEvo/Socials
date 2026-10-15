"""Recording a run in the database, so that spend is auditable and the ceiling is real.

CLAUDE.md, non-negotiable: *"Every paid API call goes through the cost guard and writes a
`cost_ledger` row in the same transaction."* The guard half was built and has been used by
every spike script. The ledger half was not: `record_call` had no caller outside its own
module and the tests, so `cost_ledger` was **empty** — not thin, empty — after weeks of
live runs.

That makes the monthly ceiling worse than absent. `BudgetGuard` enforces `monthly_usd`
against `spend_this_month`, which reads the ledger, so an empty ledger means every run
measured its spend against zero and every run was under budget by construction. The guard
was reporting compliance it could not have checked. This is the same shape as the three
render failures this project has already found: a check that reads something other than
the thing it claims to be checking.

**One transaction per paid call.** Not one per run. A run makes fifteen or twenty billed
calls over half an hour and can die in the middle of them — a timeout, a 402, a container
reclaim. Spend that has happened must be durable the moment it happens, so each method
here flushes its entity row and its ledger row together and commits that pair. The "same
transaction" rule is about the two writes landing together, not about batching a run.

**The scaffolding is opened before any money is spent.** A ledger row needs a `shot` to
hang off, which needs a `content_piece`, which needs a `persona`. Creating those lazily
after the first call would mean the first call is the one that cannot be recorded.

**Keys, never blobs** (`app/models/base.py`). `keyframe` and `voice_line` require a
non-null `storage_key`, so a caller records them only once the artefact is in object
storage. That is a feature: a recorded artefact nobody can retrieve is the audit problem
in a different place.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.costs.ledger import record_call, record_generation_cost
from app.models import ContentPiece, Generation, Keyframe, Persona, Shot, VoiceLine

#: What `shot.shot_type` may be (`ck_shot_type_vocabulary`). The pipeline's own word for
#: this distinction is `face_expected`, so the mapping is made here once rather than at
#: each call site, where the two spellings would drift.
FACE = "face"
BROLL = "broll"


@dataclass(frozen=True)
class ShotSpec:
    """What a shot is, as the shot list declares it — before anything is generated."""

    name: str
    description: str
    duration_s: float
    face_expected: bool
    dialogue: str | None = None


@dataclass
class RunRecorder:
    """The database side of one run. Every method writes its ledger row with its entity."""

    session: Session
    piece: ContentPiece
    shots: dict[str, Shot] = field(default_factory=dict)

    def _shot(self, name: str) -> Shot:
        try:
            return self.shots[name]
        except KeyError:
            raise KeyError(
                f"no shot named {name!r} in this run; it was opened with "
                f"{sorted(self.shots)}. A paid call for an unrecorded shot has nowhere "
                f"to hang its ledger row."
            ) from None

    def keyframe(
        self,
        shot: str,
        *,
        provider: str,
        model: str,
        prompt: str,
        storage_key: str,
        identity_score: float | None,
        units: Decimal,
        unit_price: Decimal,
        price_verified_on: dt.date | None,
        embedding_model: str | None = None,
    ) -> Keyframe:
        row = Keyframe(
            shot_id=self._shot(shot).id,
            prompt=prompt,
            provider=provider,
            model=model,
            storage_key=storage_key,
            identity_score=identity_score,
            embedding_model=embedding_model,
        )
        self.session.add(row)
        self.session.flush()
        record_call(
            self.session,
            ref_table="keyframe",
            ref_id=row.id,
            provider=provider,
            units=units,
            unit_price=unit_price,
            price_verified_on=price_verified_on,
        )
        self.session.commit()
        return row

    def take(
        self,
        shot: str,
        *,
        keyframe: Keyframe | None,
        provider: str,
        model: str,
        prompt: str,
        params: dict[str, object],
        duration_s: float,
        units: Decimal,
        unit_price: Decimal,
        price_verified_on: dt.date | None,
        storage_key: str | None = None,
        identity_min: float | None = None,
        identity_mean: float | None = None,
        status: str = "scored",
        embedding_model: str | None = None,
    ) -> Generation:
        """One take, scored or not, picked or not. Rejected takes are recorded too.

        A take that was generated and then not used still cost what it cost. Recording
        only the picked take would understate a run by the number of takes minus one,
        which on this pipeline is most of the bill.
        """
        row = Generation(
            shot_id=self._shot(shot).id,
            keyframe_id=keyframe.id if keyframe is not None else None,
            provider=provider,
            model=model,
            prompt=prompt,
            params=dict(params),
            duration_s=duration_s,
            storage_key=storage_key,
            identity_score_min=identity_min,
            identity_score_mean=identity_mean,
            embedding_model=embedding_model,
            status=status,
            cost_usd=Decimal(0),
        )
        self.session.add(row)
        self.session.flush()
        record_generation_cost(
            self.session,
            row,
            units=units,
            unit_price=unit_price,
            price_verified_on=price_verified_on,
        )
        self.session.commit()
        return row

    def voice(
        self,
        shot: str,
        *,
        text: str,
        voice_id: str,
        provider: str,
        storage_key: str,
        units: Decimal,
        unit_price: Decimal,
        price_verified_on: dt.date | None,
    ) -> VoiceLine:
        row = VoiceLine(
            shot_id=self._shot(shot).id,
            text=text,
            voice_id=voice_id,
            provider=provider,
            storage_key=storage_key,
            cost_usd=Decimal(0),
        )
        self.session.add(row)
        self.session.flush()
        ledger = record_call(
            self.session,
            ref_table="voice_line",
            ref_id=row.id,
            provider=provider,
            units=units,
            unit_price=unit_price,
            price_verified_on=price_verified_on,
        )
        row.cost_usd = ledger.total_usd
        self.session.commit()
        return row

    def finish(self, *, status: str = "assembled") -> None:
        self.piece.status = status
        self.piece.render_completed_at = dt.datetime.now(dt.UTC)
        self.session.commit()


def open_run(
    session: Session,
    *,
    persona_name: str,
    brief: str,
    video_format: str,
    shots: list[ShotSpec],
    target_platforms: dict[str, object] | None = None,
) -> RunRecorder:
    """Create (or find) the persona, open a content piece, and write its shot list.

    The persona is looked up by name rather than created blindly: `persona.name` is
    unique, and a run that invented a second "Mollie" would split her history in two.
    """
    persona = session.execute(
        select(Persona).where(Persona.name == persona_name)
    ).scalar_one_or_none()
    if persona is None:
        persona = Persona(name=persona_name, status="draft")
        session.add(persona)
        session.flush()

    piece = ContentPiece(
        persona_id=persona.id,
        brief=brief,
        format=video_format,
        status="generating",
        target_platforms=dict(target_platforms or {}),
        brief_started_at=dt.datetime.now(dt.UTC),
    )
    session.add(piece)
    session.flush()

    recorder = RunRecorder(session=session, piece=piece)
    for index, spec in enumerate(shots):
        row = Shot(
            content_piece_id=piece.id,
            order_index=index,
            description=spec.description,
            duration_s=spec.duration_s,
            dialogue=spec.dialogue,
            shot_type=FACE if spec.face_expected else BROLL,
        )
        session.add(row)
        session.flush()
        recorder.shots[spec.name] = row
    session.commit()
    return recorder


def piece_id_of(recorder: RunRecorder) -> uuid.UUID:
    """The piece id, for the guard's per-piece ceiling."""
    return recorder.piece.id
