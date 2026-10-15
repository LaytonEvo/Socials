# What Mollie can be shown doing — measured, 2026-10-15

**Status:** measured. Eight actions, one take each, plus two re-runs. About **$3.30** billed.
Nothing disclosed, nothing signed: these are measurements, not renders.

Eleven swing renders out of eleven had narrowed the product to "she talks and we cut
away", and none of that narrowing was measured. This measures it.

## The table

| action | verdict | face coverage | frames below | identity mean | head roll |
|---|---|---|---|---|---|
| hold_up | unmeasurable | 40% | 0 | **0.97477** | — |
| react | off-identity | 80% | 3 | 0.96044 | — |
| lean | off-identity | 100% | 2 | 0.96301 | — |
| read_green | **no keyframe** | — | — | — | — |
| putt | unmeasurable | 30% | **0** | 0.96489 | **4.2°** |
| walk | off-identity | 100% | 1 | 0.95870 | 12.3° |
| celebrate | off-identity | 90% | **9** | **0.93457** | 11.6° |
| club_throw | **holds** | 100% | 0 | 0.97114 | 64.4° |

Read as "1 of 8 holds", that looks grim. Read properly, it is not what it says.

## The real finding: the constraint is her head, not the action

**Every unmeasurable result is an action where she looks down.** `hold_up` 40%,
`putt` 30%, `read_green` no detectable face at all. The scorer reads faces; a golfer
looking at a ball is not presenting one. That is not the motion failing — in `hold_up`
the frames that *were* measurable scored **0.97477 with zero below threshold**, which is
as good as the talking shot.

**The off-identity results are mostly marginal.** `walk` is one frame under out of a
hundred-percent-covered clip; `lean` is two. Against a 0.951 threshold with means of
0.958–0.963, those are near misses, not collapses.

**One result is a genuine identity failure.** `celebrate`: nine frames below, mean
0.93457. Watched: the laugh distorts her face and the model drifts off-model. Big fast
motion *without* a club is the thing that actually broke.

**And one is genuinely good.** `club_throw` holds identity outright at 100% coverage —
but with **64.4° of head roll**, which the gate would raise for review and a human would
probably call a glitch.

## The putt works, and that is the headline

`putt` renders a correct putting stroke. Measured over every frame:

> hands peaked at **-0.19** — below the hip line, never rising — with **0 of 124 frames**
> above the shoulder line, and **100% pose coverage**.

Head roll 4.2°, the steadiest of anything measured today. Watched it: putter, ball, hole,
head down, hands low, one glove. The golf is right.

**So club motion is not categorically broken.** A full swing fails every time; a putting
stroke renders correctly first try. The failure was never "she cannot hold a club", it was
"she cannot make a full athletic swing" — a much smaller claim, and one that leaves most
of a golf personality's repertoire intact.

Its only problem is 30% face coverage, because putting means looking at the ball. The gate
would refuse it, correctly, as unverifiable — and that refusal is now the binding
constraint on a shot that is otherwise good.

## A false negative I caused

`putt` and `read_green` were not tested in the first run because **the keyframe bar
refused them**. The putt still was refused three times at 0.95944, 0.95316 and 0.96367
against a bar of 0.970 — and it is a perfectly good still: her at address, head up, putter,
ball, hole with flag.

**0.970 was calibrated on head-and-shoulders stills.** A full-body action keyframe puts the
same face across a fraction of the pixels and scores lower for that reason alone. Applying a
portrait threshold to a full-body population is this project's recurring error, in a fourth
place. Re-run at the video threshold the same scene passed at **0.98044** on the first draw.

`--keyframe-bar` now exists, floored at the video threshold so a keyframe can never be
worse than the renders it seeds. **The proper fix is a calibrated full-body keyframe bar**,
against `spike/data/body/` rather than the portraits.

## Golf is still wrong in the renders

Watched, not measured: `hold_up` puts a glove on **both hands** — which `golf.py` has a
rule about, a rule that reads prompts and so never fired. `club_throw` has her holding
**two clubs**, a wedge and a putter. Scene content remains unmeasured and remains wrong,
exactly as the standing REVIEW line says.

## What to do next

1. **Re-run the head-down actions with the face coming up.** "She strokes the putt, then
   looks up at the camera" buys coverage in the back half without touching the gate. A
   prompt change, about $0.60 to test, and it is the difference between a good putt shot
   being refused and being usable.
2. **Calibrate a full-body keyframe bar** against the body stills, so a correct still is
   not refused three times again.
3. **Leave `celebrate` alone.** Big fast motion without a club is a real failure, and
   there is no obvious lever.
