# S0.8 — lip sync costs 0.0123 of identity, and sank one clip in three

**Measured with a real provider for the first time.** The only previous figure
was `-0.0141` from the fake provider, which describes the harness.

| Clip | Before | After | Delta |
|---|---|---|---|
| `talking_head_course` | 0.9761 | 0.9708 | −0.0052 |
| `apparel` | 0.9696 | **0.9503** | **−0.0193** |
| `clubhouse` | 0.9690 | 0.9567 | −0.0123 |
| | | **mean** | **−0.0123** |

Provider: `fal-ai/pixverse/lipsync`, $0.04 per output second. Three clips that
had already passed the identity gate, re-scored against the same threshold
(0.9609) after the pass.

**`apparel` dropped below the threshold.** It passed at 0.9696 and comes back
at 0.9503 — a clip that was acceptable before lip sync and is a failure after
it. One in three, on a sample of three.

This answers amendment A5 and it is not a comfortable answer.

## The consequence nobody has accounted for

The threshold was calibrated on **stills**: her master set against a control
set, both photographs. Clips are then scored against it. Lip sync applies a
further transformation, and if the pipeline *always* lip-syncs then the gate
is judging production output against a distribution production output never
belongs to.

That is the calibration-space error from
`calibration-2026-09-23-corrected.md`, one level up: a threshold is only
meaningful in the space it was measured in. The fix is the same shape —
calibrate against what the pipeline actually emits. Either:

- re-calibrate on lip-synced clips, so the operating point matches production;
- or apply the gate *before* lip sync and accept that the published artefact
  was never scored;
- or treat the measured −0.0123 as a budget and require clips to clear
  threshold + margin before they earn a lip-sync pass.

The third is the cheapest and the least principled. The first is correct and
costs a calibration run.

**None of this is decided.** It is recorded because the pipeline is about to
be built on top of it.

## Voice quality: the built-in TTS is not usable

The probe drove `pixverse/lipsync` with `text`, so its own text-to-speech
produced the voice. Owner's verdict: *"those voices aren't good ... older than
her and harsh ... too robotic"*, and a glitch at the end of the line on the
word "one".

Two separate problems, and they want separating:

- **The voice** belongs to a text-to-speech provider. `fal-ai/elevenlabs/tts/*`
  is on fal with a `voice` parameter and, on `turbo-v2.5`, `stability` and
  `speed`. That is the route to a chosen British voice that stays the same
  across videos — which native Veo audio cannot offer, since it invents a
  voice per clip.
- **The glitch** is most likely the line not fitting the clip. Sixty-four
  characters is roughly 4.5–5 seconds of natural speech in a 4-second video,
  and the overrun lands exactly on "one more club". Untested; the fixes are a
  shorter line, a 6 s or 8 s clip, or `speed` above 1.0.

## Method note

The lip-sync model refuses a data URI (`file_download_error`), so the keyframe
approach does not generalise. Clips were passed as the fal CDN URLs they were
generated to, recovered from the queue by the request ids in the run log. The
same route will carry TTS output into the lip-sync call: chaining fal models
needs no upload at all.

## Still open

- Which lip-sync model. `pixverse` is the cheapest at $0.04/s; `sync-lipsync
  v2/pro`, `heygen/v3/lipsync/precision` and `veed/lipsync/v2` are untested and
  dearer. Sync *accuracy* has not been rated — the owner's comments were about
  the voice and the glitch.
- The per-character surcharge for text-driven calls, which fal's listing
  truncated. The configured guard covers video seconds only and understates
  those calls.
- Whether the identity cost differs by lip-sync model. If a dearer model costs
  less identity, the cheap one is not the cheap one.
