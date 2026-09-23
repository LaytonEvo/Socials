"""Face embedding: the measuring instrument for the whole spike.

The real backend is blocked on docs/decisions/0002-face-embedding-model-licence.md.
What lives here is the seam it plugs into, plus a deterministic stub so the rest
of the harness can be built and validated offline.

Two design points, both from BUILD_ORDER:

* **No-face and multi-face frames are never silently dropped** (task S0.2
  acceptance criteria). They are counted and carried through to the report. A
  clip where the model lost the face entirely for 2 seconds is a finding, and a
  scorer that quietly skips those frames would report it as a clean pass.
* **Every vector is stamped with the model and version that produced it**
  (amendment A3), because a threshold is valid for exactly one of them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from .config import EmbedderConfig
from .errors import EmbedderNotConfigured

NO_FACE = "no_face"
MULTI_FACE = "multi_face"
OK = "ok"


@dataclass(frozen=True)
class EmbedderInfo:
    """Identity of the scorer. Stamped onto every measurement it produces."""

    backend: str
    model: str
    version: str
    dim: int
    licence: str | None = None

    @property
    def is_stub(self) -> bool:
        return self.backend == "stub"

    def key(self) -> str:
        return f"{self.backend}:{self.model}:{self.version}:d{self.dim}"


@dataclass
class FrameEmbedding:
    """One sampled frame. ``vector`` is set only when exactly one face was found."""

    index: int
    timestamp_s: float
    status: str  # OK | NO_FACE | MULTI_FACE
    faces: int
    vector: np.ndarray | None = None
    source: str | None = None

    @property
    def usable(self) -> bool:
        return self.status == OK and self.vector is not None


@dataclass
class EmbeddingSet:
    """Embeddings for one clip or one still set, with the exceptions kept."""

    frames: list[FrameEmbedding]
    info: EmbedderInfo
    label: str = ""

    @property
    def usable(self) -> list[FrameEmbedding]:
        return [f for f in self.frames if f.usable]

    @property
    def vectors(self) -> np.ndarray:
        vecs = [f.vector for f in self.usable if f.vector is not None]
        if not vecs:
            return np.zeros((0, self.info.dim), dtype=np.float32)
        return np.vstack(vecs).astype(np.float32)

    def counts(self) -> dict[str, int]:
        return {
            "frames": len(self.frames),
            "usable": len(self.usable),
            NO_FACE: sum(1 for f in self.frames if f.status == NO_FACE),
            MULTI_FACE: sum(1 for f in self.frames if f.status == MULTI_FACE),
        }

    def centroid(self) -> np.ndarray | None:
        """L2-normalised mean vector, or None when nothing was usable."""
        vecs = self.vectors
        if len(vecs) == 0:
            return None
        return l2_normalise(vecs.mean(axis=0))


def l2_normalise(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec.astype(np.float32)
    return (vec / norm).astype(np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors that are already L2-normalised."""
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


class Embedder(Protocol):
    info: EmbedderInfo

    def embed_image(self, path: Path) -> FrameEmbedding: ...


_REGISTRY: dict[str, Callable[[EmbedderConfig], Embedder]] = {}


def register_embedder(name: str, factory: Callable[[EmbedderConfig], Embedder]) -> None:
    _REGISTRY[name] = factory


def load_embedder(cfg: EmbedderConfig) -> Embedder:
    cfg.require_usable()
    assert cfg.backend is not None
    try:
        factory = _REGISTRY[cfg.backend]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise EmbedderNotConfigured(
            f"No embedder backend registered under {cfg.backend!r}. Registered: {known}. "
            f"A real backend is added by implementing the Embedder protocol and calling "
            f"register_embedder(); see docs/decisions/0002-face-embedding-model-licence.md "
            f"for which model to implement and why the choice is blocking."
        ) from None
    return factory(cfg)


# --------------------------------------------------------------------------
# Stub backend
# --------------------------------------------------------------------------


