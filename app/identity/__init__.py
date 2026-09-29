"""Master reference set, LoRA training, and face embeddings.

A threshold is calibrated against one embedding model at one version, and changing
either silently invalidates every stored vector — the numbers still compare, they just
stop meaning anything. Re-calibration is therefore forced by the schema (amendment A3),
not remembered.

ADR 0008 adds that the same is true of her *face*: the master set, the centroid, the
calibration and every measured pass rate are defined against these stills.

LoRA base model weights must permit commercial use, and the licence is recorded in
`lora_version.base_model_licence` (task 1.4).
"""

from __future__ import annotations

from .embedder import (
    MIN_FACE_PIXELS,
    DlibEmbedder,
    EmbedderNotConfigured,
    Embedding,
    FaceOutcome,
    FaceReading,
    WeightsMismatch,
    cosine,
    sha256_of,
)
from .master_set import (
    KINDS,
    IngestReport,
    Rejection,
    centroid,
    find_images,
    ingest,
    read_still,
    similarities,
)

__all__ = [
    "KINDS",
    "MIN_FACE_PIXELS",
    "DlibEmbedder",
    "EmbedderNotConfigured",
    "Embedding",
    "FaceOutcome",
    "FaceReading",
    "IngestReport",
    "Rejection",
    "WeightsMismatch",
    "centroid",
    "cosine",
    "find_images",
    "ingest",
    "read_still",
    "sha256_of",
    "similarities",
]
