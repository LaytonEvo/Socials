"""Cut a multi-shot piece from clips already on disk. No provider, no spend.

Everything else in `scripts/` generates. This one only assembles, because the shots it
needs already exist and the thing that has never been done is putting them together: a
talking shot of her plus a cutaway with nobody in it, as one piece, through the gate,
with the disclosure and the captions where they belong.

**This is the format the project can actually ship today.** The brief's swing shot is
withdrawn (ADR 0016: five renders out of five played a full swing from 30 yards) and a
shot containing her without a verifiable face is refused outright (ADR 0012). What
survives both rules is her talking to camera, intercut with golf that has no persona in
it — which is how a good many real golf accounts are built, and needs no motion transfer
and no new model.

**Order matters and the types enforce it.** Assemble first, from the pre-disclosure
clips, because a piece built from already-disclosed clips would carry the overlay twice
and captions timed against the wrong lengths. Then `apply_disclosure` once over the whole
piece, then captions over that — `burn_in` refuses if the caption band would sit on the
disclosure.

**The audio policy is per cut.** Her shot carries the voice its mouth was generated
against. The cutaway carries the video model's unconditional invented soundtrack, in no
identifiable language, which is dropped — see `AudioPolicy` in the assembler, and the
measured reason: keeping it put the loudest thing in the first assembled piece under a
b-roll shot.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

from app.config import load_all
from app.identity.dataset import NO_FACE_STILLS, collect, split
from app.identity.embedder import DlibEmbedder
from app.identity.evaluation import holdout_reference
from app.pipeline.acceptance import ShotUnderTest, assess
from app.pipeline.assembler import assemble, duration_of, edit_list
from app.pipeline.captions import Cue, burn_in, split_into_cues, write_srt
from app.pipeline.disclosure import apply_disclosure
from app.providers.pose import MediapipePose
from scripts.make_single_shot import REFERENCE_ROOT, SHOT

ROOT = Path(__file__).resolve().parents[1]


class Shot(TypedDict):
    """One cut, with everything the gate needs declared rather than inferred."""

    name: str
    path: str
    #: What she says over this cut, or None for a silent one. Captions are timed against
    #: the cut's own measured length and then offset into the piece, so a line never
    #: bleeds across the cut that follows it.
    line: str | None
    speaks: bool
    audio_source: str
    use_audio: bool
    persona_present: bool
    face_expected: bool
    #: Declared swing length, or None when the cut has no golf swing in it (ADR 0016).
    swing: str | None


#: The piece. A literal, as in `make_piece.py`, because the shot-list generator is task
#: 3.1 and does not exist yet.
PIECE: list[Shot] = [
    {
        # The lip-synced take, NOT `final.mp4` or `final_captioned.mp4`: those already
        # carry the disclosure and this piece gets it once, at the end, over everything.
        "name": "explain",
        "path": "spike/runs/shot1-final/synced.mp4",
        "line": str(SHOT["line"]),
        "speaks": True,
        "audio_source": "voice",
        "use_audio": True,
        "persona_present": True,
        "face_expected": True,
        "swing": None,
    },
    {
        # Nobody in frame: the ball finishing near the hole. 0% pose coverage measured
        # 2026-10-13, which is correct for a cutaway and is why it declares no swing.
        "name": "result",
        "path": "spike/runs/broll/result_take_0.mp4",
        "line": None,
        "speaks": False,
        "audio_source": "none",
        "use_audio": False,
        "persona_present": False,
        "face_expected": False,
        "swing": None,
    },
]


def cues_for(piece: list[Shot], lengths: list[float]) -> list[Cue]:
    """Caption cues for the whole piece, each shot's timed within its own cut.

    Apportioned per cut rather than across the piece, because a line belongs to the shot
    it is spoken in: timing it against the total would drift it over the cutaway.
    """
    out: list[Cue] = []
    offset = 0.0
    for shot, length in zip(piece, lengths, strict=True):
        if shot["line"]:
            out += [
                Cue(text=c.text, start_s=c.start_s + offset, end_s=c.end_s + offset)
                for c in split_into_cues(shot["line"], length)
            ]
        offset += length
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "cut")
    parser.add_argument(
        "--no-gate", action="store_true", help="assemble only; skip identity and the gate"
    )
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    paths = [ROOT / s["path"] for s in PIECE]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise SystemExit("missing source clips:\n  " + "\n  ".join(str(m) for m in missing))

    args.out.mkdir(parents=True, exist_ok=True)
    lengths = [duration_of(p) for p in paths]
    print(f"{len(PIECE)} cuts, {sum(lengths):.2f}s total")
    for shot, length in zip(PIECE, lengths, strict=True):
        who = "her, face visible" if shot["face_expected"] else "nobody in frame"
        print(f"  {shot['name']:<9} {length:>5.2f}s  {who:<18} audio={shot['audio_source']}")

    # ------------------------------------------------------------ assembly --
    edl = edit_list(
        [
            (path, shot["path"], shot["name"], shot["use_audio"])
            for shot, path in zip(PIECE, paths, strict=True)
        ],
        aspect="9:16",
        # Her cut carries the voice; the cutaway's invented soundtrack is dropped by its
        # own `use_audio=False`, and the assembler lays silence of the right length so the
        # picture cannot slide against the sound.
        audio="keep_source",
    )
    rough = assemble(edl, args.out / "rough.mp4")
    print(f"\nrough cut   {rough.path.name}  {duration_of(rough.path):.2f}s")

    # ---------------------------------------------------------- disclosure --
    # Once, over the whole piece. Nothing downstream accepts a RoughCut.
    final = apply_disclosure(
        rough.path, args.out / "final.mp4", overlay=config.persona.persona.disclosure.overlay
    )
    print(f"disclosed   {final.path.name}")

    # ------------------------------------------------------------ captions --
    cues = cues_for(PIECE, lengths)
    srt = write_srt(cues, args.out / "captions.srt")
    captioned = burn_in(
        final.path,
        cues,
        args.out / "final_captioned.mp4",
        overlay=config.persona.persona.disclosure.overlay,
    )
    print(f"captions    {captioned.name}  ({len(cues)} cues) + {srt.name}")

    if args.no_gate:
        print("\n--no-gate: not judged.")
        return 0

    # ---------------------------------------------------------------- gate --
    # Judged per shot on the SOURCE clips, because that is the unit the gate measures —
    # identity, audio provenance, swing. `disclosed=True` describes the delivered piece,
    # which did come from the overlay pass.
    embedder = DlibEmbedder(config.providers)
    dataset = split(
        collect(
            {k: REFERENCE_ROOT / k for k in ("master_v2", "outfit", "lighting", "body")},
            exclude=NO_FACE_STILLS,
        ),
        trigger_word="mollie",
    )
    reference, _ = holdout_reference(dataset, embedder)
    verdict = assess(
        [
            ShotUnderTest(
                name=shot["name"],
                path=path,
                speaks=shot["speaks"],
                audio_source=shot["audio_source"],
                persona_present=shot["persona_present"],
                face_expected=shot["face_expected"],
                swing=shot["swing"],  # type: ignore[arg-type]
            )
            for shot, path in zip(PIECE, paths, strict=True)
        ],
        reference=reference,
        embedder=embedder,
        threshold=float(config.persona.persona.look.identity_threshold_video or 0.0),
        disclosed=True,
        captioned=True,
        pose=MediapipePose(ROOT / str(config.providers.pose.pose_model)),
    )
    (args.out / "verdict.json").write_text(
        json.dumps(
            {
                "edl": edl.to_json(),
                "accepted": verdict.accepted,
                "findings": [
                    {"severity": str(f.severity), "rule": f.rule, "detail": f.detail}
                    for f in verdict.findings
                ],
            },
            indent=2,
        )
        + "\n"
    )
    print("\n" + "=" * 70)
    print(verdict.report())
    print("=" * 70)
    print(f"\ndeliverable  {captioned}")
    return 0 if verdict.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
