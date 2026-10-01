"""Does this piece pass? One gate, run after every change.

Every regression in this pipeline so far reached the owner because nothing between the
render and him said no. Swapping the lip-sync model took identity from zero frames below
threshold to nine of ten, and the sound-effects model put an invented voice back into a
shot — both shipped, both found by a human watching. That is not a process; it is a
person doing a machine's job.

So this refuses a piece on what can be measured, and — just as importantly — **says out
loud what it cannot measure**, rather than passing in silence and implying the rest is
fine. A gate that only reports what it happens to check teaches people that a pass means
"good", and the next defect will be in whatever it does not look at.

Two severities, and the difference is real:

- `BLOCKING` — the piece does not go out. This covers two cases, not one: measured and
  wrong, **and** not measurable at all where the measurement is the point. Unverifiable
  identity blocks. A gate cannot vouch for a face it could not see.
- `REVIEW` — a human must judge this, and no measurement could have. Lip sync is the
  honest example: whether a mouth matches words is not recoverable from frames at any
  sampling rate. Not a warning to skim past; an unreviewed REVIEW is an unfinished check.

**The distinction was learned the hard way.** Identity coverage was first implemented as
REVIEW, on the reasoning that "cannot say" is not "wrong". Over five pass-rate runs on
2026-10-01 that reasoning produced four ACCEPTED verdicts in which identity had never
been measured — one with no detectable face in a single frame — against one REFUSED, the
only run where identity *could* be measured. The gate was reporting an 80% pass rate for
a pipeline whose verified pass rate was zero of one. "Cannot say" belongs with the
refusals whenever the thing unsaid is the thing the gate exists to check.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.identity.embedder import DlibEmbedder, Embedding, cosine
from app.identity.master_set import read_still
from scripts.spike.frames import FfmpegFrames


class Severity(StrEnum):
    BLOCKING = "BLOCKING"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    rule: str
    detail: str


@dataclass(frozen=True)
class ShotUnderTest:
    """One cut, and what it is supposed to be.

    `audio_source` is provenance, not description: which stage produced the sound. The
    rule below turns on it because detecting a voice in a waveform is unreliable and
    knowing where the audio came from is not.
    """

    name: str
    path: Path
    speaks: bool
    #: "voice" | "sfx" | "none"
    audio_source: str
    #: Whether her face should be verifiable in this shot at all.
    #:
    #: Declared by the shot list, not inferred from the render, because the two failure
    #: modes are opposite. A face-forward shot with no detectable face is a broken shot and
    #: blocks. A down-the-line shot filmed from behind her, or a cutaway to the ball on the
    #: green, has no face *by design* — refusing it would refuse the brief.
    #:
    #: Inferring this from the footage would let the generator decide what it is allowed to
    #: fail at: a face-forward take that drifted until no face was detectable would be
    #: reclassified as b-roll and pass.
    face_expected: bool = True


@dataclass
class Verdict:
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.BLOCKING]

    @property
    def review(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.REVIEW]

    @property
    def accepted(self) -> bool:
        """Measured faults only. A piece with REVIEW items is not finished, but this
        gate is not the thing that finishes it."""
        return not self.blocking

    def report(self) -> str:
        lines = [
            f"{'ACCEPTED' if self.accepted else 'REFUSED'}  "
            f"({len(self.blocking)} blocking, {len(self.review)} for review)"
        ]
        for finding in self.findings:
            lines.append(f"  [{finding.severity}] {finding.rule}: {finding.detail}")
        return "\n".join(lines)


#: Below this share of frames carrying a detectable face, an identity score describes
#: too little of the shot to stand for it. Set from the video identity test, where a
#: golf swing scored 1 frame in 10 and read as a pass.
MIN_COVERAGE = 0.6


def _has_audio(video: Path) -> bool:
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


def assess(
    shots: list[ShotUnderTest],
    *,
    reference: Embedding,
    embedder: DlibEmbedder,
    threshold: float,
    disclosed: bool,
    captioned: bool = False,
    roll_swing_deg: float | None = None,
    roll_drift_deg: float | None = None,
    sample_fps: float = 2.0,
) -> Verdict:
    """Judge a finished piece shot by shot."""
    verdict = Verdict()

    if not disclosed:
        verdict.findings.append(
            Finding(
                Severity.BLOCKING,
                "disclosure",
                "this piece did not come from the overlay pass. Nothing without the "
                "disclosure burned in may be treated as a render.",
            )
        )

    sampler = FfmpegFrames()
    for shot in shots:
        # -------------------------------------------------------- identity --
        frames = sampler.extract(shot.path, Path(f"/tmp/acceptance_{shot.name}"), sample_fps)
        scores = []
        for frame in frames:
            reading = read_still(frame, embedder)
            if reading.embedding is not None:
                scores.append(cosine(reading.embedding, reference))
        coverage = len(scores) / len(frames) if frames else 0.0

        if not shot.face_expected:
            # A shot that is not supposed to show her face is judged on the opposite
            # question: not "is this her" but "is there someone here who should not be".
            # A face that appears in a down-the-line or cutaway shot and scores below
            # threshold is a stranger in the piece, which is worse than no face at all.
            if scores and min(scores) < threshold:
                verdict.findings.append(
                    Finding(
                        Severity.BLOCKING,
                        f"{shot.name}: identity",
                        f"this shot declares no face, but a face was found in "
                        f"{len(scores)} of {len(frames)} frames scoring as low as "
                        f"{min(scores):.5f}, below {threshold}. Someone who is not her is "
                        f"on screen.",
                    )
                )
        elif not scores:
            # BLOCKING, not REVIEW. Measured 2026-10-01: across five pass-rate runs, four
            # were ACCEPTED on exactly this branch and its thin-coverage sibling below —
            # one of them with no detectable face in a single frame. The only run where
            # identity could actually be measured is the one that failed. A gate that
            # passes the shots it cannot vouch for reports a pass rate for "cannot say",
            # which is the opposite of its purpose.
            verdict.findings.append(
                Finding(
                    Severity.BLOCKING,
                    f"{shot.name}: identity",
                    "no detectable face in any frame, so identity cannot be judged here. "
                    "Unverifiable is not acceptable: this gate cannot vouch for a shot it "
                    "could not measure.",
                )
            )
        elif coverage < MIN_COVERAGE:
            verdict.findings.append(
                Finding(
                    Severity.BLOCKING,
                    f"{shot.name}: identity",
                    f"a face was found in only {len(scores)} of {len(frames)} frames "
                    f"({coverage:.0%}), under the {MIN_COVERAGE:.0%} floor. The score "
                    f"describes too little of the shot to stand for it — min "
                    f"{min(scores):.5f} over {len(scores)} frames is not a pass, it is "
                    f"'cannot say', and this gate refuses rather than guesses.",
                )
            )
        elif min(scores) < threshold:
            below = sum(1 for s in scores if s < threshold)
            verdict.findings.append(
                Finding(
                    Severity.BLOCKING,
                    f"{shot.name}: identity",
                    f"{below} of {len(scores)} frames score below {threshold} "
                    f"(min {min(scores):.5f}, mean {sum(scores) / len(scores):.5f}). "
                    f"It is not reliably her.",
                )
            )

        # ----------------------------------------------------------- audio --
        # Provenance, not detection. The sound-effects model generates speech when it
        # sees a person, whatever the prompt asked for, and finding a voice in a
        # waveform is far less reliable than knowing which stage made the sound.
        if shot.audio_source == "sfx" and scores:
            verdict.findings.append(
                Finding(
                    Severity.BLOCKING,
                    f"{shot.name}: audio provenance",
                    "generated sound effects on a shot with a visible face. That model is "
                    "conditioned on the video and invents speech when it sees a person — "
                    "measured on 2026-09-30. Only the voice provider may supply audio for a "
                    "shot her face appears in.",
                )
            )
        if shot.speaks and shot.audio_source != "voice":
            verdict.findings.append(
                Finding(
                    Severity.BLOCKING,
                    f"{shot.name}: audio provenance",
                    f"a speaking shot whose audio came from {shot.audio_source!r} rather "
                    f"than the voice provider.",
                )
            )
        if shot.speaks and not _has_audio(shot.path):
            verdict.findings.append(
                Finding(
                    Severity.BLOCKING,
                    f"{shot.name}: audio",
                    "a speaking shot with no audio stream at all.",
                )
            )

    # ------------------------------------------- the piece, not the shots --
    # Per-shot permissiveness must not let the whole piece escape verification. Three
    # clips that each legitimately declare no face would, shot by shot, raise no identity
    # finding at all — and a piece that never verified identity anywhere is a piece of an
    # unverified person, whatever its shots were entitled to skip.
    if shots and not any(s.face_expected for s in shots):
        verdict.findings.append(
            Finding(
                Severity.BLOCKING,
                "identity",
                f"no shot in this piece ({len(shots)} shots) expects a verifiable face, so "
                f"identity was never checked anywhere in it. At least one shot must be one "
                f"the gate can verify her in.",
            )
        )

    # ------------------------------------------- what this cannot measure --
    if len(shots) > 1:
        verdict.findings.append(
            Finding(
                Severity.REVIEW,
                "continuity",
                f"{len(shots)} shots. Wardrobe, hair, height and time of day are not "
                f"measured here and have drifted in every multi-shot piece so far. "
                f"A human must confirm it reads as one person on one day.",
            )
        )
    if any(s.speaks for s in shots):
        verdict.findings.append(
            Finding(
                Severity.REVIEW,
                "lip sync",
                "whether the mouth matches the words is not measurable here. A human must "
                "watch and listen.",
            )
        )
    if roll_swing_deg is not None:
        # Reported, not scored. The owner has flagged a head tilt twice, and it is now
        # measured — but what counts as too much swing has never been calibrated against
        # anything, so a number here would be invented. Saying it out loud lets the one
        # instrument that has caught it twice do so sooner.
        verdict.findings.append(
            Finding(
                Severity.REVIEW,
                "head tilt",
                f"the chosen take swings {roll_swing_deg:.1f} degrees of head roll"
                + (f" and drifts {roll_drift_deg:+.1f} by the end" if roll_drift_deg else "")
                + ". No calibrated ceiling exists for this, so a human must say whether it "
                "reads as a person or as a glitch.",
            )
        )
    if captioned:
        verdict.findings.append(
            Finding(
                Severity.REVIEW,
                "caption timing",
                "cue timings are apportioned by character count, which is a proxy for how "
                "long a phrase takes to say and not a measurement of it. A human must "
                "check the words appear when they are spoken.",
            )
        )
    return verdict


@dataclass(frozen=True)
class StillScreen:
    """One keyframe, scored before anything downstream is paid for."""

    path: Path
    score: float
    passes: bool


def screen_still(
    path: Path, *, reference: Embedding, embedder: DlibEmbedder, threshold: float
) -> StillScreen:
    """Score a keyframe against the still threshold.

    Separate from `assess` because it runs at a different time, for a different reason.
    `assess` judges a finished piece; this judges the first input to it, while changing
    course still costs $0.07 instead of $0.83.
    """
    try:
        embedding = read_still(path, embedder).embedding
    except Exception:
        return StillScreen(path=path, score=float("nan"), passes=False)
    if embedding is None:
        # No face found is not a low score. It is an unscorable candidate, and
        # `best_still` must not let it win by comparing as anything at all.
        return StillScreen(path=path, score=float("nan"), passes=False)
    score = float(cosine(embedding, reference))
    return StillScreen(path=path, score=score, passes=score >= threshold)


def best_still(screens: list[StillScreen]) -> StillScreen:
    """The highest-scoring keyframe, whether or not any of them passed.

    Returns the best rather than raising so the caller can report the spread: knowing
    that four candidates all landed near 0.947 says something a refusal does not, namely
    that the prompt is off-identity rather than that this one draw was unlucky.
    """
    if not screens:
        raise ValueError("no keyframe candidates to choose between")
    scored = [s for s in screens if s.score == s.score]  # NaN fails this
    if not scored:
        raise ValueError("no keyframe candidate had a detectable face to score")
    return max(scored, key=lambda s: s.score)
