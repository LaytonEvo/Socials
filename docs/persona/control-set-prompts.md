# Midjourney prompts for widening the control set

The control set is the negative distribution — "not her". Its job is to be as
**hard** as possible, because an easy control flatters the calibration. That is
not hypothetical: DINOv2 read ADEQUATE against random people and MARGINAL
against women who looked like her, and only the second number was true
(`docs/reports/calibration-2026-09-23-corrected.md`).

## The method: the same prompts, without the anchor image

**Take the 20 prompts from `master-set-prompts.md` and run them again with the
anchor image detached. That is the only change.**

Two reasons, and the second is the one that makes this worth doing properly.

**It produces the hardest possible negative.** A woman generated from *her own
description* — 25, English, long wavy light brown hair, brown eyes, slim
athletic, on a golf course — who simply is not her. That is exactly the failure
mode that matters, because when a video model loses her it drifts towards
"generic woman matching the description" rather than towards a random stranger.
Two clips of precisely this kind already exist, generated accidentally over a
blank landscape, and they scored 0.846 and 0.863 — hard, and correctly
rejected.

**It matches the control set to the master set, condition for condition.** The
master set now spans talking, profiles, wide shots and four lighting
conditions. The control set is 16 front-on stills. So part of what the
calibration currently measures is *varied versus front-on* rather than purely
*her versus not her*, and that asymmetry inflates the separation. Running the
identical prompts cancels everything that is not identity.

This is the same error the project has already made twice in other forms:
comparing distributions that differ in more than the one thing being measured.

## Steps

1. Open `master-set-prompts.md` (or the Google Doc) and use the same 20
   prompts, including `--ar 9:16`.
2. **Detach the anchor image.** Nothing else changes — same base description,
   same style settings.
3. Run each once or twice. Roughly 40 images.
4. **Discard any that look like her.** Counterintuitive, but a control that
   *is* her is a mislabelled positive, and it would corrupt the calibration in
   the worst possible direction: by making the two distributions overlap for a
   reason that has nothing to do with the scorer.
5. Send them as a batch. I will prepare, re-calibrate and re-score.

Target: ~40 new plus the existing 16 gives about 56, which clears the
harness's 50+ guidance for the negative distribution.

## Why these stay synthetic

ADR 0002 Finding 4: a control set of **real** faces is biometric data of real
people, processed specifically for biometric comparison — GDPR Article 9
special-category data, and a question entirely separate from the model licence.
Generating the controls synthetically removes that processing altogether, and
is the better test anyway: the relevant negative is not "a random real person"
but "another woman this generator could produce from the same description".

Do not substitute real photographs, stock images or scraped faces for
convenience. The legal exposure is not worth the time saved, and it is
avoidable by construction.

## What to expect afterwards

Overlap will probably rise again, because the controls are getting harder and
better matched. **That is the measurement becoming honest, not the scorer
getting worse.**

What matters is whether the two distributions still separate: the threshold
should stay clear of the controls by a healthy margin — currently about 0.10 —
and a clean talking-head clip should still pass. If a matched control set
collapses the separation, that is a real and important finding about how
distinctive this persona is, and far better to learn now than after a pipeline
is built on it.
