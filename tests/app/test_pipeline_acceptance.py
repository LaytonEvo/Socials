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


def test_thin_face_coverage_is_refused_not_merely_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A golf swing scored 1 frame in 10 and read as "passes every frame".

    This assertion was inverted on 2026-10-01, deliberately. It originally required thin
    coverage to be REVIEW and the piece to be ACCEPTED, reasoning that "cannot say" is
    not "wrong". Five pass-rate runs showed where that leads: four ACCEPTED verdicts in
    which identity had never been measured — one with no detectable face in any frame —
    against one REFUSED, the only run that could be measured. The gate reported 80% for
    a pipeline whose verified rate was zero of one.

    So an unmeasurable identity now blocks. REVIEW is kept for what no measurement could
    settle, like lip sync; it is not a place to put the measurement that failed to
    happen.
    """
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
    assert not verdict.accepted, (
        "a shot whose identity could not be measured was accepted — this is the exact "
        "verdict that reported an 80% pass rate for an unverified pipeline"
    )
    identity = [f for f in verdict.blocking if "identity" in f.rule]
    assert identity, verdict.report()
    assert "cannot say" in identity[0].detail


def test_no_face_at_all_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run 3 of the pass-rate battery was ACCEPTED with no detectable face in any frame.

    Zero coverage is the strongest case for refusing, not a special case for passing: the
    gate has seen nothing of the person it exists to verify.
    """
    import app.pipeline.acceptance as module

    monkeypatch.setattr(module, "_has_audio", lambda _p: True)
    monkeypatch.setattr(FfmpegFrames, "extract", lambda self, clip, dest, fps: [Path("f.png")] * 10)
    monkeypatch.setattr(
        module, "read_still", lambda path, embedder: type("R", (), {"embedding": None})()
    )

    verdict = assess(
        [ShotUnderTest("blind", Path("b.mp4"), speaks=False, audio_source="none")],
        reference=cast(Any, np.ones(128)),
        embedder=cast(Any, object()),
        threshold=0.951,
        disclosed=True,
    )
    assert not verdict.accepted, verdict.report()
    assert any("cannot vouch" in f.detail for f in verdict.blocking), verdict.report()


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


# ------------------------------------------------------- per-shot expectations --
def _patch(monkeypatch: pytest.MonkeyPatch, *, score: float | None, frames: int = 10) -> None:
    import app.pipeline.acceptance as module

    monkeypatch.setattr(module, "_has_audio", lambda _p: True)
    monkeypatch.setattr(
        FfmpegFrames, "extract", lambda self, clip, dest, fps: [Path("f.png")] * frames
    )
    monkeypatch.setattr(
        module,
        "read_still",
        lambda path, embedder: type(
            "R", (), {"embedding": None if score is None else np.ones(128)}
        )(),
    )
    if score is not None:
        monkeypatch.setattr(module, "cosine", lambda a, b: score)


def _assess(shots: list[ShotUnderTest]) -> Verdict:
    return assess(
        shots,
        reference=cast(Any, np.ones(128)),
        embedder=cast(Any, object()),
        threshold=0.951,
        disclosed=True,
    )


def test_a_shot_with_no_face_by_design_is_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cutaway she is not in has no identity to verify, and refusing it refuses b-roll.

    Narrowed 2026-10-01. This originally used a down-the-line shot OF HER as the example of
    a legitimate no-face shot, and that turned out to be the dangerous case rather than the
    safe one: the render came back as a different woman and nothing could tell. A shot she
    is not in is the safe case, and `persona_present=False` is what says so.
    """
    _patch(monkeypatch, score=None)
    verdict = _assess(
        [
            ShotUnderTest("explain", Path("1.mp4"), speaks=True, audio_source="voice"),
            ShotUnderTest(
                "ball_on_the_green",
                Path("4.mp4"),
                speaks=False,
                audio_source="none",
                face_expected=False,
                persona_present=False,
            ),
        ]
    )
    assert not any("ball_on_the_green" in f.rule for f in verdict.blocking), verdict.report()


def test_a_stranger_in_a_no_face_shot_still_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not 'is this her' but 'is someone here who should not be'.

    A face that turns up in a cutaway and scores below threshold is a stranger in the
    piece, which is worse than no face at all.
    """
    _patch(monkeypatch, score=0.88)
    verdict = _assess(
        [
            ShotUnderTest(
                "cutaway",
                Path("4.mp4"),
                speaks=False,
                audio_source="none",
                face_expected=False,
                persona_present=False,
            ),
            ShotUnderTest("explain", Path("1.mp4"), speaks=True, audio_source="voice"),
        ]
    )
    assert any("not her is on screen" in f.detail for f in verdict.blocking), verdict.report()


def test_a_face_forward_shot_that_lost_her_face_still_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`face_expected` is declared by the shot list, never inferred from the footage.

    Inferring it would let the generator choose what it is allowed to fail at: a
    face-forward take that drifted until no face was detectable would be reclassified as
    b-roll and pass.
    """
    _patch(monkeypatch, score=None)
    verdict = _assess([ShotUnderTest("explain", Path("1.mp4"), speaks=True, audio_source="voice")])
    assert any("cannot vouch" in f.detail for f in verdict.blocking), verdict.report()


def test_a_piece_where_no_shot_verifies_identity_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-shot permissiveness must not let the whole piece escape verification."""
    _patch(monkeypatch, score=None)
    verdict = _assess(
        [
            ShotUnderTest(
                "a", Path("a.mp4"), speaks=False, audio_source="none", face_expected=False
            ),
            ShotUnderTest(
                "b", Path("b.mp4"), speaks=False, audio_source="none", face_expected=False
            ),
        ]
    )
    assert any("never checked anywhere" in f.detail for f in verdict.blocking), verdict.report()


def test_a_shot_containing_her_without_a_face_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hole that shipped a different woman.

    A down-the-line swing shows her prominently — hair, build, posture, clothes — and no
    face. `face_expected=False` switched identity checking off on a shot entirely about
    her, and the render came back as someone else. The owner's verdict: "not her."

    The scorer reads faces. Nothing measures hair or build, so this combination cannot be
    vouched for by any means the pipeline has, and the honest answer is to refuse it.
    """
    _patch(monkeypatch, score=None)
    verdict = _assess(
        [
            ShotUnderTest("explain", Path("1.mp4"), speaks=True, audio_source="voice"),
            ShotUnderTest(
                "down_the_line",
                Path("2.mp4"),
                speaks=False,
                audio_source="none",
                face_expected=False,
                persona_present=True,
            ),
        ]
    )
    assert any("no verifiable face" in f.detail for f in verdict.blocking), verdict.report()


def test_a_shot_she_is_not_in_is_still_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ball on a green has no identity to verify, and refusing it would refuse b-roll."""
    _patch(monkeypatch, score=None)
    verdict = _assess(
        [
            ShotUnderTest("explain", Path("1.mp4"), speaks=True, audio_source="voice"),
            ShotUnderTest(
                "ball",
                Path("4.mp4"),
                speaks=False,
                audio_source="none",
                face_expected=False,
                persona_present=False,
            ),
        ]
    )
    assert not any("ball" in f.rule for f in verdict.blocking), verdict.report()
