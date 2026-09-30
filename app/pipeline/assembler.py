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
from typing import Any, Final, Literal

from app.pipeline.errors import AssemblyFailed, FfmpegMissing

#: What to do with the audio the source clips arrived with.
#:
#: **The default is silence, and that is a deliberate refusal.** The video model
#: generates a soundtrack unconditionally — there is no flag to turn it off — and it
#: speaks an unidentified language nobody chose. `config/providers.yaml` has recorded
#: this since 2026-09-28, after 61 clips came back that way.
#:
#: Carrying that into an assembled piece ships audio no human selected, in a language
#: nobody can read, under a persona who is supposed to be openly and accountably
#: synthetic. Including it requires saying so; leaving it out does not.
AudioPolicy = Literal["silent", "keep_source"]
DEFAULT_AUDIO: Final[AudioPolicy] = "silent"


def has_audio(video: Path) -> bool:
    """Whether a file carries an audio stream at all."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


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
    #: Whether THIS cut's own audio belongs in the render.
    #:
    #: Explicit, never inferred from whether the file has an audio stream. Every clip
    #: from the video model has one — an unconditional invented soundtrack in no
    #: identifiable language — so "has audio" is true of exactly the takes whose audio
    #: must be discarded. Only a lip-synced take, carrying the voice its mouth was
    #: generated against, is worth keeping.
    use_audio: bool = False


@dataclass
class EditList:
    """The cuts in order, and enough provenance to reconstruct the render."""

    cuts: list[Cut] = field(default_factory=list)
    aspect: str = "9:16"
    audio: AudioPolicy = DEFAULT_AUDIO

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
        return {
            "aspect": self.aspect,
            "duration_s": round(self.duration_s, 3),
            "audio": self.audio,
            "cuts": entries,
        }


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


def edit_list(
    clips: list[tuple[Path, str, str]] | list[tuple[Path, str, str, bool]],
    *,
    aspect: str = "9:16",
    audio: AudioPolicy = DEFAULT_AUDIO,
) -> EditList:
    """Build an edit list from (path, source_id, label) triples, in order.

    `audio` defaults to silence. Keeping the source soundtrack is a choice a caller has
    to make out loud, because on this model it is not a recording of anything — see
    `AudioPolicy`.
    """
    if not clips:
        raise AssemblyFailed("an edit list needs at least one cut")
    cuts = []
    for entry in clips:
        path, source_id, label = entry[0], entry[1], entry[2]
        use_audio = bool(entry[3]) if len(entry) > 3 else False
        if not path.is_file():
            raise AssemblyFailed(f"cut source is missing: {path}")
        cuts.append(
            Cut(
                path=path,
                source_id=source_id,
                duration_s=duration_of(path),
                label=label,
                use_audio=use_audio,
            )
        )
    return EditList(cuts=cuts, aspect=aspect, audio=audio)


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

    if edl.audio == "keep_source":
        # Per cut, and by the cut's own `use_audio` flag rather than by looking for an
        # audio stream. Every clip from the video model HAS one — an unconditional
        # invented soundtrack — so detecting a stream selects precisely the takes whose
        # audio must go. Keeping it put the loudest thing in the first assembled piece
        # under a b-roll shot.
        #
        # A lip-synced take is the case worth keeping: it arrives carrying the audio its
        # mouth was generated against, and a separately-laid copy drifts because the
        # sync stretches time slightly (5.208s out for 5.184s in).
        #
        # Cuts without it get generated silence of their own length rather than being
        # skipped, so the concat receives one audio stream per cut and the picture does
        # not slide against the sound.
        parts: list[str] = []
        pairs: list[str] = []
        for i, cut in enumerate(edl.cuts):
            if cut.use_audio and has_audio(cut.path):
                parts.append(f"[{i}:a:0]aresample=44100,asetpts=N/SR/TB[a{i}];")
            else:
                parts.append(
                    f"anullsrc=r=44100:cl=stereo,atrim=duration={cut.duration_s:.3f}[a{i}];"
                )
            pairs.append(f"[{i}:v:0][a{i}]")
        filters = "".join(parts) + "".join(pairs) + f"concat=n={len(edl.cuts)}:v=1:a=1[v][a]"
        args += [
            "-filter_complex",
            filters,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
        ]
    else:
        # Video only. Not "mute the track" — the track is not carried at all, so there
        # is nothing for anything downstream to un-mute by accident.
        streams = "".join(f"[{i}:v:0]" for i in range(len(edl.cuts)))
        args += [
            "-filter_complex",
            f"{streams}concat=n={len(edl.cuts)}:v=1:a=0[v]",
            "-map",
            "[v]",
            "-an",
        ]

    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", str(dest)]

    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not dest.is_file():
        raise AssemblyFailed(f"assembly failed: {result.stderr.strip()[:500]}")

    dest.with_suffix(".edl.json").write_text(json.dumps(edl.to_json(), indent=2) + "\n")
    return RoughCut(path=dest, edl=edl)
