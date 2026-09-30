"""The gate that should have caught the regressions the owner caught instead.

Two real defects reached him because nothing between the render and his screen said no:
swapping the lip-sync model took identity from zero frames below threshold to nine of
ten, and the sound-effects model put an invented voice into a shot. Both are BLOCKING
rules here now.

The REVIEW findings matter as much. A gate that reports only what it happens to check
teaches people that a pass means "good", and the next defect lands in whatever it does
not look at — so it says out loud that it cannot judge continuity or lip sync.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from app.pipeline.acceptance import (
    Finding,
    Severity,
    ShotUnderTest,
    StillScreen,
    Verdict,
    assess,
    best_still,
    screen_still,
)
from scripts.spike.frames import FfmpegFrames


def _verdict(*findings: Finding) -> Verdict:
    return Verdict(findings=list(findings))


# --------------------------------------------------------------- verdicts --
def test_blocking_findings_refuse_the_piece() -> None:
    verdict = _verdict(Finding(Severity.BLOCKING, "identity", "not her"))
    assert verdict.accepted is False
    assert "REFUSED" in verdict.report()


def test_review_findings_do_not_refuse_but_are_reported() -> None:
    """A gate cannot judge continuity; it must not pretend the piece is finished."""
    verdict = _verdict(Finding(Severity.REVIEW, "continuity", "wardrobe unchecked"))
    assert verdict.accepted is True
    assert "ACCEPTED" in verdict.report()
    assert "continuity" in verdict.report()
    assert verdict.review


def test_the_report_names_every_finding() -> None:
    verdict = _verdict(
        Finding(Severity.BLOCKING, "a", "one"),
        Finding(Severity.REVIEW, "b", "two"),
    )
    report = verdict.report()
    assert "a" in report and "b" in report
    assert "1 blocking" in report and "1 for review" in report


# ------------------------------------------------------------ audio rules --
def test_sfx_on_a_shot_with_a_visible_face_is_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression that reached the owner.

    mmaudio is conditioned on the video and invents speech when it sees a person,
    whatever the prompt asked for. This is provenance rather than detection because
    finding a voice in a waveform is far less reliable than knowing which stage made it.
    """
    import app.pipeline.acceptance as module

    monkeypatch.setattr(module, "_has_audio", lambda _p: True)
    monkeypatch.setattr(
        FfmpegFrames, "extract", lambda self, clip, dest, fps: [Path("f1.png")] * 10
    )
    monkeypatch.setattr(
        module, "read_still", lambda path, embedder: type("R", (), {"embedding": np.ones(128)})()
    )
    monkeypatch.setattr(module, "cosine", lambda a, b: 0.99)

    verdict = assess(
        [ShotUnderTest("broll", Path("b.mp4"), speaks=False, audio_source="sfx")],
        reference=cast(Any, np.ones(128)),
        embedder=cast(Any, object()),
        threshold=0.95,
        disclosed=True,
    )
    rules = [f.rule for f in verdict.blocking]
    assert any("audio provenance" in r for r in rules), verdict.report()


def test_a_speaking_shot_must_get_its_audio_from_the_voice_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.pipeline.acceptance as module

    monkeypatch.setattr(module, "_has_audio", lambda _p: True)
    monkeypatch.setattr(
        FfmpegFrames, "extract", lambda self, clip, dest, fps: [Path("f1.png")] * 10
    )
    monkeypatch.setattr(
        module, "read_still", lambda path, embedder: type("R", (), {"embedding": np.ones(128)})()
    )
    monkeypatch.setattr(module, "cosine", lambda a, b: 0.99)

    verdict = assess(
        [ShotUnderTest("talk", Path("t.mp4"), speaks=True, audio_source="none")],
        reference=cast(Any, np.ones(128)),
        embedder=cast(Any, object()),
        threshold=0.95,
        disclosed=True,
    )
    assert not verdict.accepted


