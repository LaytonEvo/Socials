# Midjourney prompts for widening the master set

The master set defines what the scorer will accept as "her". The current 28
stills are near-identical framing, which is why the threshold has no room for
motion (see `docs/reports/s05-gate-finding-2026-09-24.md`): a talking-head
clip fails because nothing in the reference set shows her talking.

**So the goal is not more images. It is more *variation* — while still
obviously being the same woman.** Every prompt below holds her description
constant and moves exactly one thing.

## Before you start

1. **Attach the anchor image to every prompt.** Midjourney v8.2 does not
   support `--cref`; the image reference is what keeps the face consistent.
   Use the same anchor for all of them, or the set will drift.
2. **Add `--ar 9:16`.** Veo accepts 16:9 or 9:16 and crops anything else,
   blind to where she is. Generating at 9:16 removes the crop entirely — the
   current stills are 928x1232 and lose a quarter of their width.
3. **Keep whatever style settings produced the originals.** I can't verify
   v8.2's flags from here, and a mismatched look would widen the set for the
   wrong reason — we want variation in pose and light, not in rendering.
4. **Keep roughly 3 of every 4.** Discard only images where she is plainly a
   different person. Mild variation is the point; over-curating back to
   near-identical stills recreates the problem.

## The prompts

Base description, unchanged in all of them:

> a 25 year old english woman, long wavy light brown hair, brown eyes, natural
> makeup, slim athletic build, on a golf course

### Group 1 — talking (the highest-value group)

Nothing in the current set shows her mouth open, which is the likeliest reason
a talking-head clip scored below the threshold. This group matters most.

| # | Prompt (append to the base description) |
|---|---|
| 1 | `, mid-sentence talking to camera, mouth open, animated expression, medium shot waist up, soft daylight --ar 9:16` |
| 2 | `, laughing with her head back, mouth open, eyes crinkled, medium shot, golden hour --ar 9:16` |
| 3 | `, mid-speech gesturing with one hand, looking at camera, waist up, overcast light --ar 9:16` |
| 4 | `, smiling broadly showing teeth, head and shoulders, bright daylight --ar 9:16` |

### Group 2 — angle

| # | Prompt |
|---|---|
| 5 | `, three-quarter view facing left, looking at camera, waist up, soft daylight --ar 9:16` |
| 6 | `, three-quarter view facing right, looking away from camera, waist up, golden hour --ar 9:16` |
| 7 | `, full profile side view, looking down the fairway, waist up, overcast --ar 9:16` |
| 8 | `, turning her head towards the camera over her shoulder, waist up, afternoon light --ar 9:16` |

### Group 3 — distance

| # | Prompt |
|---|---|
| 9 | `, tight close-up of her face, shoulders just in frame, soft daylight --ar 9:16` |
| 10 | `, close-up, head and shoulders, slight smile, golden hour --ar 9:16` |
| 11 | `, full body standing on the fairway, relaxed posture, midday sun --ar 9:16` |
| 12 | `, full body walking towards camera, mid-stride, overcast --ar 9:16` |

### Group 4 — light

| # | Prompt |
|---|---|
| 13 | `, harsh midday sunlight, strong shadows on her face, waist up --ar 9:16` |
| 14 | `, warm low golden hour sun behind her, rim light on her hair, waist up --ar 9:16` |
| 15 | `, flat grey overcast daylight, no shadows, waist up --ar 9:16` |
| 16 | `, seated indoors in a clubhouse by a window, soft indoor light, waist up --ar 9:16` |

### Group 5 — expression and head position

| # | Prompt |
|---|---|
| 17 | `, neutral expression, relaxed, looking straight at camera, waist up --ar 9:16` |
| 18 | `, concentrating, slight frown, looking down at the ball, waist up --ar 9:16` |
| 19 | `, head tilted to one side, warm smile, head and shoulders --ar 9:16` |
| 20 | `, eyes closed briefly mid-blink, relaxed face, head and shoulders --ar 9:16` |

## What to send back

20 prompts × 4 images ≈ 80 candidates; keeping ~3 in 4 gives roughly 60 new
stills. Added to the existing 28 that is a master set of about 90, which also
clears the harness's small-sample warning (it wants 50+ per distribution).

Put them in a folder and I will re-prepare and re-calibrate. Expect the
overlap statistic to rise from 0.000 — that is the point. A wider positive
distribution is an honest one, and the threshold should land somewhere a
moving clip can clear. If overlap rises far enough to reach the control set,
that is a real finding about how distinctive she is, and better learned now.

## What NOT to do

- **Do not change her description** to make images easier to get. The set
  defines her identity; drift here silently redefines the target.
- **Do not include images you would not publish.** The master set is the
  standard every take is measured against, so a bad still lowers the bar.
- **Do not discard the current 28.** They stay in the set. The aim is to widen
  it, not replace it.
