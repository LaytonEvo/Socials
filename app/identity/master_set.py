"""Master set ingestion — task 1.1.

Reads stills, computes an embedding for each, uploads the image to object storage and
writes a `reference_asset` row carrying the vector *and* the model and version that
produced it (amendment A3).

Two things it deliberately does not do.

**It does not guess a `kind`.** BUILD_PLAN's vocabulary is face / body / outfit /
lighting, and the existing 105 stills were filtered for face presence and never
tagged. Which still is a good body reference, or demonstrates a lighting condition, is
a visual judgement; inferring it from a bounding box would put fabricated metadata into
the provenance backbone. The caller says what kind it is ingesting, and the default is
the only one the evidence supports.

**It does not silently skip a rejection.** Every still that cannot be embedded is
reported with the reason, because a set that quietly shrank is a centroid that quietly
moved — and the threshold is defined against that centroid.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from app.models import Persona, ReferenceAsset
from app.storage import StorageBackend, key_for

from .embedder import DlibEmbedder, Embedding, FaceOutcome, FaceReading, cosine

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})

#: The kinds `reference_asset.kind` accepts.
KINDS = ("face", "body", "outfit", "lighting")


@dataclass
class Rejection:
    path: Path
    outcome: FaceOutcome
    detail: str | None = None


@dataclass
class IngestReport:
    kind: str
    ingested: list[uuid.UUID] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    embeddings: list[Embedding] = field(default_factory=list)
    face_area_fractions: list[float] = field(default_factory=list)

    @property
    def considered(self) -> int:
        return len(self.ingested) + len(self.rejected)

    def framing(self) -> dict[str, int]:
        """Close / medium / wide, by face area as a fraction of the frame.

        Recorded because it is the only objective statement available about what the
        stills contain, and the answer mattered: a median of 6% means the frame is
        overwhelmingly not-face, so these are medium-distance shots showing torso and
        clothing rather than headshots.
        """
        bands = {"close": 0, "medium": 0, "wide": 0}
        for fraction in self.face_area_fractions:
            if fraction >= 0.08:
                bands["close"] += 1
            elif fraction >= 0.02:
                bands["medium"] += 1
            else:
                bands["wide"] += 1
        return bands


def find_images(source: Path) -> list[Path]:
    return sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def read_still(path: Path, embedder: DlibEmbedder) -> FaceReading:
    image = np.asarray(Image.open(path).convert("RGB"))
    return embedder.read(image)


def ingest(
    source: Path,
    *,
    persona_id: uuid.UUID,
    kind: str,
    storage: StorageBackend,
    embedder: DlibEmbedder,
    session: Session,
    is_master: bool = True,
) -> IngestReport:
    """Ingest a directory of stills as reference assets of one kind."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}, got {kind!r}")
    if session.get(Persona, persona_id) is None:
        raise ValueError(f"no persona {persona_id}; create the persona row first")

    report = IngestReport(kind=kind)
    for path in find_images(source):
        reading = read_still(path, embedder)
        if reading.outcome is not FaceOutcome.OK or reading.embedding is None:
            report.rejected.append(Rejection(path, reading.outcome, reading.detail))
            continue

        key = key_for(persona_id, "reference", f"{kind}-{path.stem}{path.suffix.lower()}")
        storage.put(key, path.read_bytes(), content_type=_content_type(path))

        asset = ReferenceAsset(
            persona_id=persona_id,
            kind=kind,
            storage_key=key,
            embedding=reading.embedding.as_list(),
            embedding_model=reading.embedding.model,
            embedding_model_version=reading.embedding.model_version,
            is_master=is_master,
        )
        session.add(asset)
        session.flush()

        report.ingested.append(asset.id)
        report.embeddings.append(reading.embedding)
        if reading.face_area_fraction is not None:
            report.face_area_fractions.append(reading.face_area_fraction)

    return report


def centroid(embeddings: Sequence[Embedding]) -> Embedding:
    """The L2-normalised mean descriptor — what the threshold compares against.

    `persona.yaml` records the threshold as "cosine vs the L2-normalised centroid", so
    this is the reference every identity score in the project is measured from. Refuses
    to mix models, for the same reason `cosine` does.
    """
    if not embeddings:
        raise ValueError("a centroid needs at least one embedding")
    models = {(e.model, e.model_version) for e in embeddings}
    if len(models) > 1:
        raise ValueError(f"cannot average vectors from {len(models)} different scorers: {models}")

    stacked = np.asarray([e.vector for e in embeddings], dtype=np.float64)
    mean = stacked.mean(axis=0)
    norm = float(np.linalg.norm(mean))
    first = embeddings[0]
    return Embedding(
        vector=tuple((mean / norm).tolist()), model=first.model, model_version=first.model_version
    )


def similarities(embeddings: Iterable[Embedding], reference: Embedding) -> list[float]:
    return [cosine(embedding, reference) for embedding in embeddings]


def _content_type(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }[path.suffix.lower()]
