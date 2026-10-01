# Pinning both ends does not hold a camera through a swing — 2026-10-01

Tested at the owner's direction after shots 2-4 came back wrong: a down-the-line pitch
rendered as a side-on full swing with a driver.

## The keyframes were right

Worth stating first, because it narrows the problem. The edited keyframe was exactly the
brief: her from behind, hip height, down the line, sand wedge with visible loft, green and
flag ahead. The finish keyframe matched it — same camera, same clothes, same glove, same
wedge, weight on the lead foot, ball gone.

**The render left them.** At t=0 the clip matches the keyframe; by about 1 second she has
rotated to side-on and the wedge has become a long club.

## The decay, measured

Downscaled frame correlation against the keyframe the clip was built from. Crude, so the
shape within a clip is what matters, not levels across clips.

| | t=0 | 0.5s | 1.0s | 2.0s | 4.0s |
|---|---|---|---|---|---|
| swing, unpinned | 0.98 | 0.73 | 0.67 | 0.68 | 0.64 |
| **swing, both ends pinned** | **0.98** | **0.74** | **0.72** | **0.73** | **0.76** |
| ball rolling (little motion) | 0.98 | 0.93 | 0.89 | 0.85 | — |

Pinning stops the *drift away* — the pinned clip recovers to 0.76 where the unpinned one
kept falling to 0.64 — and does nothing about the first half-second, where both lose a
quarter of their adherence.

Looking at the frames says the same thing more plainly: frame 1 behind her, frames 2-3
rotated side-on, frame 4 a smear, frames 5-6 behind her again. **Both pinned ends held.
The path between them did not.**

This is the same shape as ADR 0007's effect on head roll in shot 1: pinning made the head
*end* where it started and made the excursion in between larger. First/last conditioning
constrains endpoints, not trajectory.

## What the published guidance says

Consistent across sources: these models are autoregressive, so error in early frames is the
foundation for later ones and compounds. Quality degrades past about 6 seconds, a 4-second
clip holds identity better than a 10-second one from the same image, and stitching short
clips beats generating long ones.

Two techniques we have never used, both documented for this model family:

- **Bracketed camera directives** — `[Static shot]`, `[Push in]`, two or three at most.
  Ours were prose, which the model reads as scene description.
- **Prompt the delta.** In image-to-video, describe what *changes*. Our prompts
  re-described the whole setup, inviting re-invention of a composition the keyframe had
  already fixed.

`[Static shot]` and a delta-only prompt were both used in this test. They did not save it.

## Where that leaves the swing

The usable window is about **one second** — the time before the camera moves. That is
enough for an address, a reaction or a ball rolling. It is not enough for a swing.

Four ways forward, cheapest first:

1. **Shoot the swing side-on.** The model keeps rotating to side-on, so start there and
   there is nothing to rotate to. Works with the model's bias instead of against it, and
   costs one keyframe edit plus two takes — about $0.48. It abandons the brief's
   down-the-line framing.
2. **Cut the swing.** Address (static, holds well) → cut → ball finishing by the hole
   (holds well). The strike is the one event this model cannot keep coherent, and hiding
   the hardest moment in a cut is what the brief's own production note recommends.
3. **Try a newer model.** `fal-ai/minimax/hailuo-2.3` is a generation on from our
   `h3-max-turbo`, and there is a Director variant built for camera control. ADR 0003
   ruled veo3.1 out for club-and-ball, but that was measured on a different tier months
   ago. A fair comparison is a few dollars.
4. **Accept one-second cuts throughout.** Matches both the measurement and the published
   advice, but changes the piece's rhythm and is a content decision rather than a
   technical one.

## Cost

| | |
|---|---|
| finish keyframe edit | $0.08 |
| 2 pinned takes at 5s | $0.40 |
| **this test** | **$0.48** |
