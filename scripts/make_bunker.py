"""Build "The Bunker" — docs/briefs/bunker-flop-2026-10-15.md.

She lines up a flop out of a greenside bunker, talks it up, doesn't get it out, and the
ball rolls back to her feet. Four shots, twenty seconds, 1080x1920.

**Every shot is five seconds because five is the model's floor.** The brief asked for
4s/3s/4s/4s; `video.golf_1080` advertises `durations_s: [5 … 15]` and nothing shorter, so
the brief's fifteen seconds is not renderable here and the piece is twenty. Shortening
happens in the edit afterwards, not in the request. The extra second helps the facepalm:
one second of palm in five leaves ~80% face coverage rather than ~75%.

**The swing is not in it, deliberately.** A greenside bunker shot is a full athletic swing
and full swings have failed 11 renders out of 11. So the piece cuts from her address to
the sand and back — the swing happens between shots 2 and 3, which is where an editor
would put it anyway, because the joke is the result rather than the technique.

**The facepalm is held short and late.** A palm over the face removes the face, and the
face is what the identity scorer reads. One second of it inside a four-second shot leaves
coverage near 75%, above the 60% floor, and she comes out from behind the hand at the end.

**Wardrobe is asked for and then measured.** The brief wants a short skort and a fitted
polo, which `config/persona.yaml` §clothing permits. Describing clothing has historically
cost identity, so each keyframe is screened against the identity bar after the edit and
redrawn if it drops — the measurement decides whether the wardrobe change was affordable,
rather than an argument about it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict, cast

import httpx
from sqlalchemy.orm import Session

from app.compliance.c2pa import credentials, sign
from app.config import load_all
from app.costs.guard import BudgetGuard
from app.costs.ledger import spend_this_month
from app.identity.dataset import NO_FACE_STILLS, collect, split
from app.identity.embedder import DlibEmbedder
from app.identity.evaluation import holdout_reference
from app.models import Generation
from app.models.session import make_engine
from app.pipeline.acceptance import ShotUnderTest, assess, screen_still
from app.pipeline.assembler import assemble, duration_of, edit_list
from app.pipeline.captions import Cue, burn_in, split_into_cues, write_srt
from app.pipeline.disclosure import apply_disclosure
from app.pipeline.lipsync import lip_sync
from app.pipeline.recording import ShotSpec, open_run, resume_run
from app.pipeline.swing import SwingKind
from app.pipeline.takes import measure
from app.pipeline.voice import pad_to
from app.providers.fal import QUEUE_ROOT, api_key
from app.providers.pose import MediapipePose
from app.storage.keys import key_for
from app.storage.s3 import S3Storage, bucket_from_env
from scripts.make_broll import edit_keyframe
from scripts.make_single_shot import REFERENCE_ROOT
from scripts.train_lora import persona_storage_id
from scripts.video_identity_test import submit_clip

ROOT = Path(__file__).resolve().parents[1]

#: Carried into every scene edit so wardrobe and light do not drift between shots. The
#: skort and polo are named here ONCE and then inherited, rather than re-described per
#: shot, because every re-description is another chance for the model to reinvent her.
LOOK = (
    "Keep the same woman and the same late afternoon light. She wears a short white golf "
    "skort, a fitted white golf polo and a white visor, with a glove on her lead hand. "
)


class Shot(TypedDict):
    name: str
    seconds: int
    #: What the gate should MEASURE this shot's hands against, or None where no
    #: declaration is honest. Declaring is how a swing the prompt forbade gets caught:
    #: the model ignores prompts, so "she does not swing" is worth nothing on its own
    #: and `chip` on the address shot turns a snuck-in full swing into a BLOCKING
    #: finding. It is left None where hands legitimately cross the shoulder line —
    #: the facepalm raises one by design, and a declaration there would block the shot
    #: for doing exactly what the brief asks.
    swing: str | None
    scene: str
    motion: str
    line: str | None
    speaks: bool
    audio_source: str
    persona_present: bool
    face_expected: bool


PIECE: list[Shot] = [
    {
        "name": "setup",
        "seconds": 5,
        "swing": None,
        "scene": LOOK + "She stands in a greenside bunker, the sand around her feet and "
        "the bunker lip behind her shoulder with a flag just beyond it. The camera is in "
        "front of her at chest height. Her face is clearly visible to the camera.",
        "motion": "She looks into the lens and talks to camera, holding a lob wedge. Her "
        "head stays up and still. The camera does not move.",
        "line": "Right — greenside bunker, pin's just over the lip. "
        "This is where we find out whether those lessons did anything.",
        "speaks": True,
        "audio_source": "voice",
        "persona_present": True,
        "face_expected": True,
    },
    {
        "name": "address",
        "seconds": 5,
        "swing": "chip",
        "scene": LOOK + "She stands over a golf ball in a greenside bunker with a lob "
        "wedge, the clubface open, settling into her stance. Whole body in frame, the "
        "camera in front of her, her face visible and turned toward the camera.",
        # The club does NOT touch the sand: grounding it in a bunker is a two-stroke
        # penalty and the most recognisable tell in a golf clip.
        "motion": "She shuffles her feet down into the sand and settles over the ball, "
        "holding the clubhead just above the sand without touching it, then lifts her "
        "eyes to the camera for a beat. She does not swing. The camera does not move.",
        "line": None,
        "speaks": False,
        "audio_source": "none",
        "persona_present": True,
        "face_expected": True,
    },
    {
        "name": "result",
        "seconds": 5,
        "swing": None,
        "scene": LOOK.replace("She wears", "Nobody is in the frame. A golfer wears")
        + "The camera is low and tight on the sand of a greenside bunker, the lip filling "
        "the top of the frame. A single golf ball sits in the sand. Nobody is in the frame.",
        "motion": "Sand sprays up. The ball pops up the face of the bunker, clips the top "
        "of the lip, checks, and rolls back down the sand to the bottom of the bunker, "
        "where it comes to rest. Nothing else moves. The camera does not move.",
        "line": None,
        "speaks": False,
        "audio_source": "none",
        "persona_present": False,
        "face_expected": False,
    },
    {
        "name": "facepalm",
        "seconds": 5,
        "swing": None,
        "scene": LOOK + "She stands in a greenside bunker looking down at a golf ball by "
        "her feet, the lip behind her. The camera is in front of her at chest height. Her "
        "face is clearly visible to the camera.",
        "motion": "She looks down at the ball, then straight into the lens, flat. She "
        "brings one palm up to her face for a moment, then drops it and looks back at the "
        "camera. Her hand is away from her face for most of the shot. The camera does "
        "not move.",
        "line": "...They did not.",
        "speaks": True,
        "audio_source": "voice",
        "persona_present": True,
        "face_expected": True,
    },
]


def speak(client: httpx.Client, slot: Any, voice: Any, text: str, dest: Path) -> Path:
    """One line of dialogue. Shape copied from the single-shot path, not from memory."""
    shape = dict(slot.request or {})
    assert slot.model is not None
    arguments: dict[str, Any] = {
        str(shape.get("text_field", "text")): text,
        str(shape.get("voice_field", "voice")): str(voice.voice_id),
        **dict(voice.options or {}),
    }
    response = client.post(f"{QUEUE_ROOT}/{slot.model}", json=arguments)
    response.raise_for_status()
    submitted = response.json()
    for _ in range(120):
        if client.get(submitted["status_url"]).json().get("status") in {
            "COMPLETED",
            "FAILED",
            "ERROR",
        }:
            break
        time.sleep(3)
    url = str((client.get(submitted["response_url"]).json().get("audio") or {}).get("url") or "")
    if not url:
        raise SystemExit(f"TTS returned no audio for {dest.name}")
    dest.write_bytes(client.get(url, timeout=120.0).content)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "bunker")
    parser.add_argument(
        "--from-keyframe",
        type=Path,
        default=ROOT / "spike" / "runs" / "shot1-v2" / "keyframe.png",
        help="the clean, seam-screened still every scene is edited from",
    )
    parser.add_argument("--takes", type=int, default=3)
    parser.add_argument("--keyframe-tries", type=int, default=3)
    parser.add_argument(
        "--keyframe-bar",
        type=float,
        default=None,
        help="identity bar for keyframes; the configured 0.970 is a portrait number and "
        "these are full-body scenes (action-battery-2026-10-15.md)",
    )
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    guard = BudgetGuard(config.budget, config.providers)
    edit_slot, edit_price, _ = guard.price("image", "keyframe")
    video_slot, video_price, _ = guard.price("video", "golf_1080")
    voice_slot, voice_price, _ = guard.price("voice", "primary")
    sync_slot, sync_price, _ = guard.price("lipsync", "primary")
    assert video_slot.model is not None

    seconds = sum(s["seconds"] for s in PIECE)
    spoken = [s for s in PIECE if s["line"]]
    estimate = (
        guard.estimate("image", "keyframe", Decimal(len(PIECE)))
        + guard.estimate("video", "golf_1080", Decimal(seconds * args.takes))
        + guard.estimate(
            "voice", "primary", Decimal(sum(len(str(s["line"])) for s in spoken)) / 1000
        )
        + guard.estimate("lipsync", "primary", Decimal(sum(s["seconds"] for s in spoken)))
    )
    print(f'"The Bunker" — {len(PIECE)} shots, {seconds}s, {args.takes} takes each')
    print(f"  keyframe  {edit_slot.model}")
    print(
        f"  video     {video_slot.model} at "
        f"{(video_slot.request.get('base') or {}).get('resolution')}"
    )
    print(f"  voice     {voice_slot.model}   lip sync  {sync_slot.model}")
    print("  the swing is NOT rendered: it happens in the cut between address and result")
    print(f"ESTIMATE    ${estimate}")
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0
    if not args.from_keyframe.is_file():
        raise SystemExit(f"no source keyframe at {args.from_keyframe}")

    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    # Everything that can fail for free fails now. Signing is the last step of the run
    # and reads two secrets from the environment; discovering one is missing after the
    # generation is paid for would mean paying twice for the same piece.
    creds = credentials()
    storage = S3Storage(bucket=bucket_from_env())
    client = httpx.Client(
        timeout=900.0, headers={"Authorization": f"Key {api_key()}"} if api_key() else {}
    )
    embedder = DlibEmbedder(config.providers)
    dataset = split(
        collect(
            {k: REFERENCE_ROOT / k for k in ("master_v2", "outfit", "lighting", "body")},
            exclude=NO_FACE_STILLS,
        ),
        trigger_word="mollie",
    )
    reference, _ = holdout_reference(dataset, embedder)
    threshold = float(config.persona.persona.look.identity_threshold_video or 0.0)
    bar = float(args.keyframe_bar) if args.keyframe_bar is not None else threshold
    if bar < threshold:
        raise SystemExit(f"--keyframe-bar {bar} is below the video threshold {threshold}")
    pose = MediapipePose(ROOT / str(config.providers.pose.pose_model))
    engine = make_engine()
    session = Session(bind=engine, expire_on_commit=False)
    specs = [
        ShotSpec(
            name=s_["name"],
            description=s_["motion"],
            duration_s=float(s_["seconds"]),
            face_expected=bool(s_["face_expected"]),
            dialogue=s_["line"],
        )
        for s_ in PIECE
    ]
    brief = "The Bunker — docs/briefs/bunker-flop-2026-10-15.md"
    recorder = resume_run(session, brief=brief, shots=specs) if args.skip_generate else None
    if recorder is not None:
        print(f"resuming    piece {recorder.piece.id}")
    recorder = recorder or open_run(
        session,
        persona_name=str(config.persona.persona.name),
        brief=brief,
        # `content_piece.format` is free text; the brief's own word for this shape.
        video_format="reaction",
        shots=specs,
    )

    def bill(estimated: Decimal, what: str) -> None:
        """The guard, ahead of the provider — the other half of the cost rule.

        `guard.price` only says what a unit costs. This is the call that can refuse,
        and it reads the ledger, which is why `recording.py` exists. The orchestrator
        (BUILD_PLAN 3.4) should own this pairing; until it does, a run that spends has
        to do it itself or the ceiling means nothing.
        """
        reservation = guard.check(
            session, estimated_usd=estimated, content_piece_id=recorder.piece.id
        )
        if reservation.warning:
            print(f"  BUDGET    {reservation.warning} ({what})")

    persona_id = persona_storage_id(config.persona.persona.id)

    chosen: list[tuple[Shot, Path]] = []
    for shot in PIECE:
        name = shot["name"]
        print(f"\n{name}")
        keyframe = args.out / f"{name}_keyframe.png"
        frame_row = None
        for attempt in range(1, args.keyframe_tries + 1):
            reused = attempt == 1 and args.skip_generate and keyframe.is_file()
            if not reused:
                bill(edit_price, f"{name} keyframe attempt {attempt}")
                edit_keyframe(client, edit_slot, args.from_keyframe, shot["scene"], keyframe)
            screen = (
                screen_still(keyframe, reference=reference, embedder=embedder, threshold=bar)
                if shot["face_expected"]
                else None
            )
            # Recorded whether it passed or not: a rejected attempt was still billed, and
            # a run that records only its keepers understates itself by its retries.
            frame_key = key_for(persona_id, "keyframe", f"bunker-{name}-{attempt}.png")
            storage.put(frame_key, keyframe.read_bytes(), content_type="image/png", overwrite=True)
            # A reused file was paid for by an earlier run and recorded there. Recording
            # it again would bill the ledger twice for one call, which is the same
            # corruption as not recording it at all, pointing the other way.
            frame_row = (
                None
                if reused
                else recorder.keyframe(
                    name,
                    provider=str(edit_slot.backend),
                    model=str(edit_slot.model),
                    prompt=shot["scene"],
                    storage_key=frame_key,
                    identity_score=(
                        screen.score
                        if screen is not None and screen.score == screen.score
                        else None
                    ),
                    units=Decimal(1),
                    unit_price=edit_price,
                    price_verified_on=edit_slot.verified_on,
                    embedding_model=embedder.model,
                )
            )
            if screen is None:
                print("  keyframe  no face expected in this shot; not screened on identity")
                break
            score = "no face" if screen.score != screen.score else f"{screen.score:.5f}"
            seam_score = screen.seam.score if screen.seam is not None else float("nan")
            print(
                f"  keyframe  attempt {attempt}: face {score} (bar {bar})  "
                f"seam {seam_score:.2f}{'  SEAMED' if screen.seamed else ''}"
            )
            if screen.passes:
                break
        else:
            raise SystemExit(
                f"no keyframe for {name} passed in {args.keyframe_tries} attempts. The "
                f"wardrobe change may be costing identity — try --from-keyframe with a "
                f"source still already in a skort, rather than asking the edit for one."
            )

        request = dict(video_slot.request or {})
        allowed = list((video_slot.capabilities or {}).get("durations_s") or [])
        if allowed and int(shot["seconds"]) not in allowed:
            raise SystemExit(
                f"{name} asks for {shot['seconds']}s and the model takes {allowed}. "
                f"Cut it shorter in the edit; do not send a duration it does not take."
            )
        request["duration_s"] = int(shot["seconds"])
        takes = []
        rows: dict[Path, Generation | None] = {}
        for index in range(args.takes):
            take = args.out / f"{name}_take_{index}.mp4"
            reused_take = args.skip_generate and take.is_file()
            if not reused_take:
                bill(video_price * Decimal(shot["seconds"]), f"{name} take {index + 1}")
                url = submit_clip(client, video_slot.model, shot["motion"], keyframe, request)
                take.write_bytes(client.get(url, timeout=600.0).content)
            takes.append(take)
            # Recorded here, not after the pick. Scoring every take of a shot is a dlib
            # pass over several hundred frames and takes minutes; a crash in there would
            # otherwise lose takes the provider has already charged for.
            take_key = key_for(persona_id, "take", f"bunker-{take.stem}.mp4")
            storage.put(take_key, take.read_bytes(), content_type="video/mp4", overwrite=True)
            # On reuse: find the row an earlier run wrote, so scoring can complete it,
            # but write no new ledger row — this run did not pay for this take.
            rows[take] = (
                recorder.find_take(take_key)
                if reused_take
                else recorder.take(
                    name,
                    keyframe=frame_row,
                    provider=str(video_slot.backend),
                    model=str(video_slot.model),
                    prompt=shot["motion"],
                    params=request,
                    duration_s=float(shot["seconds"]),
                    units=Decimal(shot["seconds"]),
                    unit_price=video_price,
                    price_verified_on=video_slot.verified_on,
                    storage_key=take_key,
                )
            )
            print(f"  take {index + 1}/{args.takes}  {take.name}")

        scores: dict[Path, tuple[float | None, float | None]] = {}
        if not shot["face_expected"]:
            # Nothing to rank on: no face to score and no swing to measure. First take
            # stands as a placeholder and a human picks, as on every faceless shot.
            pick = takes[0]
            print(f"  picked    {pick.name} (no criterion; a human picks)")
        else:
            measured = [
                measure(
                    t,
                    embedder._detector,
                    embedder._predictor,
                    embedder=embedder,
                    reference=reference,
                )
                for t in takes
            ]
            for m in measured:
                print(
                    f"    {m.path.name}: cov {m.coverage:>4.0%}  "
                    f"{m.frames_below(threshold)} below  mean {m.identity_mean:.5f}  "
                    f"roll {m.roll_swing_deg:.1f}d"
                )
            scores = {m.path: (m.identity_min, m.identity_mean) for m in measured}
            usable = [m for m in measured if m.coverage >= 0.6 and not m.frames_below(threshold)]
            best = min(usable or measured, key=lambda m: (m.frames_below(threshold), -m.coverage))
            pick = best.path
            print(
                f"  picked    {pick.name}"
                f"{'' if usable else '  (NONE passed outright; best of a bad set)'}"
            )
        for take in takes:
            identity_min, identity_mean = scores.get(take, (None, None))
            row = rows[take]
            if row is None:
                continue
            recorder.rescore(
                row,
                identity_min=identity_min,
                identity_mean=identity_mean,
                status="ready" if take == pick else "auto_rejected",
                embedding_model=embedder.model if identity_mean is not None else None,
            )
        chosen.append((shot, pick))

    # ------------------------------------------------------------- dialogue --
    synced: dict[str, Path] = {}
    for shot, pick in chosen:
        if not shot["line"]:
            continue
        name = shot["name"]
        bill(
            (voice_price * Decimal(len(str(shot["line"]))) / Decimal(1000)).quantize(
                Decimal("0.000001")
            ),
            f"{name} voice",
        )
        audio = speak(
            client,
            voice_slot,
            config.persona.persona.voice,
            str(shot["line"]),
            args.out / f"{name}_line.mp3",
        )
        padded = pad_to(audio, duration_of(pick), args.out / f"{name}_line_padded.mp3")
        video_key = key_for(persona_id, "take", f"bunker-{name}.mp4")
        audio_key = key_for(persona_id, "voice", f"bunker-{name}.mp3")
        storage.put(video_key, pick.read_bytes(), content_type="video/mp4", overwrite=True)
        storage.put(audio_key, padded.read_bytes(), content_type="audio/mpeg", overwrite=True)
        recorder.voice(
            name,
            text=str(shot["line"]),
            voice_id=str(config.persona.persona.voice.voice_id),
            provider=str(voice_slot.backend),
            storage_key=audio_key,
            units=Decimal(len(str(shot["line"]))) / Decimal(1000),
            unit_price=voice_price,
            price_verified_on=voice_slot.verified_on,
        )

        def presigned(v: str = video_key, a: str = audio_key) -> tuple[str, str]:
            return storage.presign_get(v, expires_in=3600), storage.presign_get(a, expires_in=3600)

        take_url, voice_url = presigned()
        assert sync_slot.model is not None
        out = args.out / f"{name}_synced.mp4"
        bill(sync_price * Decimal(shot["seconds"]), f"{name} lip sync")
        lip_sync(
            client,
            queue_root=QUEUE_ROOT,
            model=sync_slot.model,
            video_url=take_url,
            audio_url=voice_url,
            base=dict((sync_slot.request or {}).get("base") or {}),
            dest=out,
            refresh_urls=presigned,
        )
        synced[name] = out
        # A lip-synced clip is a derived take: same shot, different model, its own bill.
        # `cost_ledger.ref_table` has no "lipsync" value and inventing one would put this
        # spend outside the vocabulary the ledger is checked against, so it is recorded
        # as the generation it is, with the model naming what produced it.
        synced_key = key_for(persona_id, "take", f"bunker-{name}-synced.mp4")
        storage.put(synced_key, out.read_bytes(), content_type="video/mp4", overwrite=True)
        recorder.take(
            name,
            keyframe=frame_row,
            provider=str(sync_slot.backend),
            model=str(sync_slot.model),
            prompt=str(shot["line"]),
            params={"kind": "lipsync", "source": video_key},
            duration_s=duration_of(out),
            units=Decimal(shot["seconds"]),
            unit_price=sync_price,
            price_verified_on=sync_slot.verified_on,
            storage_key=synced_key,
            status="ready",
        )
        print(f"synced      {out.name}")

    # ------------------------------------------------------------- assembly --
    cuts = []
    lengths = []
    for shot, pick in chosen:
        path = synced.get(shot["name"], pick)
        cuts.append((path, shot["name"], shot["name"], bool(shot["line"])))
        lengths.append(duration_of(path))
    edl = edit_list(cuts, aspect="9:16", audio="keep_source")
    rough = assemble(edl, args.out / "rough.mp4")
    print(f"\nrough cut   {rough.path.name}  {duration_of(rough.path):.2f}s")

    final = apply_disclosure(
        rough.path, args.out / "final.mp4", overlay=config.persona.persona.disclosure.overlay
    )
    cues: list[Cue] = []
    offset = 0.0
    for (shot, _), length in zip(chosen, lengths, strict=True):
        if shot["line"]:
            cues += [
                Cue(text=c.text, start_s=c.start_s + offset, end_s=c.end_s + offset)
                for c in split_into_cues(str(shot["line"]), length)
            ]
        offset += length
    srt = write_srt(cues, args.out / "captions.srt")
    captioned = burn_in(
        final,
        cues,
        args.out / "final_captioned.mp4",
        overlay=config.persona.persona.disclosure.overlay,
    )
    print(f"captions    {captioned.path.name} ({len(cues)} cues) + {srt.name}")

    signed = sign(
        captioned,
        args.out / "final_signed.mp4",
        creds=creds,
        title="Mollie — The Bunker",
        persona_name=str(config.persona.persona.name),
        ingredients=[
            str(edit_slot.model),
            str(video_slot.model),
            str(voice_slot.model),
            str(sync_slot.model),
        ],
    )
    print(
        f"signed      {signed.path.name}  "
        f"({'trusted' if signed.trusted_chain else 'self-signed'}; valid, not trusted)"
    )

    verdict = assess(
        [
            ShotUnderTest(
                name=shot["name"],
                path=synced.get(shot["name"], pick),
                speaks=shot["speaks"],
                audio_source=shot["audio_source"],
                persona_present=shot["persona_present"],
                face_expected=shot["face_expected"],
                swing=cast("SwingKind | None", shot["swing"]),
            )
            for shot, pick in chosen
        ],
        reference=reference,
        embedder=embedder,
        threshold=threshold,
        disclosed=True,
        captioned=True,
        pose=pose,
    )
    print("\n" + "=" * 70)
    print(verdict.report())
    print("=" * 70)
    recorder.finish(status="assembled" if verdict.accepted else "review")
    spent = spend_this_month(session, dt.datetime.now(dt.UTC))
    ceiling = config.budget.budget.monthly_usd
    print(f"\nledger      ${spent} month-to-date against a ${ceiling} ceiling")
    print(f"deliverable  {signed.path}")
    return 0 if verdict.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
