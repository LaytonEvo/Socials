# Veo breaks when the face leaves frame and comes back — 2026-09-24

The owner assessed all five coverage-probe clips by eye. Two are bad. **The
split is predicted exactly by one property: whether the face leaves frame and
returns.**

| Shot | Face leaves frame and returns | Owner |
|---|---|---|
| `approach_camera` | **yes** | **bad** |
| `glance_back` | **yes** | **bad** |
| `turn_away_hold` | leaves, never returns | fine |
| `look_down_and_up` | never leaves | fine |
| `profile_to_camera` | never leaves (turns *to* camera) | fine |

Five for five. `profile_to_camera` is the discriminating case: it turns toward
camera through the same angular range as the broken clips, with the face
visible in all 32 frames, and it is fine. So it is not *turning toward camera*
that breaks. It is the round trip through an occlusion.

The mechanism is the one measured in
`identity-gate-blind-spot-2026-09-24.md` §3(d): nothing carries the head's
state across the window where the model cannot see her, so the return is
reconstructed rather than continued. The owner's description of
`approach_camera` — *"her head position on the turn back doesn't match the
head position when she turns away ... her head is tilting the other way on the
return"* — is what a reconstruction rather than a continuation looks like.

## The identity gate cannot see any of this

Every one of the five clips has healthy identity. `glance_back`, which the
owner rejected, scores 0.964–0.993 across thirteen readable frames with a
single dip to 0.953 — and 0.953 is **above her own worst reference still**
(`master_010`, 0.95041), so it is within the range of her own photographs.

| Shot | Longest run below threshold | Gate verdict | Owner |
|---|---|---|---|
| `approach_camera` | 0% | **pass** | **bad** |
| `glance_back` | 33% | indeterminate | **bad** |
| `look_down_and_up` | 17% | pass | fine |
| `profile_to_camera` | 0% | pass | fine |
| `turn_away_hold` | 0% | indeterminate | fine |

**After the threshold correction, the presence-rule rewrite and the statistic
replacement, the gate rejects neither clip the owner rejected.** That is not a
regression in those fixes — each was correct, and the gate is now right about
identity. Identity was never what was wrong with these clips.

`glance_back` reaches `indeterminate` only because the face leaving frame
dropped its coverage below the floor. That is a useful accident and not a
detection: the failure mode correlates with low coverage, so the human-review
lane catches some of it. It did not catch `approach_camera`, whose face left
frame for a single sampled frame and which passed at 87.5% coverage.

## What to do with this

**A shot-list constraint, available now.** Until S0.4 supplies per-shot
keyframes, do not commission shots where the face leaves frame and returns.
Shots where she turns away and stays away, turns toward camera, or never turns
are all sound on this evidence.

**The golf battery is exposed.** `reaction`, `ball_flight` and the full-swing
shots all plausibly take the face out of frame and bring it back. They are
among the eleven still blocked on S0.4, and this predicts they will fail for a
reason that has nothing to do with the LoRA.

**Gate A.** BUILD_PLAN task 3.4's auto-reject cannot use identity scoring to
catch this. A detector would have to compare across the occlusion using
something other than the face — the one signal that is absent exactly when it
is needed.

## Limits

Five clips, one provider, one duration (4 s), all animated from close-up
keyframes. The pattern is 5/5 but it is a hypothesis, not a law, and the
cheapest way to break it is more shots of each kind.

**A gap this probe does not close:** none of the five clips exhibits sustained
identity drift — the failure the gate exists for. The 40% run allowance in
`score.py` is therefore still resting on the two different-woman clips and has
never been tested against a clip that drifts partway and stays drifted.
