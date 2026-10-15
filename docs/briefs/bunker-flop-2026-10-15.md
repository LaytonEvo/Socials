# Brief — "The Bunker" · 2026-10-15

**Logline.** She lines up a flop out of a greenside bunker, talks it up, doesn't get it
out, and the ball rolls back to her feet. Ends on a facepalm.

**Format.** YouTube Short / Reel. 9:16, ~15s, four shots. Captions burned in. Disclosure
overlay and C2PA manifest, as every piece.

---

## The thing to know before reading the shot list

**Two beats in this idea are the two things our evidence says do not render.**

**The swing.** A greenside bunker shot is a big swing for a short distance — hands at or
above shoulder height with an open face. That is a full athletic swing, and full swings
have failed **11 renders out of 11** across three attempts, two framings and a clean
keyframe (`swing-shot-2026-10-15.md`). Asking for it again would be asking for a twelfth.

**The facepalm.** A palm over the face removes the face, and the face is what the identity
scorer reads. The `react` take in the battery put a hand over her face and came back at
80% coverage with 3 frames under threshold; `hold_up` looking down scored 40%.

**Both are solvable by shooting around them, and the result is better comedy.**

The swing goes *in the cut* — address, cut to sand, cut back to her. That is how an editor
would do it anyway: the joke is the result, not the technique. And the facepalm is held
**short and late**, inside a shot that is otherwise face-to-camera, so coverage over the
whole clip stays above the 60% floor. She comes out from behind the hand at the end, which
restores the face and is funnier than holding it.

---

## Wardrobe

**Short white skort, fitted polo, visor.** Carried by the keyframe, not described in the
prompt — a clothing change stated in a prompt re-renders the person
(`wardrobe-control-2026-09-28.md`), which is why every keyframe is an *edit* of a master
still.

On "revealing": `config/persona.yaml` §clothing is the owner's own rule and it already
answers this. **Yes:** skorts, fitted polos, tennis-to-golf crossover, visor. **No:**
cropped tops, anything that reads gym-not-golf. The stated test is *"would a strict
members' club let her on the first tee."* A short skort and a fitted polo sit inside that;
a crop top does not. **Moving that line is a change to `persona-spec-v1.md` §5 and a
decision to record, not a prompt tweak** — flagging it rather than quietly doing either.

Known gap, unchanged: nothing measures wardrobe continuity between shots, and the model
has changed her outfit mid-clip before. A human still has to watch for it.

---

## The golf

Getting this right is most of whether it reads as made by someone who plays.

- **Club: lob wedge**, 58–60°, face open. Not a "flop" in the strict sense — from sand it
  is a splash or explosion shot — but "flop it out" is what people say, so the dialogue can
  keep the word and the picture should show the right shot.
- **Open stance**, feet dug in, ball forward of centre, weight slightly on the lead side.
- **The club must NOT touch the sand at address.** Grounding it in a bunker is a two-stroke
  penalty and it is the single most recognisable tell in a golf clip. The club hovers.
- **The failure:** she catches it heavy. The ball pops up the face, catches the lip, and
  rolls back down to her feet. Unambiguous on camera and instantly familiar to anyone who
  has played.
- Greenside bunker, flag visible just over the lip so the distance reads as short.

---

## Shots

**Every shot is five seconds, because five is the model's floor.** This brief first asked
for 4s/3s/4s/4s. `video.golf_1080` advertises `durations_s: [5 … 15]` and takes nothing
shorter, so fifteen seconds is not renderable on this model and the piece is twenty. Any
tightening happens in the edit, never by sending a duration the model does not accept —
the build script refuses one rather than letting the provider round it silently.

### 1 — Setup · 5s · face to camera

**Camera** chest height, in front of her, slightly above. She stands in the bunker, lip and
flag behind her shoulder.
**Action** She looks at the camera and talks. Hands on the club, club not grounded.
**Dialogue** *"Right — greenside bunker, pin's just over the lip. This is where we find out
whether those lessons did anything."*
**Declares** `face_expected=True`, `persona_present=True`, `swing=None`.
**Evidence** This is the shot type that works: 0.970–0.980 identity, 100% coverage, the
only one the owner has approved.

### 2 — Address · 5s · face up at the end

**Camera** same position, a little wider, whole body in frame.
**Action** She settles over the ball, shuffles her feet into the sand, clubhead hovering
above it, then flicks her eyes up to the lens for a beat.
**Dialogue** none.
**Declares** `face_expected=True`, `persona_present=True`, **`swing="chip"`**.

A declaration here is not a description of what she does — she does not swing — it is the
instrument that catches it if the model makes her. The prompt says "she does not swing"
and prompts are worth nothing on this model; a declared `chip` makes hands above the
shoulder line a BLOCKING finding, so a full swing snuck into the address shot cannot pass
the gate silently. This is the one shot where that trap is both safe and useful: her hands
stay low at address by the nature of the position.
**Evidence** The address keyframe rendered cleanly on the swing attempt and on the putt;
"look up at the end" took the scorecard shot from 40% to 100% coverage.

### 3 — The result · 5s · nobody in frame

**Camera** low and tight on the sand, lip filling the top of frame.
**Action** A spray of sand. The ball pops up the face, clips the lip, checks, and rolls
back down to the bottom of the bunker. It comes to rest. Nothing else moves.
**Dialogue** none. Source sound kept if it is clean.
**Declares** `persona_present=False`, `face_expected=False`, `swing=None`.
**Evidence** The faceless golf cutaway works — the ball-to-hole shot came back with correct
golf on 15 October once the keyframe was clean.

### 4 — Facepalm · 5s · face to camera

**Camera** back to shot 1's position.
**Action** She watches the ball roll back. A beat of disbelief, straight down the lens.
Palm goes to her face for about a second — **not longer** — then she drops it and looks
back at the camera, defeated.
**Dialogue** *"...They did not."*
**Declares** `face_expected=True`, `persona_present=True`, `swing=None` — **deliberately
not declared.** The facepalm puts a hand above the shoulder line by design, which is
exactly what a swing declaration refuses. Declaring one here would block the shot for
doing what this brief asks it to do. Shot 2 carries the trap instead.
**Evidence** The risk shot. A second of occlusion in five leaves ~80% coverage, above the
60% floor; `celebrate` showed that big expression changes cost identity, so the beat is
played dry rather than broad.

---

## Cost

Four keyframes at $0.08, several takes each because that is production rather than
science, voice on two shots, lip sync on two.

Built at 1080P on the owner's instruction. The figures below are what the cost guard
estimated from `config/providers.yaml`, not an approximation:

| | |
|---|---|
| 4 keyframes at $0.08, before redraws | $0.32 |
| 3 takes × 4 shots × 5s at $0.08/s | $4.80 |
| voice on shots 1 and 4 | $0.05 |
| lip sync on shots 1 and 4, 10s at $0.096/s | $0.96 |
| **estimate** | **$6.13** |

Up from the ~$5.10 quoted when this brief was written, for two reasons stated plainly:
the 5s floor adds a second to every shot, and that earlier figure was a guess rather than
the guard's arithmetic. A redraw adds $0.08 each; the run was given an $8 budget to leave
room for them.

---

## If the swing has to be on screen

It is the one thing here that money will not currently buy. The route is
`minimax/h3-max/recast` over real footage of a real bunker shot — golf correct by
construction, $0.45/s at 1080p — which needs a clip and a signed release
(`footage-licensing-2026-10-15.md`). Everything above is designed so the piece works
without it.
