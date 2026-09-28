"""Getting sampled frames out of a clip.

Two sources behind one seam. ``FfmpegFrames`` is what a real run uses;
``ImageSequenceFrames`` reads a directory of stills, which is what the fake
video provider emits and what the tests run against. The seam exists because
ffmpeg is a runtime dependency that should not stop the harness being
developed or tested.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import FfmpegMissing

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class FrameSource(Protocol):
    def extract(self, clip: Path, dest: Path, fps: float) -> list[Path]: ...


@dataclass
class ImageSequenceFrames:
    """Treat a directory of ordered stills as a clip.

    Frames are already at the clip's native rate, so ``fps`` selects a stride
    rather than resampling. ``native_fps`` says what rate the directory is in.
    """

    native_fps: float = 8.0

    def extract(self, clip: Path, dest: Path, fps: float) -> list[Path]:
        clip = Path(clip)
        if not clip.is_dir():
            raise NotADirectoryError(f"{clip} is not a frame directory")
        frames = sorted(p for p in clip.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        if not frames:
            return []
        stride = max(1, round(self.native_fps / fps)) if fps > 0 else 1
        return frames[::stride]


@dataclass
class FfmpegFrames:
    """Sample a real video file at a fixed rate via ffmpeg.

    Covered by tests/spike/test_ffmpeg_path.py, which encodes a real .mp4 and
    runs it through the whole scoring path. Those tests skip themselves when
    ffmpeg is absent, so the harness stays developable without it.
    """

    image_format: str = "png"

    def extract(self, clip: Path, dest: Path, fps: float) -> list[Path]:
        if not ffmpeg_available():
            raise FfmpegMissing(
                "ffmpeg is not on PATH. It is required to sample frames from real "
                "clips; install it, or use ImageSequenceFrames for fixture runs."
            )
        clip = Path(clip)
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        pattern = dest / f"frame_%05d.{self.image_format}"
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(clip),
            "-vf",
            f"fps={fps}",
            str(pattern),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed on {clip}: {result.stderr.strip()}")
        return sorted(dest.glob(f"frame_*.{self.image_format}"))


def default_frame_source(clip: Path) -> FrameSource:
    """Pick a source by what the path is: a directory of stills, or a file."""
    return ImageSequenceFrames() if Path(clip).is_dir() else FfmpegFrames()


def strip_audio(clip: Path) -> bool:
    """Remove a clip's soundtrack in place. True if there was one to remove.

    h3-max invents a soundtrack on every clip and has no flag to stop it, and
    what it invents is speech in an unidentified language (2026-09-28). A clip
    that goes on to the lip-sync stage is fine -- that pass replaces the audio
    and the mouth together -- but a clip that does not is unpublishable as it
    stands, for a reason nothing in the scoring pipeline can see, because
    nothing in the scoring pipeline listens.

    Stream copy, so the video is bit-identical and this costs nothing.
    """
    clip = Path(clip)
    if clip.is_dir():
        return False
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg is not on PATH, and it is what removes a soundtrack. Refusing "
            "rather than passing a clip through unchanged: a clip that silently "
            "keeps its invented audio is the failure this exists to prevent."
        )
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(clip),
        ],
        capture_output=True,
        text=True,
    )
    if "audio" not in probe.stdout:
        return False
    # These clips have no file extension -- the ref IS the filename -- so
    # ffmpeg cannot infer a muxer and has to be told. Ask the file what it is
    # rather than assuming mp4: the container is the provider's choice.
    fmt = (
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name",
                "-of",
                "csv=p=0",
                str(clip),
            ],
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        # ffprobe's CSV quotes any value containing a comma, and format_name
        # usually does: "mov,mp4,m4a,3gp,3g2,mj2". Strip the quote before
        # splitting, or the muxer name arrives as `"mov` and ffmpeg refuses.
        .strip('"')
        .split(",")[0]
    )
    if not fmt:
        raise RuntimeError(f"could not read the container format of {clip}")
    muted = clip.with_name(clip.name + ".muted")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(clip),
            "-c:v",
            "copy",
            "-an",
            "-f",
            fmt,
            "-y",
            str(muted),
        ],
        check=True,
    )
    muted.replace(clip)
    return True
