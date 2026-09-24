# S0.7 — the golf format battery ran, and the plan's prediction was wrong

**13 of 13 formats generated, no refusals, $7.80. The owner rates all 13
usable, including all 7 the plan predicted would break.**

## What ran

| | |
|---|---|
| Prompt set | `GOLF_BATTERY`, all 13 formats |
| Takes | 1 (acceptance asks 2 — see Deviations) |
| Provider | `fal-ai/veo3.1/fast/image-to-video` |
| Keyframes | 6 master stills, rotated on refusal |
| Spend | $7.80 at the guard rate ($0.15/s), 13 x 4 s |

Nothing was refused. The previous attempt at this battery halted after four
shots; the difference is the keyframe rotation added earlier the same day,
which tries another still instead of giving a shot up.

## The finding

`docs/decisions/0003-content-format-constraints.md` and `BUILD_PLAN` Section 6
predict that full swing and ball flight break on club-and-ball physics, and
seven formats are tagged `hard` on that basis. **All seven are usable.**

Owner's verdict, verbatim: *"They all look good but the golf club details and
ball are a bit off."*

| Rated | Count |
|---|---|
| 5 — no defect noted | 6 |
| 4 — usable, club/ball detail off | 7 |
| below 4 | **0** |

So the constraint is not "these formats are impossible". It is "club and ball
detail is imperfect in every shot that contains them". That is a far weaker
constraint and it changes what this persona can post.

The failure tags (`club_distortion|ball`) are attributed from each prompt
containing a club or ball, not rated shot by shot — the owner's comment was
general. Recorded that way in `battery_ratings.csv`.

## The identity gate disagreed with the owner on 6 of 13, always by being stricter

| Shot | Gate | Owner |
|---|---|---|
| `equipment_closeup` | **fail** (4/8 frames below) | usable |
| `putting_stroke` | **fail** (4/5 below) | usable |
| `full_swing_address` | **fail** (5/8 below) | usable |
| `chip` | indeterminate, min **0.8352** | usable |
| `full_swing_top` | indeterminate, 25% coverage | usable |
| `ball_flight` | indeterminate, 25% coverage | usable |

This is the opposite error from the morning, when the gate passed clips the
owner rejected. At this operating point it would auto-regenerate three usable
clips and send three more to a human.

**`chip` deserves its own look.** Its minimum is 0.8352 — *below the negative
controls*, where a woman Veo invented over a blank landscape scored 0.846. By
every measure available, the frames the detector could read are not her. The
owner rates the clip usable. Those two statements are not obviously
compatible, and the likeliest explanation is that the face is small or blurred
in those frames, so a human reads the clip as fine while the scorer reads the
face as wrong.

That is not settled here, and it should not be settled by assumption: it
decides whether the gate is too strict at speed and distance, or whether
identity genuinely drifts in shots nobody is scrutinising. Either answer
matters.

## The club/ball defect, and not planning on it going away

The owner's reading is that improving models will fix it. That may well be
right, but it is a hope and not a plan, and the spike should not hand Gate A a
constraint that depends on it. Mitigations that exist **now**:

- **Frame it out.** The defect is in small, fast-moving objects. Tighter
  framing on her, with the club partly or wholly out of shot, removes it
  without removing the format.
- **Cut around contact.** Social video is cut fast. Ball contact is the
  hardest instant to render and the easiest second to skip.
- **Prefer the shots that do not need it.** Six formats carry no club or ball
  at all and were rated 5.
- **Re-take.** Generation is stochastic; a second take at $0.60 is cheap
  relative to accepting a visible defect.

## Deviations from the acceptance criteria

S0.7 asks for **2 takes on 2 providers**. This run is **1 take on 1 provider**.

- One provider because only fal is configured; the `budget` video slot is
  still null.
- One take because it is cheaper to learn which formats work and re-take the
  failures than to pay double up front. Nothing failed, so the second take is
  now a question about *variance* rather than about coverage: a single good
  take does not prove a format is reliably good, and 13 more takes cost $7.80.

Both gaps are real and neither is closed by this run.

## Bearing on Gate A

- §3.3 item 5 (format matrix, usable rate, dominant failure tags) is now
  answerable: **13/13 usable, dominant tags `club_distortion` and `ball`.**
- ADR 0003 needs amending. Its prediction was tested and did not hold.
- §3.3 item 2 (pass rate by condition) is still the identity matrix's job, not
  this battery's.
- The 6/13 disagreement above belongs in §3.3 item 3, which exists precisely
  to ask whether the scorer agrees with a human eye. It does not, in a
  specific and now-measured direction.
