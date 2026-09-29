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

from .dataset import (
    DEFAULT_HOLDOUT_FRACTION,
    NO_FACE_STILLS,
    TRAIN_EDGE_PX,
    Still,
    TrainingSet,
    build_archive,
    caption_for,
    collect,
    split,
)
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
from .evaluation import (
    MIN_HOLDOUT,
    Evaluation,
    HoldoutTooSmall,
    evaluate,
    holdout_reference,
    sanity_check,
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
from .training import (
    FakeLoraTrainer,
    FalLoraTrainer,
    LicenceViolation,
    LoraArtefact,
    LoraTrainer,
    TrainingRequest,
)

__all__ = [
    "DEFAULT_HOLDOUT_FRACTION",
    "KINDS",
    "MIN_FACE_PIXELS",
    "MIN_HOLDOUT",
    "NO_FACE_STILLS",
    "TRAIN_EDGE_PX",
    "DlibEmbedder",
    "EmbedderNotConfigured",
    "Embedding",
    "Evaluation",
    "FaceOutcome",
    "FaceReading",
    "FakeLoraTrainer",
    "FalLoraTrainer",
    "HoldoutTooSmall",
    "IngestReport",
    "LicenceViolation",
    "LoraArtefact",
    "LoraTrainer",
    "Rejection",
    "Still",
    "TrainingRequest",
    "TrainingSet",
    "WeightsMismatch",
    "build_archive",
    "caption_for",
    "centroid",
    "collect",
    "cosine",
    "evaluate",
    "find_images",
    "holdout_reference",
    "ingest",
    "read_still",
    "sanity_check",
    "sha256_of",
    "similarities",
    "split",
]
