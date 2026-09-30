"""Assemble one short golf piece end to end, from a shot list to a disclosed render.

A rehearsal for tasks 3.1 to 3.10 rather than the production pipeline: the shot list is a
literal below rather than generated (3.1), and there is no review step (3.5). What it
does exercise for real is keyframe -> clip -> edit list -> assembly -> disclosure, on
golf content rather than on identity-test prompts.

**The audio is dropped, deliberately.** The video model generates a soundtrack
unconditionally, in an unidentified language nobody chose. Until the voice layer exists
(3.6), silence is the honest output — see `AudioPolicy` in the assembler.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.identity.embedder import DlibEmbedder
from app.pipeline.assembler import assemble, duration_of, edit_list
from app.pipeline.disclosure import apply_disclosure
from app.pipeline.golf import apply_house_style
from app.pipeline.golf import check as check_golf
from app.pipeline.lipsync import lip_sync, should_lip_sync
from app.pipeline.sfx import generate_sound
from app.pipeline.takes import measure, steadiest
from app.pipeline.voice import pad_to
from app.providers.fal import QUEUE_ROOT, api_key
from app.storage.keys import key_for
from app.storage.s3 import S3Storage, bucket_from_env
from scripts.evaluate_lora import generate as generate_image
from scripts.train_lora import persona_storage_id
from scripts.video_identity_test import submit_clip

ROOT = Path(__file__).resolve().parent.parent


#: The shot list. Golf content, in her clothes, on a course — which is what the persona
#: is for. Each entry is a still prompt, the motion applied to it, and what she says.
#:
#: **The lines are observational, not instructional, and that is deliberate.** ADR 0009
#: settled that this persona has no golf knowledge base behind her, so putting swing
#: advice in her mouth would be inventing expertise she does not have and cannot cite.
#: Personality is in scope; coaching is not.
#:
#: **Every still prompt states its framing, and that is not decoration.** The first
#: version of this list did not, and the model answered "walking along a fairway" with a
#: wide shot in which her face was a few dozen pixels: face coverage across the piece
#: fell to 0.45 and five frames scored below threshold. The identity layer was fine —
#: there was simply not enough face to measure. Apparent face size is the variable the
#: spike's condition matrix kept finding underneath its other results, and a shot list
#: that leaves it to the model is one that will sometimes produce unmeasurable footage.
class Shot(TypedDict):
    """One entry in the shot list. Typed because `face_forward` drives real spend."""

    name: str
    still: str
    motion: str
    label: str
    face_forward: bool
    line: str
    #: What the world sounds like in this shot. Never speech — see app/pipeline/sfx.py.
    sound: str


SHOTS: list[Shot] = [
    {
        "name": "01_intro",
        "still": "a photo of {w}, a young woman in a white golf polo and visor, "
        "head and shoulders, standing on a golf course fairway, smiling at "
        "the camera, golden hour, shallow depth of field",
        # She MUST be speaking in the source take, and that is a property of the
        # lip-sync model rather than a preference. Asked to sync a take generated with
        # "mouth closed", the provider refuses outright:
        #
        #     No speech detected in the input video, please try a different video
        #
        # It replaces speech; it does not animate a still mouth. So the video model
        # animates her talking in its own invented language and the sync swaps which
        # words the mouth is forming. Verified 2026-09-30, at no cost — the refusal
        # comes back as a 422 before any GPU runs.
        #
        # NOT "small natural head movements", which was in the first version and
        # produced a take that tilted and rolled throughout. That reads as a glitch
        # rather than as life, and it was wrongly blamed on the sync, which is visibly
        # steadier than its own source.
        "motion": "she looks into the lens and talks to camera. Her head stays "
        "completely still and upright throughout, no tilting, no turning, no nodding. "
        "Shoulders still. Only her lips and her hair move. Camera locked off.",
        "label": "opening — to camera on the fairway",
        "face_forward": True,
        # ADR 0009 does NOT forbid her knowing golf — §1 says the model writing her
        # words already has the rules, the etiquette and the equipment, and the
        # decision was against building a RETRIEVAL CORPUS. I read it as "keep golf out
        # of her mouth" and wrote three lines of nothing. That was my misreading.
        #
        # What the ADR does constrain is REGISTER: spec §1 has her a 14 handicap,
        # "not a coach, not a pro", and §4 is pointed about men explaining her own
        # swing to her. So she talks about golf the way a decent amateur does — from
        # her own round, occasionally wrong — and never instructs.
        "line": "Right, first tee, and there's water left the whole way down. "
        "Which is exactly where I'm going to hit it.",
        "sound": "",
    },
    {
        "name": "02_walk",
        # Framed AWAY from her face, and that is the fix rather than a style choice.
        # The video model animates speech unconditionally and will not be talked out of
        # it: a take prompted "lips closed, not speaking" came back with MORE mouth
        # movement than the talking take (29.31 against 23.10, measured inside the
        # detected face box). Since b-roll is silent, a visible mouth means she is
        # mouthing to nobody. So b-roll shows what b-roll actually shows — her from
        # behind, the bag, the course — and the problem stops existing.
        # "full-size" and "clubs above her shoulder" because the first version said
        # only "a golf bag" and produced something the size of a pencil case hanging at
        # her hip. A tour bag is nearly as tall as she is and the club heads stand well
        # above the shoulder; without saying so the model renders a token bag shape.
        "still": "a photo of {w}, a young woman in golf clothing seen FROM BEHIND, "
        "walking away from the camera along a fairway, carrying a FULL-SIZE golf "
        "bag on her shoulder with a full set of clubs whose heads stand well above "
        "her shoulder, the bag is tall and reaches from her hip to above her head, "
        "medium shot, her face is not visible, trees ahead, afternoon light",
        "motion": "she walks away from the camera along the fairway, seen from behind, "
        "camera follows steadily at the same height",
        "label": "b-roll — walking the fairway",
        "face_forward": False,
        "line": "",
        "sound": "quiet golf course ambience, soft footsteps on grass, golf clubs "
        "rattling gently in a bag, distant birdsong, light breeze",
        # Not the putting surface — a bag never goes on a green, which is what the
        # first version of this shot rendered.
    },
    {
        "name": "03_swing",
        "still": "a photo of {w}, a young woman in a white golf polo and visor STANDING "
        "UPRIGHT at address over a golf ball, driver in both hands, MEDIUM "
        "SHOT from the waist up, face visible in profile, on the tee",
        # As above: silent shot, so she must not be mouthing words through it.
        "motion": "she takes the club back and swings through, full follow through, "
        "lips closed, not speaking, concentrating, camera static at chest height",
        "label": "the swing",
        "face_forward": False,
        "line": "",
        # The defect this fixes: a golf swing with no contact sound reads as broken.
        "sound": "a golf club swishing through the air then a sharp solid crack as it "
        "strikes the ball, followed by quiet course ambience and birdsong",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "piece-golf")
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true", help="reuse what is on disk")
    parser.add_argument(
        "--sync-slot",
        default="primary",
        help="which lipsync provider slot to use: primary (heygen) or alternative",
    )
    parser.add_argument(
        "--takes",
        type=int,
        default=3,
        help="takes to generate for face-forward shots before picking on head stability",
    )
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    artefact = json.loads((ROOT / "spike" / "runs" / "lora" / "artefact.json").read_text())
    guard = BudgetGuard(config.budget, config.providers)

    image_slot, _, _ = guard.price("image", "lora_inference")
    video_slot, _, _ = guard.price("video", "golf")
    scale = float(image_slot.options.get("lora_scale", 1.0))
    seconds = Decimal(str((video_slot.request or {}).get("duration_s", 5)))

    still_cost = guard.estimate("image", "lora_inference", Decimal(len(SHOTS)))
    clip_cost = guard.estimate("video", "golf", seconds * len(SHOTS))
    estimate = still_cost + clip_cost

    print(f"shots         {len(SHOTS)}")
    for s in SHOTS:
        print(f"  {s['name']:<10} {s['label']}")
    print(f"\nkeyframes     {image_slot.model} at scale {scale} = ${still_cost}")
    print(f"clips         {video_slot.model} = ${clip_cost}")
    print(f"ESTIMATE      ${estimate}")
    chars = sum(len(str(s["line"])) for s in SHOTS)
    voice_cost = guard.estimate("voice", "primary", Decimal(chars) / Decimal(1000))
    estimate += voice_cost
    print(f"voice         {chars} characters = ${voice_cost}")
    sync_slot, _, _ = guard.price("lipsync", args.sync_slot)
    to_sync = [
        s
        for s in SHOTS
        if should_lip_sync(face_forward=s["face_forward"], has_dialogue=bool(s["line"])).sync
    ]
    sync_cost = guard.estimate("lipsync", args.sync_slot, seconds * len(to_sync))
    estimate += sync_cost
    print(f"lip sync      {sync_slot.model}")
    print(
        f"              {len(to_sync)} of {len(SHOTS)} shots (face-forward + dialogue) "
        f"= ${sync_cost}"
    )
    print("audio         the model's own soundtrack is dropped; her voice replaces it")
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0

    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    embedder = DlibEmbedder(config.providers)
    headers = {"Authorization": f"Key {api_key()}"} if api_key() else {}
    client = httpx.Client(timeout=300.0, headers=headers)
    image_base = dict((image_slot.request or {}).get("base") or {})
    video_shape = dict(video_slot.request or {})

    clips: list[tuple[Path, str, str, bool]] = []
    for shot in SHOTS:
        keyframe = args.out / f"{shot['name']}_key.png"
        clip = args.out / f"{shot['name']}.mp4"

        if not (args.skip_generate and keyframe.is_file()):
            prompt = apply_house_style(shot["still"].format(w=artefact["trigger_word"]))
            for problem in check_golf(prompt):
                raise SystemExit(
                    f"{shot['name']}: shot prompt contains {problem.rule} — "
                    f"{problem.why}. Fix the prompt rather than the picture."
                )
            print(f"\n[{shot['name']}] keyframe")
            assert image_slot.model is not None
            url = generate_image(
                client, image_slot.model, prompt, artefact["weights_url"], scale, image_base
            )
            keyframe.write_bytes(client.get(url, timeout=180.0).content)
            print(f"  -> {keyframe.name}")

        if not (args.skip_generate and clip.is_file()):
            assert video_slot.model is not None
            # Several takes for the shot people actually watch her face in, then pick
            # on measured head stability. The prompt cannot hold her head still and a
            # seed is accepted but not honoured, so selection is the only lever — and
            # at $0.0625 a take against $0.50 to sync one, choosing before syncing is
            # eight times cheaper than syncing the wrong take.
            wanted = args.takes if shot["face_forward"] else 1
            candidates: list[Path] = []
            for take in range(wanted):
                candidate = args.out / f"{shot['name']}_take{take}.mp4"
                print(f"[{shot['name']}] clip, take {take + 1} of {wanted}")
                url = submit_clip(client, video_slot.model, shot["motion"], keyframe, video_shape)
                candidate.write_bytes(client.get(url, timeout=300.0).content)
                candidates.append(candidate)

            if wanted == 1:
                candidates[0].replace(clip)
            else:
                measured = [measure(c, embedder._detector, embedder._predictor) for c in candidates]
                for m in measured:
                    print(
                        f"       {m.path.name}: head roll sd {m.head_roll_sd_deg:.2f} deg, "
                        f"{m.frames_with_face} frames with a face"
                    )
                best = steadiest(measured)
                print(f"       picked {best.path.name} on head stability")
                best.path.replace(clip)
            print(f"  -> {clip.name} ({clip.stat().st_size / 1048576:.2f} MB)")

        clips.append((clip, f"piece-golf/{shot['name']}", str(shot["label"]), False))

    # ---------------------------------------------------------- her voice --
    voice = config.persona.persona.voice
    if not voice.voice_id:
        raise SystemExit("persona.voice.voice_id is not set; there is no voice to speak in")
    voice_id = str(voice.voice_id)
    voice_slot, _, _ = guard.price("voice", "primary")
    voice_shape = dict(voice_slot.request or {})

    spoken_lines: dict[str, Path] = {}
    for shot in SHOTS:
        text = str(shot["line"])
        if not text:
            continue
        audio = args.out / f"{shot['name']}_voice.mp3"
        if not (args.skip_generate and audio.is_file()):
            assert voice_slot.model is not None
            arguments: dict[str, Any] = {
                str(voice_shape.get("text_field", "text")): text,
                str(voice_shape.get("voice_field", "voice")): voice_id,
                **dict(voice.options or {}),
            }
            r = client.post(f"{QUEUE_ROOT}/{voice_slot.model}", json=arguments)
            r.raise_for_status()
            sub = r.json()
            for _ in range(120):
                if client.get(sub["status_url"]).json().get("status") in {
                    "COMPLETED",
                    "FAILED",
                    "ERROR",
                }:
                    break
                time.sleep(3)
            payload = client.get(sub["response_url"]).json()
            url = str((payload.get("audio") or {}).get("url") or "")
            if not url:
                raise SystemExit(f"TTS returned no audio: {str(payload)[:300]}")
            audio.write_bytes(client.get(url, timeout=120.0).content)
        spoken_lines[str(shot["name"])] = audio
        print(f"  voice {shot['name']}: {text!r}")

    # ----------------------------------------------------------- lip sync --
    # Task 3.7's rule, applied per take rather than to the assembled piece: sync is a
    # property of a shot, not of a render.
    sync_base = dict((sync_slot.request or {}).get("base") or {})
    print(f"  using lipsync slot '{args.sync_slot}': {sync_slot.model}")
    storage = S3Storage(bucket=bucket_from_env())
    persona_id = persona_storage_id(config.persona.persona.id)
    synced: set[str] = set()

    for shot, (clip_path, source_id, label, _) in zip(SHOTS, list(clips), strict=True):
        name = str(shot["name"])
        decision = should_lip_sync(
            face_forward=bool(shot.get("face_forward")), has_dialogue=bool(shot.get("line"))
        )
        print(f"  sync {name}: {'YES' if decision.sync else 'no '} — {decision.reason}")
        if not decision.sync:
            continue
        dest = args.out / f"{name}_synced.mp4"
        if not (args.skip_generate and dest.is_file()):
            # Presigned rather than a public upload: the provider must fetch these, and
            # fal's own CDN is public (ADR 0006).
            # The provider refuses inputs whose durations differ much, so the line is
            # padded with trailing silence to the length of the shot it belongs to.
            padded = pad_to(
                spoken_lines[name],
                duration_of(clip_path),
                args.out / f"{name}_voice_padded.mp3",
            )
            video_key = key_for(persona_id, "take", f"{name}-take.mp4")
            audio_key = key_for(persona_id, "voice", f"{name}-line.mp3")
            storage.put(video_key, clip_path.read_bytes(), content_type="video/mp4", overwrite=True)
            storage.put(audio_key, padded.read_bytes(), content_type="audio/mpeg", overwrite=True)
            assert sync_slot.model is not None
            lip_sync(
                client,
                queue_root=QUEUE_ROOT,
                model=sync_slot.model,
                video_url=storage.presign_get(video_key, expires_in=3600),
                audio_url=storage.presign_get(audio_key, expires_in=3600),
                base=sync_base,
                dest=dest,
            )
        # The synced take keeps its own audio; that is the only track that matches
        # the mouth it was generated against.
        clips[SHOTS.index(shot)] = (dest, source_id, label, True)
        synced.add(name)
        print(f"       -> {dest.name}")

    # ------------------------------------------------------- sound effects --
    # For shots where nobody speaks. Silence was honest and wrong: a swing with no
    # contact sound reads as broken.
    sfx_slot, _, _ = guard.price("sfx", "primary")
    sfx_base = dict((sfx_slot.request or {}).get("base") or {})
    for index, shot in enumerate(SHOTS):
        prompt = str(shot.get("sound") or "")
        if not prompt:
            continue
        name = str(shot["name"])
        clip_path = clips[index][0]
        dest = args.out / f"{name}_sound.mp4"
        if not (args.skip_generate and dest.is_file()):
            key = key_for(persona_id, "take", f"{name}-for-sound.mp4")
            storage.put(key, clip_path.read_bytes(), content_type="video/mp4", overwrite=True)
            assert sfx_slot.model is not None
            generate_sound(
                client,
                queue_root=QUEUE_ROOT,
                model=sfx_slot.model,
                video_url=storage.presign_get(key, expires_in=3600),
                prompt=prompt,
                duration_s=duration_of(clip_path),
                base=sfx_base,
                dest=dest,
            )
        clips[index] = (dest, clips[index][1], clips[index][2], True)
        print(f"  sound {name}: {prompt[:58]}...")

    # A synced take arrives carrying the audio its mouth was generated against, so the
    # assembler keeps that track rather than a separately-laid copy — the copy drifted,
    # because the sync stretches time slightly.
    #
    # Everything else stays silent. Laying her voice over a shot where she is visible
    # and NOT talking is worse than silence: the first cut of this piece had her
    # speaking over the swing with her mouth shut.
    edl = edit_list(clips, aspect="9:16", audio="keep_source")
    print(f"\nedit list     {len(edl.cuts)} cuts, {edl.duration_s:.2f}s, audio={edl.audio}")
    for shot, cut in zip(SHOTS, edl.cuts, strict=True):
        name = str(shot["name"])
        if name in synced:
            kind = "her voice"
        elif shot.get("sound"):
            kind = "ambience"
        else:
            kind = "silent"
        print(f"  {name:<10} {kind:<10} {cut.duration_s:.2f}s")
    rough = assemble(edl, args.out / "rough.mp4")

    final = apply_disclosure(
        rough.path, args.out / "final.mp4", overlay=config.persona.persona.disclosure.overlay
    )
    print(f"rough         {rough.path.name}")
    print(f"FINAL         {final.path.name}  '{final.disclosure_text}' at {final.position}")
    print(f"              {final.path.stat().st_size / 1048576:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
