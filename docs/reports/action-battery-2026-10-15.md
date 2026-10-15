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

## The head-up re-run

Three actions re-shot with her eyes coming up. $0.84.

| action | coverage | below | identity | roll | verdict |
|---|---|---|---|---|---|
| `hold_up_lookup` | **100%** (was 40%) | **0** | 0.96792 | 17.0° | **holds** |
| `putt_lookup` | 60% (was 30%) | 4 | 0.94612 | 23.6° | off-identity |
| `mark_ball` | 100% (read_green had none) | 5 | 0.95051 | 23.4° | off-identity |

**`hold_up` is fixed.** Coverage went from 40% to 100%, zero frames below, and it now
holds outright. One line of prompt — *"she does not look down at the card"* — turned an
unverifiable shot into a passing one. That is the cheapest fix found on this project.

**The putt got more measurable and less good.** Coverage doubled, but identity fell from
0.96489 to 0.94612 and four frames went under. **The stroke stayed correct** — hands
peaked at -0.18, below the hip line, zero of 124 frames above the shoulder line. So the
golf survived the change and the face did not.

**`mark_ball` solved read_green's missing face** and landed five frames under.

### A relationship I was about to assert, and the data does not support

Lifting her head adds head roll, and the two worse results both roll about 23°, so the
obvious story is "roll costs identity". Across all seven measured actions the correlation
between head roll and identity mean is **+0.381 — the wrong sign**, driven entirely by
`club_throw`, which rolls 64.4° and has the *best* identity of anything measured.

    club_throw       0.97114   0 below   64.4°
    hold_up_lookup   0.96792   0 below   17.0°
    putt             0.96489   0 below    4.2°
    walk             0.95870   1 below   12.3°
    mark_ball        0.95051   5 below   23.4°
    putt_lookup      0.94612   4 below   23.6°
    celebrate        0.93457   9 below   11.6°

So there is no roll-to-identity law here. The three worst are a laugh, a head lift with an
expression change, and a crouch-to-stand — which *suggests* that changing expression and
posture costs identity where moving a limb does not. **One take per action cannot tell
that from luck**, and this report is not going to pretend otherwise.

## What to do next

1. ~~Re-run the head-down actions with the face coming up.~~ Done. It fixed `hold_up`
   outright and half-fixed the putt.
2. **Take more than one draw of each.** Everything above is n=1. The talking shot needed
   six takes to find a good one and this gave every action a single roll of the dice, so
   "this action is hard" and "this draw was unlucky" are not separable. Four takes each of
   `hold_up_lookup`, `putt_lookup`, `lean` and `walk` is about $2 and would settle it.
3. **Calibrate a full-body keyframe bar** against the body stills, so a correct still is
   not refused three times again.
4. **Leave `celebrate` alone.** Big fast motion without a club is a real failure, and
   there is no obvious lever.
