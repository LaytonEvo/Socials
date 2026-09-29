"""Face embeddings. The ONLY module that imports dlib.

Written against the app's own needs rather than promoted from `scripts/spike/`:
BUILD_ORDER Section 3 says no spike code moves into `app/` without being rewritten,
and the spike's embedder carries a bake-off between two candidate backends that was
settled in ADR 0004 and is dead weight here.

Two properties this enforces that the spike learned the expensive way.

**The weights are verified before use.** A threshold is valid for one model at one
version (amendment A3), and dlib's models carry no semantic version — so the version
is the SHA-256 of the weights file, checked on load. A different file is a different
scorer, and every stored vector and the calibrated threshold would silently stop
meaning anything.

**Absence of a face is not a low score.** It is missing evidence, and conflating the
two is what made the spike's identity gate agree with the owner once in three. A
frame with no face, or more than one, is reported as such and never scored.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np

from app.config import ProvidersConfig


class FaceOutcome(StrEnum):
    OK = "ok"
    #: No face found. Missing evidence, not a failure to resemble her.
    NO_FACE = "no_face"
    #: More than one. Which one is she? Unanswerable, so not scored.
    MULTI_FACE = "multi_face"
    #: A crop too small for the model input to mean anything.
    TOO_SMALL = "too_small"


#: Below this, a face crop has too few pixels for the descriptor to be meaningful.
#: Carried across from the spike, which set it against measured behaviour.
MIN_FACE_PIXELS = 80


class EmbedderNotConfigured(RuntimeError):
    """The scorer cannot run, and must not silently fall back to another one."""


class WeightsMismatch(EmbedderNotConfigured):
    """The weights on disk are not the ones the config pins.

    Fatal rather than a warning. Scoring against different weights than the threshold
    was calibrated on produces numbers that still compare and no longer mean anything,
    which is the worst kind of wrong.
    """


@dataclass(frozen=True)
class Embedding:
    """One face descriptor, with the provenance that makes it interpretable."""

    vector: tuple[float, ...]
    model: str
    model_version: str

    def as_list(self) -> list[float]:
        return list(self.vector)


@dataclass(frozen=True)
class FaceReading:
    """What was found in one image. `embedding` is None unless the outcome is OK."""

    outcome: FaceOutcome
    embedding: Embedding | None = None
    faces_found: int = 0
    #: Face bounding-box area as a fraction of the frame. A proxy for framing, and
    #: the measurement that showed the master set is medium-distance rather than a
    #: pile of headshots.
    face_area_fraction: float | None = None
    detail: str | None = None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class DlibEmbedder:
    """dlib's ResNet face descriptor, 128-d, scored on the L2-normalised vector.

    Licensed public domain by the author with a FaceScrub training-data caveat
    (ADR 0004). That caveat blocks *publication*, not measurement, and the config
    carries a separate flag for it.
    """

    def __init__(self, providers: ProvidersConfig, *, root: Path | None = None) -> None:
        settings = providers.embedder
        base = root or Path.cwd()

        for field in ("model", "version", "dim", "recognition_model", "shape_predictor"):
            if getattr(settings, field) is None:
                raise EmbedderNotConfigured(
                    f"embedder.{field} is not set. The model, its version, the dimension "
                    f"and both weight paths must all be pinned, because a calibrated "
                    f"threshold is valid for exactly one of them (amendment A3)."
                )

        assert settings.recognition_model is not None
        assert settings.shape_predictor is not None
        self._recognition_path = base / settings.recognition_model
        self._predictor_path = base / settings.shape_predictor
        for path in (self._recognition_path, self._predictor_path):
            if not path.is_file():
                raise EmbedderNotConfigured(
                    f"{path} is missing. Fetch the weights rather than letting the "
                    f"scorer fall back to a different model: "
                    f"`python -m scripts.spike.cli fetch-models --backend dlib`."
                )

        assert settings.version is not None
        actual = sha256_of(self._recognition_path)
        if actual != settings.version:
            raise WeightsMismatch(
                f"{self._recognition_path} has sha256 {actual}, but config pins "
                f"{settings.version}. These are different weights. Every vector stored "
                f"under the pinned version, and the threshold calibrated against them, "
                f"would stop meaning anything — so this refuses rather than warns."
            )

        self.model = settings.model
        self.model_version = settings.version
        self.dim = settings.dim

        import dlib

        self._detector = dlib.get_frontal_face_detector()
        self._predictor = dlib.shape_predictor(str(self._predictor_path))
        self._recognizer = dlib.face_recognition_model_v1(str(self._recognition_path))

    def read(self, image: np.ndarray, *, jitter: int = 1) -> FaceReading:
        """Find exactly one face and describe it, or explain why not."""
        height, width = image.shape[:2]
        faces = self._detector(image, 1)

        if not faces:
            return FaceReading(FaceOutcome.NO_FACE, faces_found=0)
        if len(faces) > 1:
            return FaceReading(
                FaceOutcome.MULTI_FACE,
                faces_found=len(faces),
                detail=f"{len(faces)} faces; which one is she is not answerable",
            )

        box = faces[0]
        if min(box.width(), box.height()) < MIN_FACE_PIXELS:
            return FaceReading(
                FaceOutcome.TOO_SMALL,
                faces_found=1,
                detail=f"{box.width()}x{box.height()} is under {MIN_FACE_PIXELS}px",
            )

        shape = self._predictor(image, box)
        descriptor = np.asarray(
            self._recognizer.compute_face_descriptor(image, shape, jitter), dtype=np.float64
        )
        norm = float(np.linalg.norm(descriptor))
        if norm == 0.0:  # pragma: no cover - defensive
            return FaceReading(FaceOutcome.NO_FACE, faces_found=1, detail="zero-norm descriptor")

        assert self.model is not None and self.model_version is not None
        return FaceReading(
            FaceOutcome.OK,
            embedding=Embedding(
                vector=tuple((descriptor / norm).tolist()),
                model=self.model,
                model_version=self.model_version,
            ),
            faces_found=1,
            face_area_fraction=(box.width() * box.height()) / float(width * height),
        )


def cosine(left: Embedding, right: Embedding) -> float:
    """Similarity between two L2-normalised descriptors.

    Refuses to compare across models or versions. The numbers would still produce a
    float, which is exactly the problem: nothing downstream could tell that the
    comparison was meaningless.
    """
    if (left.model, left.model_version) != (right.model, right.model_version):
        raise WeightsMismatch(
            f"cannot compare a vector from {left.model}@{left.model_version[:12]} with one "
            f"from {right.model}@{right.model_version[:12]}. A similarity across models is "
            f"a number with no meaning, and nothing downstream could tell."
        )
    return float(np.dot(np.asarray(left.vector), np.asarray(right.vector)))
