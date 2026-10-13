# ADR 0017 — One model for the mouth and the motion

- **Status**: **proposed**, 2026-10-13. Nothing is swapped. The slot is configured and a
  test is written; the decision waits on the owner watching the result.
- **Would replace**: the two-stage talking-shot chain — `video.golf` image-to-video
  followed by `lipsync.primary` — for shots where she speaks to camera
- **Does not touch**: `video.golf`, which stays the slot for anything with action in it
- **Relates to**: amendment A5 (re-score identity after lip sync), ADR 0013 (a price is a
  price *for* something)

## Context

The owner's report, twice over three weeks:

> *"Weird head tilt at the end again."*
> *"Lip sync and motion."*

Both are consequences of the same construction. Shot 1 is built like this:

1. `h3-max-turbo/image-to-video` animates a still. **The model never hears the line.** It
   invents head motion from the prompt, which is why the prompt has to make her talk at
   all — see the note on `lipsync.primary` in `config/providers.yaml`: HeyGen *replaces*
   speech and refuses a take with a closed mouth (*"No speech detected in the input
   video"*).
2. Six takes are generated and ranked on head roll, because the invented motion varies
   wildly between takes — measured 19.2° to 39.8° of roll on 2026-10-01.
3. HeyGen replaces the mouth with the real line.

So the head motion and the words are independent by construction. The chain can make the
mouth right and the head wrong at the same time, and the gate has said the unmeasurable
half out loud since 2026-09-24:

> `[REVIEW] lip sync: whether the mouth matches the words is not measurable here.`

Ranking six takes on head roll is a symptom, not a feature. It is sampling against a
variable that should not have been free.

## Decision

**Propose `fal-ai/kling-video/ai-avatar/v2/standard`: image plus voice in, video out, with
mouth and head motion generated together from the audio.**

Verified 2026-10-13 against fal's own OpenAPI and pricing endpoint:

| | current chain | proposed |
|---|---|---|
| calls per finished shot | 3 (video ×6 takes, TTS, sync) | 1 (TTS unchanged) |
| head motion | invented, ranked over 6 takes | driven by the audio |
| duration | chosen, then the line padded to fit | **follows the audio** |
| source take must contain speech | yes — HeyGen refuses a closed mouth | no |
| cost per finished second | $0.34 (6 × $0.04 + $0.10) | **$0.0562** |
| shot 1 as costed | $2.2452 | **$0.96 for three takes** |

Three consequences worth stating beyond the price.

**Duration stops being a gamble.** There is no duration parameter: the output length
follows the audio and the response reports what it produced. A 15-second line gives a
15-second clip. The current chain picks a duration, renders against a drift budget, then
pads the line to fit — which is also why `long-form-construction-2026-10-01.md` treated
15 seconds as a problem to be chained around on a *talking* shot. For talking shots it
simply is not one.

**Take selection loses its criterion, and that is correct.** Head roll was rankable
because it was free. Once the motion comes from the audio there is nothing to rank but
identity, so the test keeps every take and a human picks. The owner's eye has been the
instrument on every judgement of this kind so far.

**It is not a new provider.** Same account, same adapter protocol, same cost guard, same
licence. `licenseType: commercial` on fal's catalogue.

## What is not verified

- **The output canvas.** The endpoint takes no aspect or resolution parameter, so the
  canvas presumably follows `image_url` as `h3-max-turbo`'s does. Nothing confirms it.
  Our shot is 1080×1920, so `scripts/avatar_test.py` prints the dimensions of every clip
  before anything else. Recorded in config as `canvas: follows_image_unverified`.
- **The maximum audio length.** Undocumented on this endpoint. A long line may be refused.
- **No `price_basis`, deliberately.** There is no resolution field for a price to be
  quoted against, so an unqualified price is the honest record here. If fal later tiers
  this model, the slot needs a `price_basis` and a re-read — ADR 0013 in reverse.
- **Quality.** Nothing in this ADR is a claim about how it looks. The argument is about
  the mechanism: the motion is generated from the audio rather than beside it. Whether
  that reads as a person is exactly what the owner has to watch.

## Status: blocked on a credential

`scripts/avatar_test.py` is written, typechecked, and its dry run prices correctly. It
cannot run in this environment because **`FAL_KEY` is not set** — the bucket credentials
are present, the fal credential is not. Secrets come from the environment only
(CLAUDE.md), so this waits on the variable being added to the environment's settings.

## If it works

The talking-shot path collapses to TTS → avatar → disclosure → captions, and
`make_single_shot.py` loses its take loop, its roll ranking and its sync stage. That is a
real simplification, so this ADR moves to accepted only with a clip the owner has watched
and approved — the same bar `This is a much better video` set on 2026-10-01.

## If it does not

Nothing is lost but the test's cost. The slot stays configured and unused, as `video.face`
has since 2026-09-28, and the current chain keeps working.
