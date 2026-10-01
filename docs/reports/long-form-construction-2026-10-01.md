# How videos over ten seconds are actually constructed — 2026-10-01

Researched at the owner's request after a 5-second swing clip rotated its camera and came
back as a different woman.

## The short answer

**Nobody generates long clips. They generate short ones and chain them.**

Every source agrees on the mechanism and the remedy:

- These models are **autoregressive** — each frame is built on the last, so error in early
  frames becomes the foundation for later ones and compounds. Quality degrades past about
  six seconds; a four-second clip holds identity better than a ten-second one from the
  same image.
- The standard technique is **last-frame chaining**: export the final frame of a clip, use
  it as the first frame of the next, and join them in an editor. Subject position, lighting
  and composition carry over instead of resetting.
- Native chaining on most platforms caps around 30 seconds in total.

We already do the sequencing half. We have never done the chaining half: our shots each
start from an independently edited keyframe, so nothing carries across a cut except what
the edit happens to preserve. That is why continuity is a REVIEW item rather than a
property of the pipeline.

## The thing we did not know we were missing

Newer models accept **character reference images** — several views of the same person,
supplied alongside the prompt, as an identity anchor. That is the direct answer to "not
her" on a shot with no visible face, which our face-only scorer cannot even detect.

Verified against fal's own schemas and pricing pages, 2026-10-01:

| endpoint | references | duration | price at our resolution |
|---|---|---|---|
| `minimax/h3-max-turbo/image-to-video` *(what we use)* | none | 5–15s | **$0.04/s** at 768p |
| **`minimax/h3-max/reference-to-video`** | **`reference_image_urls`, audio and video refs** | 5–15s | **$0.08/s** at 768p |
| `fal-ai/kling-video/v3/pro/image-to-video` | `reference_image_urls` | — | not priced here |
| `bytedance/seedance-2.5/image-to-video` | none | up to **30s** in one pass | $0.4730/s at 720p |
| `fal-ai/minimax/hailuo-2.3/standard/image-to-video` | none | 6 or 10s | not priced here |

**`h3-max/reference-to-video` is the candidate.** Same model family as the turbo we use —
which matters, because ADR 0003 established turbo is the only model tested that renders
club-and-ball golf at all — at twice the price, with **the first four reference images
free** (4,096 reference tokens included; a square image costs 1,024). A 5-second 768p clip
with four references is $0.40.

**Seedance is out on cost.** Thirty seconds in one pass is the most interesting capability
found, and at $0.4730/s for 720p a single 15-second clip is $7.10 — against a $100 monthly
ceiling, that is fourteen clips a month before anything else is paid for.

## The caveat that decides whether this works

Reference images only help if we hold the angles the shot needs. Measured across the 80
master stills:

| | |
|---|---|
| near face-on | 45 |
| three-quarter | 29 |
| strong profile | 3 |
| no detectable face at all | 3 |

**We are rich in front views and have almost nothing from the side or behind.** A
down-the-line shot asks the model for a view we cannot reference, so reference-to-video
would be anchoring on four frontal images to render her back. That is better than nothing
and it is not the same as having the view.

Two ways to close that, both outside today's work:

1. **Extend the master set with the missing angles** — profile and rear views, generated and
   then approved by eye the way the existing set was. This is Phase 1 task 1.1 territory
   and it changes what ADR 0008 locked.
2. **Only shoot angles we hold.** The rule added today already forces this: a shot
   containing her without a verifiable face is refused, and the angles we can verify are
   the ones we have references for.

## What I would do

1. **Test `h3-max/reference-to-video` on the talking shot first**, where we have abundant
   references and a known-good baseline to compare against. About $0.48 for two 6-second
   takes. If it holds composition better than turbo, that alone is worth the doubled price.
2. **Adopt last-frame chaining between shots** — free, and it is the one technique every
   source names that we do not use.
3. **Leave the swing withdrawn** until either the master set covers rear angles or a
   reference model proves it can render one from frontal references.

## Sources

- [First Frame, Last Frame: chaining AI clips](https://medium.com/@shrutisaagar13/first-frame-last-frame-how-i-chain-ai-clips-into-one-continuous-shot-e6649434e689)
- [AI video length limits tested](https://zsky.ai/blog/ai-video-length-quality) and [How long can AI videos be](https://invideo.io/blog/ai-video-length-limits/)
- [Best AI video models with reference image support](https://app.cinevva.com/guides/long-reference-video-models)
- [Long-form AI video with character consistency](https://www.aimagicx.com/blog/long-form-ai-video-character-consistency-guide-2026)
- [Fixing AI video drift](https://kling.ai/blog/fix-ai-video-drift-consistency-guide)
- fal schemas and pricing pages for each endpoint above, read 2026-10-01
