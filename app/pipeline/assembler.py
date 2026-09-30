"""Task 3.8 — build an edit list from accepted takes and render it.

The output is a `RoughCut`, deliberately not a finished render. It carries no overlay,
no manifest and no captions, and the type says so: `apply_disclosure` is what turns one
into a `FinalRender`, and only a `FinalRender` may be signed, exported or published.

The edit list is stored as data (`render.edl_json`) rather than implied by the order
files happened to sit in a directory, so a render can be explained after the fact —
which take, from which generation, at what offset.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.pipeline.errors import AssemblyFailed, FfmpegMissing


@dataclass(frozen=True)
class Cut:
    """One clip's place in the edit.

    `source_id` is free-form on purpose: during the spike it names a run directory, and
    in production it is a `generation.id`. What matters is that the rendered file can be
    traced back to the thing that produced it.
    """

    path: Path
    source_id: str
    duration_s: float
    label: str = ""


@dataclass
class EditList:
    """The cuts in order, and enough provenance to reconstruct the render."""

    cuts: list[Cut] = field(default_factory=list)
    aspect: str = "9:16"

    @property
    def duration_s(self) -> float:
        return sum(c.duration_s for c in self.cuts)

    def to_json(self) -> dict[str, Any]:
        """What goes in `render.edl_json`. Offsets are computed, never stored twice."""
        offset = 0.0
        entries: list[dict[str, Any]] = []
        for cut in self.cuts:
            entry = asdict(cut) | {"path": str(cut.path), "offset_s": round(offset, 3)}
            entries.append(entry)
            offset += cut.duration_s
        return {"aspect": self.aspect, "duration_s": round(self.duration_s, 3), "cuts": entries}


@dataclass(frozen=True)
class RoughCut:
    """An assembled video with no overlay, no captions and no manifest.

    A deliberately separate type from `FinalRender`. Nothing downstream accepts one,
    so a rough cut cannot be mistaken for something publishable by a caller in a hurry.
    """

    path: Path
    edl: EditList


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise FfmpegMissing("ffmpeg is not on PATH; assembly cannot run")


def duration_of(video: Path) -> float:
    """Clip length in seconds, read from the file rather than assumed from config."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssemblyFailed(f"could not read duration of {video}: {result.stderr.strip()}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise AssemblyFailed(f"unreadable duration for {video}: {result.stdout!r}") from exc


def edit_list(clips: list[tuple[Path, str, str]], *, aspect: str = "9:16") -> EditList:
    """Build an edit list from (path, source_id, label) triples, in order."""
    if not clips:
        raise AssemblyFailed("an edit list needs at least one cut")
    cuts = []
    for path, source_id, label in clips:
        if not path.is_file():
            raise AssemblyFailed(f"cut source is missing: {path}")
        cuts.append(Cut(path=path, source_id=source_id, duration_s=duration_of(path), label=label))
    return EditList(cuts=cuts, aspect=aspect)


def assemble(edl: EditList, dest: Path) -> RoughCut:
    """Render the edit list to a single file.

    Re-encodes rather than stream-copying. Concatenating clips from one model at one
    resolution would usually copy cleanly, but a silent failure here produces a file
    that plays for the first cut and then stalls, which is worse than a slower render.
    """
    _require_ffmpeg()
    if not edl.cuts:
        raise AssemblyFailed("nothing to assemble")
    dest.parent.mkdir(parents=True, exist_ok=True)

    args: list[str] = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error"]
    for cut in edl.cuts:
        args += ["-i", str(cut.path)]
    streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(edl.cuts)))
    args += [
        "-filter_complex",
        f"{streams}concat=n={len(edl.cuts)}:v=1:a=1[v][a]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(dest),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not dest.is_file():
        raise AssemblyFailed(f"assembly failed: {result.stderr.strip()[:500]}")

    dest.with_suffix(".edl.json").write_text(json.dumps(edl.to_json(), indent=2) + "\n")
    return RoughCut(path=dest, edl=edl)