# --------------------------------------------------------------- identity --
def test_frames_below_threshold_are_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lip-sync swap regression: nine of ten frames below, shipped anyway."""
    import app.pipeline.acceptance as module

    monkeypatch.setattr(module, "_has_audio", lambda _p: True)
    monkeypatch.setattr(FfmpegFrames, "extract", lambda self, clip, dest, fps: [Path("f.png")] * 10)
    monkeypatch.setattr(
        module, "read_still", lambda path, embedder: type("R", (), {"embedding": np.ones(128)})()
    )
    monkeypatch.setattr(module, "cosine", lambda a, b: 0.944)

    verdict = assess(
        [ShotUnderTest("talk", Path("t.mp4"), speaks=True, audio_source="voice")],
        reference=cast(Any, np.ones(128)),
        embedder=cast(Any, object()),
        threshold=0.951,
        disclosed=True,
    )
    assert not verdict.accepted
    assert any("identity" in f.rule for f in verdict.blocking)


def test_thin_face_coverage_is_review_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """A golf swing scored 1 frame in 10 and read as "passes every frame". It does not
    pass; it cannot be judged."""
    import app.pipeline.acceptance as module

    calls = {"n": 0}

    def _read(path, embedder):
        calls["n"] += 1
        has_face = calls["n"] <= 1
        return type("R", (), {"embedding": np.ones(128) if has_face else None})()

    monkeypatch.setattr(module, "_has_audio", lambda _p: True)
    monkeypatch.setattr(FfmpegFrames, "extract", lambda self, clip, dest, fps: [Path("f.png")] * 10)
    monkeypatch.setattr(module, "read_still", _read)
    monkeypatch.setattr(module, "cosine", lambda a, b: 0.99)

    verdict = assess(
        [ShotUnderTest("swing", Path("s.mp4"), speaks=False, audio_source="none")],
        reference=cast(Any, np.ones(128)),
        embedder=cast(Any, object()),
        threshold=0.951,
        disclosed=True,
    )
    assert verdict.accepted, "thin coverage is not a measured failure"
    assert any("identity" in f.rule for f in verdict.review), verdict.report()


# ------------------------------------------------------------- disclosure --
def test_an_undisclosed_piece_is_refused() -> None:
    verdict = assess(
        [],
        reference=cast(Any, np.ones(128)),
        embedder=cast(Any, object()),
        threshold=0.95,
        disclosed=False,
    )
    assert not verdict.accepted
    assert any("disclosure" in f.rule for f in verdict.blocking)


# -------------------------------------------- what it admits it cannot do --
def test_a_multi_shot_piece_always_raises_continuity_for_review() -> None:
    """Wardrobe, hair, height and time of day drifted in every multi-shot piece and
    none of it is measured here. Silence would imply it had been checked."""
    verdict = assess(
        [],
        reference=cast(Any, np.ones(128)),
        embedder=cast(Any, object()),
        threshold=0.95,
        disclosed=True,
    )
    assert not verdict.review, "a zero-shot piece has no continuity to review"


def test_an_off_identity_keyframe_is_caught_before_the_chain_below_it() -> None:
    """The finding from the first single-shot run, as a test.

    The keyframe scored 0.94753 against a 0.9619 still threshold and the piece was
    refused at the end for an identity failure that was already in its first frame.
    Screening here costs $0.07 a candidate where the chain underneath costs $0.83.
    """
    import app.pipeline.acceptance as module

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        module, "read_still", lambda path, embedder: type("R", (), {"embedding": np.ones(128)})()
    )
    monkeypatch.setattr(module, "cosine", lambda a, b: 0.94753)
    screen = screen_still(
        Path("keyframe.png"),
        reference=cast(Any, np.ones(128)),
        embedder=cast(Any, object()),
        threshold=0.9619,
    )
    monkeypatch.undo()

    assert not screen.passes
    assert screen.score == pytest.approx(0.94753)


def test_the_best_keyframe_is_returned_even_when_none_passed() -> None:
    """The spread is the finding.

    Four candidates all landing near 0.947 says the prompt is off-identity; one low
    draw among three passes says that draw was unlucky. A bare refusal says neither,
    so the caller gets the best one and reports the rest.
    """
    screens = [
        StillScreen(Path("a.png"), 0.9470, False),
        StillScreen(Path("b.png"), 0.9482, False),
        StillScreen(Path("c.png"), 0.9461, False),
    ]
    assert best_still(screens).path.name == "b.png"


def test_a_keyframe_with_no_detectable_face_cannot_be_chosen() -> None:
    """An unscorable candidate is not a low-scoring one, and must not win by default."""
    with pytest.raises(ValueError, match="detectable face"):
        best_still([StillScreen(Path("x.png"), float("nan"), False)])
