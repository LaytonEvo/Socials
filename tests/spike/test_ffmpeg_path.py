"""The real-video path.

Everything else in the suite runs on frame directories, because the fake video
provider emits those and they need no external tools. This module is the only
place a genuine encoded video file goes through the harness, so it is the only
place `FfmpegFrames` and `default_frame_source` are exercised.

Skipped when ffmpeg is absent. That is deliberate rather than lazy: the harness
is meant to be developable without it, and a hard failure here would punish
someone working on scoring who has no interest in video encoding.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

from scripts.spike.calibrate import Calibration
from scripts.spike.config import load_config
from scripts.spike.embed import StubEmbedder, embed_images
from scripts.spike.frames import (
    FfmpegFrames,
    ImageSequenceFrames,
    default_frame_source,
    ffmpeg_available,
)
from scripts.spike.providers import FakeVideoProvider, VideoRequest
from scripts.spike.score import score_clip
from tests.spike.conftest import make_stills

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not on PATH")

NATIVE_FPS = 8
DURATION_S = 5.0


@pytest.fixture
def encoded_clip(tmp_path: Path) -> Path:
    """A real .mp4, encoded from the fake provider's frames."""
    cfg = load_config()
    frames_dir = tmp_path / "frames"
    FakeVideoProvider(
        cfg.provider("video", "fake"), drift_per_second=0.15, native_fps=NATIVE_FPS
    ).generate(VideoRequest(Path("k"), "test", DURATION_S, 3, "r"), frames_dir)

    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-framerate",
            str(NATIVE_FPS),
            "-i",
            str(frames_dir / "frame_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )
    return clip


def test_sampling_rate_is_honoured(encoded_clip: Path, tmp_path: Path):
    """2 fps over a 5-second clip is ten frames, not forty."""
    out = FfmpegFrames().extract(encoded_clip, tmp_path / "sampled", fps=2.0)
    assert len(out) == 10
    assert all(p.exists() and p.stat().st_size > 0 for p in out)


def test_frames_come_back_in_order(encoded_clip: Path, tmp_path: Path):
    out = FfmpegFrames().extract(encoded_clip, tmp_path / "sampled", fps=2.0)
    assert [p.name for p in out] == sorted(p.name for p in out)


def test_a_file_gets_ffmpeg_and_a_directory_gets_the_sequence_reader(
    encoded_clip: Path, tmp_path: Path
):
    assert isinstance(default_frame_source(encoded_clip), FfmpegFrames)
    assert isinstance(default_frame_source(tmp_path), ImageSequenceFrames)


def test_a_real_video_scores_end_to_end(encoded_clip: Path, tmp_path: Path):
    """The whole path on an encoded file rather than a folder of stills."""
    embedder = StubEmbedder()
    master = embed_images(embedder, make_stills(tmp_path / "master", "look-a", 6), label="m")
    calibration = Calibration(
        embedder_key=embedder.info.key(),
        embedder_is_stub=True,
        calibrated_on=dt.date(2026, 9, 22),
        threshold=0.5,
        target_fpr=0.01,
        fpr_at_threshold=0.0,
        tpr_at_threshold=1.0,
        eer_threshold=0.5,
        eer=0.0,
        auc=1.0,
        d_prime=5.0,
        overlap=0.0,
        verdict="EXCELLENT",
    )

    score = score_clip(
        encoded_clip,
        embedder,
        master,
        calibration,
        ref="real-video",
        fps=2.0,
        frames_dir=tmp_path / "extracted",
    )
    assert score.frames_sampled == 10
    assert score.frames_usable == 10
    assert score.identity_score_min is not None
    assert score.identity_score_mean is not None
    # The fixture drifts, so the worst frame must score below the mean.
    assert score.identity_score_min < score.identity_score_mean


def test_missing_video_file_fails_loudly(tmp_path: Path):
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        FfmpegFrames().extract(tmp_path / "nope.mp4", tmp_path / "out", fps=2.0)
