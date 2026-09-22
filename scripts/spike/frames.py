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

    NOTE: unexercised in the container this harness was written in -- ffmpeg was
    not installed there. Run `make check` on a machine with ffmpeg on PATH
    before trusting it against real clips.
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
