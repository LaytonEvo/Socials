# S0.5 first live video run — 2026-09-23

The first real clips this project has generated. **The headline is not the
identity result — it is that three of the five cells attempted could not be
generated at all.**

**Provider:** `fal-ai/veo3.1/image-to-video`, audio off, 720p, 4s
**Scorer:** dlib ResNet, threshold 0.9748 (ADR 0004, calibration reproduced locally)
**Keyframes:** her 28 Midjourney stills, cropped to 9:16 deliberately (ADR 0006)
**Budget:** $15 cap, $3.20 reserved, 2 clips generated

## What happened

| # | Cell | Result |
|---|---|---|
| 1 | front · medium · golden_hour · walking | **pass** |
| 2 | three_quarter · close · indoor · static | **never generated** — content policy |
| 3 | profile · wide · overcast · turning | **never generated** — 403 exhausted balance |
| 4 | three_quarter · wide · midday · turning | **fail**, 0.9183 |
| 5 | profile · medium · indoor · static | **never generated** — `no_media_generated` |

Stopped by the skip guard at three failures to generate, which is the intended
behaviour: past a third of the run, something systematic is wrong and
discovering it one paid cell at a time helps nobody.

## Finding 1 — generation reliability, not identity, is the live risk

**Two of five cells were refused for content or model reasons** (the third was
a transient billing flap that resolved by itself, and is not counted here).
That is a 40% refusal rate on prompts describing a clothed woman on a golf
course, with no pattern that suggests the prompts are at fault:

- `three_quarter · close · indoor · static` — "content flagged by a content
  checker"
- `profile · medium · indoor · static` — "the model did not generate the
  expected output for this prompt"

And the checker is **not deterministic**: the exact cell refused as cell 2 in
this run generated successfully in the previous one, same prompt, same
keyframe.

This is a feasibility problem independent of whether the face survives, and it
was invisible until real money met a real provider. A recurring publishing
schedule that loses two takes in five to a non-deterministic checker needs
either a different provider, a reworded prompt vocabulary, or an accepted
re-roll cost per clip — and that is an owner decision, not a tuning exercise.

**It also biases the measurement.** The cells that survive are not a random
sample of the cells attempted, so an identity pass rate computed over
survivors flatters whatever conditions the checker happens to permit. The
harness now reports never-generated cells separately from failures for exactly
this reason: missing evidence is not bad evidence.

## Finding 2 — the identity result, such as it is

Two clips is not a sample. What there is:

| Cell | Min similarity | Threshold | |
|---|---|---|---|
| front · medium · golden_hour · walking | ≥ 0.9748 | 0.9748 | pass |
| three_quarter · wide · midday · turning | 0.9183 | 0.9748 | fail |

The failure is substantial rather than marginal — 0.057 below, where the
threshold itself sits only 0.0018 under her weakest master still. A previous
run produced a near-miss at 0.9638 on a *close* shot, so the ordering so far is
close > medium > wide, which is the direction intuition predicts: less face in
frame, less to recognise.

**Do not conclude anything from this yet.** Two clips, one of each outcome, and
the axes are confounded with each other because the sample is too small to
separate them.

## What this cost

$3.20 reserved against the $15 cap for 2 clips. The ledger reserves at
$0.40/second (the with-audio rate fal's pricing API publishes) while the run
sends `generate_audio: false`, so the actual charge should be about half that.
Reconcile against the first real invoice — ADR 0006 records why the ledger is
an estimate rather than a bill.

Refused cells cost nothing, and are recorded at zero rather than skipped, so
the attempt stays reconcilable.

## What to do next

1. **Decide how to handle the refusal rate.** Options: raise
   `safety_tolerance` from fal's default of 4 (an owner decision, deliberately
   not taken here); reword the condition vocabulary, accepting that the prompt
   fragments *are* the matrix variables so changing them changes what is
   measured; try a different model; or accept a re-roll cost and budget for it.
2. **Then get a real sample.** The identity question needs the full 13-shot
   battery at minimum, and nothing can be concluded about which conditions
   break her likeness until generation is reliable enough to produce them.
