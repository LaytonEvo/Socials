# The swing shot, measured: 11 full swings out of 11 — 2026-10-15

**Status:** measured result. Nothing shipped, nothing to pick from. $1.36 billed.

The owner asked for the swing shot, now that the keyframe is seam-screened (ADR 0018) and
the swing itself is measurable (ADR 0016).

## What was changed before trying again

The shot was withdrawn on 2026-10-01 for **two** reasons and only one was the swing:

1. The brief frames it down-the-line, from behind her. The scorer reads faces, so nothing
   here can confirm a shot of her back is her — and the render came back as a different
   woman. ADR 0012 blocks it, and still does.
2. It was a full swing from 30 yards.

So this did not re-run the withdrawn shot. **It reframed it front-on with her face in
shot**, which is the only framing a shot containing her can be verified in. That is a real
cost, not a free fix: it is not the shot the brief asked for.

The keyframe was screened for identity *and* seams, and passed: face **0.97039** against a
0.970 bar, seam 0.65 against a limit of 7.

## The result

Six takes, 5 seconds each, from a clean screened keyframe, with *"the club goes back only
to about waist height... It is a small controlled swing, not a full swing"* in the prompt.

| take | hand peak | verdict | face coverage | frames below | identity mean |
|---|---|---|---|---|---|
| take_0 | **1.62** | FULL SWING | 90% | 6 | 0.94515 |
| take_1 | **1.66** | FULL SWING | 70% | 4 | 0.94415 |
| take_2 | **1.66** | FULL SWING | 80% | 4 | 0.95188 |
| take_3 | **1.61** | FULL SWING | 80% | 5 | 0.94671 |
| take_4 | **1.74** | FULL SWING | 70% | 4 | 0.94352 |
| take_5 | **1.79** | FULL SWING | 50% | 2 | 0.95110 |

**0 of 6 on the swing. 0 of 6 on identity.** The shoulder line is 1.0; every take put her
hands two thirds of a torso above it. The identity threshold is 0.951; every take has
frames below it.

With the two earlier attempts, that is **11 renders out of 11 that played a full swing
when the prompt asked for waist height**, across three keyframes, two framings and a
seam-free source.

## What the frames show, which is worse than the number

I watched take_0. At the top of the backswing her **arms are straight out to her side with
the club vertical and her shoulders barely turned** — it is a lateral swipe, not a
backswing. The finish is a full-iron follow-through with the club wrapped behind her head,
which is the finish of a 150-yard shot, not a 30-yard pitch. The club also changes: a
wedge in the keyframe, a blade iron by the finish.

So the defect is not only *length*. The body mechanics are wrong in a way that no
measurement here was even asking about, and no prompt has moved.

## Two secondary findings

**Identity degrades in an action shot.** The talking shot scores 0.970–0.980 with 100%
coverage. The same persona swinging scores 0.944–0.952 with 50–90% coverage, because the
face is smaller, angled, and moving. **A swing shot is harder to verify as well as harder
to render**, which is worth knowing before any route is chosen.

**Wardrobe drifted.** Shot 1 is a white skirt; this keyframe came back in white trousers.
Continuity across a multi-shot piece is still unmeasured and still drifts.

## A mistake in this run worth recording

The first attempt produced a keyframe with her in profile at the edge of the frame, head
down, no usable face — seam 0.34, perfectly clean. **The script scanned for seams and
forgot to screen for identity**, which is what ADR 0011 exists for. Caught by looking at
the image before the takes ran; it cost $0.08 instead of $1.28. `make_swing.py` now screens
for both and redraws up to four times.

## What this says

The case for recasting real footage stops being an argument and becomes a count. Eleven
attempts, three keyframes, two framings, one clean source, one explicit instruction each
time — and every single render played a different shot from the one asked for.
`minimax/h3-max/recast` does not need to be told what a pitch looks like, because the
pitch in the source video already happened.

It still needs 10–30 seconds of the owner playing one.
