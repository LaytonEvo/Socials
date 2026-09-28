# Dressing her: the prompt works, and takes her face with it

**Date:** 2026-09-28 · 4 clips, $0.25. Spec v1 §5's own list — navy fitted golf
polo, white pleated skort, white visor — against the usual English portrait
keyframe.

## The outfit obeys, exactly and stably

She wears what the prompt asks for. Navy polo, white pleated skort, visor, held
for the whole clip with no drift. **Spec §5's clothing rule is enforceable at
generation time**, which the previous report said it might not be.

That is a real result: wardrobe is a prompt-level control, like the Florida
setting, and not something the model insists on choosing.

## But identity falls over

| Clip | Face presence | Verdict | Identity min |
|---|---|---|---|
| `talking_head_course` take 1 | 0.500 | **fail** | 0.9259 |
| `talking_head_course` take 2 | 0.800 | **fail** | **0.8854** |
| `walking_fairway` take 1 | 0.200 | indeterminate | 0.9884 |
| `walking_fairway` take 2 | 0.500 | indeterminate | 0.9109 |

**Both talking-head takes failed.** 0.8854 is the second-worst identity score in
the entire spike, beaten only by the clip that turned into a man.

The same two formats, same keyframe, same model, with no outfit in the prompt
returned 0.9725, 0.9748, 0.9634 and 0.9571 — every one a pass or a near-pass.

**The naive reading is that dressing her costs her face**, and the mechanism is
at least plausible: a heavily specified outfit is a large instruction about her
appearance, and the model appears to re-render more of her to satisfy it.

**Treat that as a hypothesis.** The gate's failures have been right one in three
across this spike, and it has cried wolf on exactly this kind of clip before —
it failed all four Florida clips the owner then rated usable. On the frames she
reads as noticeably more made-up than the master set, which is consistent with
the score, but the owner's eye decides and the clips have gone to them.

## It invented a brand

The visor carries a legible made-up wordmark, and there are logo marks on the
polo and skort. **Nobody asked for branding.**

This matters more than it looks:

- Spec v1 §7 forbids partnered product claims without on-screen use and
  disclosure. Invented branding is not a claim, but it is apparel that reads as
  sponsored when nothing is.
- An invented mark can land close to a real one. Golf apparel is a crowded
  trademark space and the model has no idea what it is spelling.
- It is **unmeasured**. Nothing in the harness reads text in a frame, so a brand
  could appear on any clip and only a human would catch it.

Add to the negative prompt at minimum: no logos, no wordmarks, no brand names on
clothing or equipment. **That is a locked-fragment change, not a per-shot one.**

## The wardrobe-continuity detector: built, tested, withdrawn

An attempt at the instrument D-A needs. Torso-region colour histogram, first
frame against last, no model and no API.

On hand-picked cases it looked decisive: the white-skirt-to-black-shorts clip
scored **0.428** and the owner's "changes outfit midway" clip **0.400**, against
**0.017** and **0.018** for two clean clips.

Across all 60 rated clips it does not hold. **25 score above 0.25 and only one
of those is a clip the owner flagged for wardrobe.** Clips rated 5 score higher
than the known-bad ones — `ball_flight` at 0.849, because the camera pans off
her and the sampled region stops containing a person at all.

So it measures *"the lower middle of the frame looks different by the end"*,
which conflates a clothing change with a camera move, her leaving frame, and a
cut. **Not specific, and the clean result came from choosing two examples.**

Making it work needs the clothing sampled rather than a fixed rectangle, which
means detecting the person: a segmentation model, a licence to check under
CLAUDE.md's rules, and a new component to agree. Not free and not today.

**Third instrument this spike has built on a plausible mechanism and withdrawn
on measurement**, after the roll detector and the cuts-cause-identity-drift
correlation. Recorded rather than shipped.
