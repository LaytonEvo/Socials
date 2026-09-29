"""Training set preparation — the first half of task 1.4.

Turns the reference set into an archive a hosted trainer can fetch, and holds back a
slice of it for evaluation.

**The holdout is the part that matters.** Task 1.4's acceptance criteria say "eval
against held-out master images", and the reason is easy to lose: a LoRA scored against
the full master centroid is being scored against images it was trained on, which
measures memorisation rather than likeness. So the holdout is excluded from training AND
from the centroid the evaluation compares to — `app.identity.evaluation` enforces that,
and this module is what makes it possible by keeping the split.

The split is deterministic and stratified by kind. Deterministic so a `lora_version` row
is reproducible from its `dataset_hash`; stratified because a random 10% of 121 stills
can easily take all three body references and leave the holdout unable to say anything
about wider framing.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

#: FLUX trains at 1024px. Larger costs upload and buys nothing; smaller loses detail the
#: face depends on.
TRAIN_EDGE_PX = 1024
TRAIN_JPEG_QUALITY = 92

#: Roughly one in six held back. Enough to say something, few enough that the LoRA still
#: sees the variety it needs.
DEFAULT_HOLDOUT_FRACTION = 0.15


@dataclass(frozen=True)
class Still:
    path: Path
    kind: str

    @property
    def name(self) -> str:
        return f"{self.kind}-{self.path.stem}"


@dataclass
class TrainingSet:
    """A deterministic split of the reference set."""

    trigger_word: str
    train: list[Still] = field(default_factory=list)
    holdout: list[Still] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.train) + len(self.holdout)

    def by_kind(self, stills: Sequence[Still]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for still in stills:
            counts[still.kind] = counts.get(still.kind, 0) + 1
        return counts

    def dataset_hash(self) -> str:
        """Identifies exactly this split, for `lora_version.dataset_hash`.

        Covers the trigger word and both sides of the split, because a version trained
        on the same images with a different holdout is a different version — its
        evaluation numbers are not comparable.
        """
        payload = json.dumps(
            {
                "trigger_word": self.trigger_word,
                "train": sorted(s.path.as_posix() for s in self.train),
                "holdout": sorted(s.path.as_posix() for s in self.holdout),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def collect(roots: dict[str, Path], *, exclude: Sequence[str] = ()) -> list[Still]:
    """Every image under each kind's directory, in a stable order.

    `exclude` takes filenames to leave out. The reference set holds three stills with no
    detectable face — `b1_11`, `b2_04`, `b4_10` — which the spike's own ingest rejected
    and which the centroid is not built from. Training a FACE model on images with no
    face in them adds noise for nothing, so the caller passes them here rather than the
    module guessing.
    """
    suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    skip = set(exclude)
    return [
        Still(path, kind)
        for kind, root in sorted(roots.items())
        for path in sorted(root.iterdir())
        if path.suffix.lower() in suffixes and path.name not in skip
    ]


#: The three stills in `master_v2` with no detectable face. Named rather than detected,
#: because detecting them costs a full pass over the set and the answer never changes —
#: `tests/app/test_master_set.py` fails if the set does.
NO_FACE_STILLS = ("b1_11.png", "b2_04.png", "b4_10.png")


def split(
    stills: Sequence[Still],
    *,
    trigger_word: str,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    seed: str = "persona-studio",
) -> TrainingSet:
    """Split into train and holdout, deterministically and stratified by kind.

    Deterministic by hashing each path with a seed rather than shuffling with a random
    number generator: the same inputs give the same split on any machine and any Python
    version, which a seeded RNG does not reliably promise across releases.
    """
    if not 0.0 < holdout_fraction < 1.0:
        raise ValueError(f"holdout_fraction must be between 0 and 1, got {holdout_fraction}")

    result = TrainingSet(trigger_word=trigger_word)
    by_kind: dict[str, list[Still]] = {}
    for still in stills:
        by_kind.setdefault(still.kind, []).append(still)

    for _kind, members in sorted(by_kind.items()):
        ranked = sorted(
            members,
            key=lambda s: hashlib.sha256(f"{seed}:{s.path.as_posix()}".encode()).hexdigest(),
        )
        # At least one held back per kind where the kind has more than one member, so
        # every kind can say something at evaluation. A kind of one contributes nothing
        # to a holdout and is better spent training.
        wanted = round(len(ranked) * holdout_fraction)
        take = min(max(wanted, 1 if len(ranked) > 1 else 0), len(ranked) - 1)
        result.holdout.extend(ranked[:take])
        result.train.extend(ranked[take:])

    result.train.sort(key=lambda s: s.path.as_posix())
    result.holdout.sort(key=lambda s: s.path.as_posix())
    return result


def build_archive(stills: Sequence[Still], *, trigger_word: str) -> bytes:
    """A zip of resized JPEGs plus a caption per image, which is what trainers expect.

    Captions carry the trigger word so the LoRA binds to it rather than to whatever the
    auto-captioner infers. Each also names the kind, so an outfit still is not read as a
    statement about her face.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for still in stills:
            image = Image.open(still.path).convert("RGB")
            image.thumbnail((TRAIN_EDGE_PX, TRAIN_EDGE_PX), Image.Resampling.LANCZOS)
            encoded = io.BytesIO()
            image.save(encoded, "JPEG", quality=TRAIN_JPEG_QUALITY, optimize=True)
            archive.writestr(f"{still.name}.jpg", encoded.getvalue())
            archive.writestr(f"{still.name}.txt", caption_for(still, trigger_word))
    return buffer.getvalue()


def caption_for(still: Still, trigger_word: str) -> str:
    descriptions = {
        "master_v2": f"a photo of {trigger_word}, a young woman",
        "face": f"a photo of {trigger_word}, a young woman",
        "outfit": f"a photo of {trigger_word}, a young woman wearing golf clothing",
        "lighting": f"a photo of {trigger_word}, a young woman, natural lighting",
        "body": f"a photo of {trigger_word}, a young woman, full body",
    }
    return descriptions.get(still.kind, f"a photo of {trigger_word}")
