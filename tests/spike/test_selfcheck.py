"""The embedder self-check.

Its job is to answer "does the scorer work on this machine?" before anyone
spends money, and — just as important — to refuse to be mistaken for evidence
that the scorer is good enough to gate takes on.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scripts.spike.embed import NO_FACE, EmbedderInfo, FrameEmbedding, StubEmbedder
from scripts.spike.errors import SpikeError
from scripts.spike.selfcheck import (
    CheckResult,
    format_result,
    run_check,
    sample_images_from,
)


def _steps(result: CheckResult) -> dict[str, bool]:
    return {s.name: s.ok for s in result.steps}


def test_stub_passes_every_step(tmp_path):
    result = run_check(StubEmbedder(), tmp_path, expected_dim=256)
    assert result.ok
    assert _steps(result)["embedding dimension matches config"]
    assert _steps(result)["same image twice gives the same vector"]
    assert _steps(result)["embedding is normalised"]


def test_stub_is_flagged_as_proving_nothing(tmp_path):
    result = run_check(StubEmbedder(), tmp_path, expected_dim=256)
    assert any("prove nothing about the real scorer" in n for n in result.notes)


def test_discrimination_probe_detects_signal(tmp_path):
    """Variations of one identity must score closer than two identities.

    A backend that returned a constant vector would pass every other step.
    """
    result = run_check(StubEmbedder(), tmp_path, expected_dim=256)
    assert _steps(result)["variations of one identity score closer than two identities"]
    assert np.mean(result.same_identity) > np.mean(result.different_identity)


def test_dimension_mismatch_is_caught(tmp_path):
    """A silent mismatch invalidates any threshold calibrated against it."""
    result = run_check(StubEmbedder(), tmp_path, expected_dim=512)
    assert not result.ok
    assert _steps(result)["embedding dimension matches config"] is False


def test_a_model_that_cannot_load_is_reported_not_raised(tmp_path):
    """The whole point is a readable answer, not a stack trace."""

    class Broken:
        info = EmbedderInfo("broken", "m", "1", 768)

        def embed_image(self, path: Path) -> FrameEmbedding:
            raise OSError("Can't load image processor for 'facebook/dinov2-base'")

    result = run_check(Broken(), tmp_path, expected_dim=768)
    assert not result.ok
    step = next(s for s in result.steps if s.name == "model loads and runs")
    assert "OSError" in step.detail
    assert "dinov2" in step.detail


def test_non_deterministic_embedder_is_caught(tmp_path):
    """A scorer that drifts between runs cannot support a provenance record."""
    from scripts.spike.embed import l2_normalise

    class Drifting(StubEmbedder):
        _n = 0

        def embed_image(self, path: Path) -> FrameEmbedding:
            Drifting._n += 1
            vec = np.zeros(256, dtype=np.float32)
            vec[Drifting._n % 256] = 1.0
            return FrameEmbedding(0, 0.0, "ok", faces=1, vector=l2_normalise(vec))

    result = run_check(Drifting(), tmp_path, expected_dim=256)
    assert _steps(result)["same image twice gives the same vector"] is False


def test_no_face_gives_actionable_advice(tmp_path):
    class Blind:
        info = EmbedderInfo("blind", "m", "1", 768)

        def embed_image(self, path: Path) -> FrameEmbedding:
            return FrameEmbedding(0, 0.0, NO_FACE, faces=0)

    result = run_check(Blind(), tmp_path, expected_dim=768)
    assert not result.ok
    step = next(s for s in result.steps if "face found" in s.name)
    assert "whole-image" in step.detail


def test_timing_is_translated_into_what_a_real_run_costs(tmp_path):
    result = run_check(StubEmbedder(), tmp_path, expected_dim=256, clips=24, fps=2.0, clip_s=5.0)
    note = next(n for n in result.notes if "per embedding" in n)
    assert "240 embeddings" in note  # 2fps x 5s x 24 clips


def test_passing_output_still_refuses_to_be_evidence(tmp_path):
    result = run_check(StubEmbedder(), tmp_path, expected_dim=256)
    text = format_result(result, "stub")
    assert "PASSED" in text
    assert "NOT evidence" in text
    assert "Only calibration" in text


def test_failing_output_points_at_the_failures(tmp_path):
    result = run_check(StubEmbedder(), tmp_path, expected_dim=999)
    text = format_result(result, "stub")
    assert "FAILED" in text
    assert "[FAIL]" in text


def test_sample_images_directory_is_validated(tmp_path):
    with pytest.raises(SpikeError, match="not a directory"):
        sample_images_from(tmp_path / "nope")
    (tmp_path / "empty").mkdir()
    with pytest.raises(SpikeError, match="no images found"):
        sample_images_from(tmp_path / "empty")
    assert sample_images_from(None) == []


def test_sample_images_are_exercised_when_given(tmp_path):
    from scripts.spike.providers import render_fake_face

    images = tmp_path / "imgs"
    images.mkdir()
    for i in range(3):
        render_fake_face("real-ish", variation=i).save(images / f"{i}.png")
    result = run_check(
        StubEmbedder(), tmp_path / "wd", expected_dim=256, sample_images=sample_images_from(images)
    )
    step = next(s for s in result.steps if "your sample images" in s.name)
    assert step.ok
    assert "3 of 3" in step.detail
