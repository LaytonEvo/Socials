# The invented soundtrack: two lanes, and only one had a problem

**Date:** 2026-09-28 · The owner, repeatedly, across nine days of clips:
*"wrong language"*, *"weird music"*, *"not sure what language she's speaking"*.

`h3-max` generates a soundtrack on every clip and its schema has **no flag to
turn that off**. 61 of 61 clips came back speaking an unidentified language, and
nothing in the scoring pipeline noticed because nothing in it listens.

Three mechanisms were tried and are recorded in ADR 0005. None of them was the
answer, and the answer turns out not to need one.

## A speaking clip already fixes itself

A clip bound for the lip-sync stage does not have an audio problem. **HeyGen
replaces the soundtrack and the mouth together**, so whatever the model invented
never survives to publication.

There is a second-order benefit nobody planned. `config/spike.yaml`'s lipsync
slot carries this note against Veo:

> Refused twice without this, both free: first because our clips are silent by
> design and heygen requires an audio track on the input

**Veo's silent clips needed a workaround to be accepted at all.** Turbo's
unconditional soundtrack satisfies that requirement for nothing. The nuisance
removes a hack.

## A non-speaking clip needs the track removed, and that is free

Everything else — a swing, a reaction, B-roll, a walking shot — never reaches
the lip-sync stage, so nothing overwrites the audio. That is the whole of the
problem, and it is an `ffmpeg` stream copy away from solved.

`--mute` on the battery, and `strip_audio()` underneath it. **Stream copy, so
the video is bit-identical** and only the audio track goes. Demonstrated on the
four clips the owner had just approved: all four now carry a video stream and
nothing else.

Two details worth having got right:

- **These clips have no file extension** — the ref *is* the filename — so ffmpeg
  cannot infer a muxer and has to be told. The container is read from the file
  rather than assumed to be mp4, because the container is the provider's choice.
- **It refuses if ffmpeg is missing** rather than passing the clip through
  untouched. A clip that silently keeps its invented audio is exactly the
  failure this exists to prevent, and a no-op that reports success would
  reintroduce it.

## The rule, for `content_policy.yaml`

> Every clip either goes through the lip-sync stage, which replaces its audio,
> or has its audio stripped. No clip ships the model's invented soundtrack.

That is a pipeline invariant rather than a per-shot decision, which is what
makes it enforceable in code — the same shape as the disclosure rule.

**Replacing rather than removing** is also available and verified: pinning via
`target_audio_url` lands bit-exact (+1.000 correlation against the source). For
ambience or music under B-roll that is the better option, and it needs a track
to pin, which nothing in the project has yet.

## What is still not solved

**The voice is not stable between takes.** *"Second sounds a little different."*
Native speech can be steered to English — that works — but a recurring persona
needs one voice the way it needs one face, and the model does not hold one. That
is why ElevenLabs and the lip-sync stage stay, and it is a separate problem from
the language, which this closes.
