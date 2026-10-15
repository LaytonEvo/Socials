# Where driving footage can legally come from — 2026-10-15

**Status:** verified against each source's own licence text, today. The owner has said he
will not film, so this is about the routes that do not need him to.

Recast feeds a real video into a model that replaces the person in it. Two separate
permissions are needed and they come from different places: **copyright in the footage**,
and **the personality rights of the golfer in it**. A source that settles one and not the
other is not usable.

## Storyblocks — no, and it is explicit

From the Individual License, read 2026-10-15:

> **Restrictions on Machine Learning, AI, or Biometric Technology Uses:** You may not use
> any Stock File … for machine learning and/or artificial intelligence purposes (i.e., to
> train AI systems), or for any technologies designed or intended for the identification
> of natural persons. **The foregoing is not meant to serve as a restriction on your
> ability to use AI to assist in your selection of Stock Files or in the creation of
> projects that do not transform the underlying Stock Files.**

The carve-out is the sentence that decides it: AI is permitted for *selection*, and for
projects that **do not transform** the file. Recast transforms it completely — it replaces
the human being in it. Their own AI Toolkit is licensed for editing Stock Files, and the
agreement is equally explicit that files altered "using AI or other tools apart from the AI
Toolkit" are outside their indemnity.

So Storyblocks is a clear no for this use, and it is worth noting the restriction is
standard rather than unusual.

## Wikimedia Commons and Creative Commons — settles copyright, not the person

A CC0 or CC-BY file settles **copyright**: derivatives and commercial use are permitted.
CC-BY-SA does not work for us for a different reason — share-alike would oblige us to
license the finished piece under CC-BY-SA, which is not compatible with a commercial
persona.

But Commons says plainly, on `Commons:Photographs_of_identifiable_people`:

> The legal rights of the subjects constitute **non-copyright restrictions** on use of
> photos. … The main legal rights of the subject are **personality rights**, which consist
> of the right of publicity and the right of privacy. … Re-use of photos should respect
> laws both where the photo is taken and where it is re-used.

That is exactly the right at stake here. A golfer's body, swing and mannerisms drive the
output; a CC licence from the *uploader* says nothing about whether the *subject* agreed to
that. Under UK GDPR their image is also personal data, and generating a synthetic person
from it needs a lawful basis the licence does not supply.

**CC0 footage with no identifiable person in it is fine** — but a swing has a person in it,
which is the whole point.

## Pexels, Pixabay, Shutterstock — could not be read

All three are now allowed by the network policy and all three refuse a non-browser client:
Cloudflare returns `cf-mitigated: challenge` for Pexels and Pixabay, CloudFront a bare 403
for Shutterstock. **This is the sites blocking automation, not the allowlist**, so there is
nothing further the owner can change. Their terms are unverified and will stay that way
unless someone reads them in a browser.

For what it is worth, the Storyblocks clause above is the industry-standard shape, so the
prior should be that these restrict it too until someone confirms otherwise.

## The route that is clean on both axes

**Commission thirty seconds from a golfer, with a signed model release.** A club pro, a
coach, or someone on a freelance platform. Roughly £50–200.

It is the only option that settles **both** permissions in one document: the videographer
assigns copyright, the golfer consents to their likeness being used this way, and the
consent is the lawful basis GDPR wants. The owner does not film anything.

It is also the cheapest per use. Two recast runs at 1080p cost $9; a commissioned library
— a drive, an iron, a chip, a pitch, a putt — is bought once and used in every piece
forever, with no licence to re-read each time.

## Still open

The MediaPipe pose weights licence remains **unverified**. `ai.google.dev` now resolves but
redirects to `developers.google.com`, which is not allowed, and the model card itself sits
behind `mediapipe.page.link`, also not allowed. Adding those two hosts would close it. It
blocks publication, not measurement (`config/providers.yaml`).
