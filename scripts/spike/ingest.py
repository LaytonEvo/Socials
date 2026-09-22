"""Validating a folder of stills before it becomes a master or control set.

Task S0.1. The point is to fail early and legibly. Calibration on a set the
detector cannot read produces either a crash or, worse, a confident threshold
computed from three usable images — and by the time that shows up in a Gate A
report it looks like a finding about the persona rather than a problem with the
input.

So: run the detector over every candidate image first, say exactly which ones
are unusable and why, and copy only the good ones into the run.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .embed import MULTI_FACE, NO_FACE, Embedder

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

#: Below this, a face crop has too few pixels for a 224px model input to mean
#: much. A warning rather than a rejection — it is a judgement, not a rule.
MIN_EDGE_PX = 256

#: Calibration quality depends on pair counts, which grow quadratically. Ten
#: master images give 45 same-face pairs; the guide in calibrate.py is 50.
RECOMMENDED_MASTER = 12
RECOMMENDED_CONTROL = 16


@dataclass
class Candidate:
    path: Path
    status: str  # ok | no_face | multi_face | unreadable | too_small
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.status == "ok"


@dataclass
class IngestReport:
    which: str
    candidates: list[Candidate] = field(default_factory=list)
    copied: list[Path] = field(default_factory=list)

    @property
    def usable(self) -> list[Candidate]:
        return [c for c in self.candidates if c.usable]

    def count(self, status: str) -> int:
        return sum(1 for c in self.candidates if c.status == status)

    @property
    def recommended(self) -> int:
        return RECOMMENDED_MASTER if self.which == "master" else RECOMMENDED_CONTROL

    @property
    def enough(self) -> bool:
        return len(self.usable) >= self.recommended


def find_images(source: Path) -> list[Path]:
    return sorted(p for p in Path(source).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def inspect(path: Path, embedder: Embedder) -> Candidate:
    try:
        with Image.open(path) as img:
            width, height = img.size
    except Exception as exc:
        return Candidate(path, "unreadable", f"{type(exc).__name__}: {exc}")

    frame = embedder.embed_image(path)
    if frame.status == NO_FACE:
        return Candidate(path, "no_face", "no face detected")
    if frame.status == MULTI_FACE:
        return Candidate(path, "multi_face", f"{frame.faces} faces detected")
    if min(width, height) < MIN_EDGE_PX:
        return Candidate(path, "too_small", f"{width}x{height}, below {MIN_EDGE_PX}px")
    return Candidate(path, "ok", f"{width}x{height}")


def ingest(
    source: Path, dest: Path, which: str, embedder: Embedder, copy: bool = True
) -> IngestReport:
    report = IngestReport(which=which)
    for path in find_images(source):
        report.candidates.append(inspect(path, embedder))

    if copy:
        dest.mkdir(parents=True, exist_ok=True)
        for i, candidate in enumerate(report.usable):
            target = dest / f"{which}_{i:03d}{candidate.path.suffix.lower()}"
            shutil.copy2(candidate.path, target)
            report.copied.append(target)
    return report


def format_report(report: IngestReport, dest: Path) -> str:
    lines = [f"\n{report.which} set: {len(report.candidates)} candidate images", ""]
    for candidate in report.candidates:
        mark = "ok  " if candidate.usable else "SKIP"
        lines.append(f"  [{mark}] {candidate.path.name}  —  {candidate.detail}")

    counts = {
        "no face detected": report.count("no_face"),
        "more than one face": report.count("multi_face"),
        "too small": report.count("too_small"),
        "unreadable": report.count("unreadable"),
    }
    rejected = {k: v for k, v in counts.items() if v}
    lines += ["", f"  usable: {len(report.usable)} of {len(report.candidates)}"]
    for reason, n in rejected.items():
        lines.append(f"  rejected: {n} — {reason}")

    if report.copied:
        lines += ["", f"  copied {len(report.copied)} into {dest}"]

    lines += [""]
    if not report.usable:
        lines += [
            "  NOTHING USABLE. The detector found no single-face image in that folder.",
            "  Check they are photographs of one person, reasonably close-framed, and",
            "  that the detector is configured (embedder.backends.<name>.detector_model).",
        ]
    elif not report.enough:
        lines += [
            f"  THIN. {len(report.usable)} usable, {report.recommended} recommended for the",
            f"  {report.which} set. Calibration works on fewer, but the statistics get",
            "  noisy fast — same-face pairs grow with the square of the count, and the",
            "  report will flag a small sample rather than quietly trusting it.",
        ]
    else:
        lines += [f"  READY — {len(report.usable)} usable images is enough to calibrate on."]
    return "\n".join(lines) + "\n"