@dataclass
class StubEmbedder:
    """Deterministic pixel-statistics embedder. **Not a face recognition model.**

    It exists so the harness -- calibration statistics, scoring, contact sheets,
    reporting -- can be developed and tested without a licensed model and
    without network access. It has no face detector, so it simulates detection
    outcomes from filename markers: a file containing ``__noface`` reports zero
    faces and ``__multiface`` reports two.

    Any run using this backend is marked as stub data and cannot produce a Gate
    A report without an explicit override.
    """

    info: EmbedderInfo = field(
        default_factory=lambda: EmbedderInfo(
            backend="stub",
            model="pixel-stats",
            version="0",
            dim=256,
            licence="n/a (not a model)",
        )
    )
    grid: int = 16

    def embed_image(self, path: Path) -> FrameEmbedding:
        name = Path(path).name
        if "__noface" in name:
            return FrameEmbedding(0, 0.0, NO_FACE, faces=0, source=str(path))
        if "__multiface" in name:
            return FrameEmbedding(0, 0.0, MULTI_FACE, faces=2, source=str(path))
        vec = self._vector(path)
        return FrameEmbedding(0, 0.0, OK, faces=1, vector=vec, source=str(path))

    def _vector(self, path: Path) -> np.ndarray:
        with Image.open(path) as img:
            small = img.convert("L").resize((self.grid, self.grid), Image.Resampling.BILINEAR)
            arr = np.asarray(small, dtype=np.float32).reshape(-1)
        arr = arr - arr.mean()
        return l2_normalise(arr)


register_embedder("stub", lambda cfg: StubEmbedder())


# --------------------------------------------------------------------------
# Batch helpers
# --------------------------------------------------------------------------


def embed_images(
    embedder: Embedder,
    paths: Iterable[Path],
    label: str = "",
    fps: float | None = None,
) -> EmbeddingSet:
    """Embed a sequence of stills or extracted frames, preserving order."""
    frames: list[FrameEmbedding] = []
    for i, path in enumerate(paths):
        fe = embedder.embed_image(Path(path))
        fe.index = i
        fe.timestamp_s = (i / fps) if fps else 0.0
        frames.append(fe)
    return EmbeddingSet(frames=frames, info=embedder.info, label=label)


def pairwise_similarities(vectors: Sequence[np.ndarray]) -> list[float]:
    """Every unordered pair within one set. Self-pairs excluded."""
    out: list[float] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            out.append(cosine(vectors[i], vectors[j]))
    return out


def cross_similarities(a: Sequence[np.ndarray], b: Sequence[np.ndarray]) -> list[float]:
    """Every pair across two sets."""
    return [cosine(x, y) for x in a for y in b]


def leave_one_out_centroid_similarities(vectors: Sequence[np.ndarray]) -> list[float]:
    """Each vector against the centroid of *the others*.

    This is the positive distribution, and it has to be built this way rather
    than pairwise, because `score.py` compares every frame to the master
    centroid. A threshold is only meaningful in the space it was measured in,
    and centroid similarity is systematically higher than pairwise similarity:
    averaging cancels the noise that a single other image still carries. Mixing
    the two makes the threshold too lenient by exactly that gap.

    Leave-one-out, because a vector included in its own reference centroid is
    partly being compared to itself, which inflates the positives and would
    flatter the instrument for the same reason.
    """
    if len(vectors) < 2:
        return []
    stacked = np.stack([np.asarray(v, dtype=np.float64) for v in vectors])
    total = stacked.sum(axis=0)
    n = len(stacked)
    return [
        cosine(
            l2_normalise(stacked[i].astype(np.float32)),
            l2_normalise((total - stacked[i]) / (n - 1)),
        )
        for i in range(n)
    ]


def centroid_similarities(
    vectors: Sequence[np.ndarray], centroid: np.ndarray | None
) -> list[float]:
    """Each vector against a fixed centroid — the negative distribution.

    No leave-one-out here: a control image never contributed to the master
    centroid in the first place.
    """
    if centroid is None:
        return []
    return [cosine(v, centroid) for v in vectors]
