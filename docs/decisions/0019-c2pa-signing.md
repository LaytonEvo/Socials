# ADR 0019 — C2PA signing: valid now, trusted later

- **Status**: accepted, 2026-10-15. Task 3.11 built.
- **Implements**: amendment A9, without changing what it decided
- **Relates to**: ADR 0012 (unverifiable is not acceptable), task 3.10 (the overlay)

## Context

CLAUDE.md: *"Every final render gets the on-video disclosure overlay and a C2PA manifest.
Don't add a flag, env var, or code path that skips either."* The database has carried
`render.c2pa_manifest_key` and a `c2pa_manifest_key IS NULL OR disclosure_applied` check
since the schema was written. Nothing wrote to either.

With two shots now coming out well, the binding constraint has moved from making
something to being able to publish it, and this was the piece missing.

## Decision

**Sign with `c2pa-python` and a certificate chain we generate ourselves.**

Verified 2026-10-15: `c2pa-python` 0.38.0, **MIT OR Apache-2.0**, from contentauth. MP4 is
a supported format. Signing `cut-v2/final_captioned.mp4` and reading it back gives
`validation_state: Valid`.

### Disclosure before signing is a type, not a rule

`sign` takes a `FinalRender`, and only `apply_disclosure` can produce one. So a signed
file has necessarily been through the overlay pass — the database check can never be the
thing that catches a mistake, because the mistake cannot be written. `SignedRender` uses
the same construction key, so holding one is evidence a manifest was embedded.

### The manifest always declares AI generation

`digitalSourceType` is pinned to IPTC `trainedAlgorithmicMedia` with **no parameter to
vary it**. A manifest that could omit it would be the skippable code path CLAUDE.md
forbids, with extra steps. A test holds it in place.

It also asserts CAWG `training-mining` as `notAllowed` for both inference and generative
training. Her likeness is the asset, and it is the same position we take on our own inputs.

### Valid is not trusted, and the code says which it has

A self-signed chain verifies as **valid** — the bytes have not changed since signing — and
never as **trusted**, which needs a certificate from an authority on the C2PA trust list.
`SigningCredentials.trusted_chain` defaults to false and `SignedRender` carries it, so
nothing downstream can claim more than was proven. **This is the procurement item A9
flagged; it has lead time and should be started now rather than discovered later.**

## Two things that cost a round trip each, recorded so they do not again

- **The private key must be PKCS#8.** A SEC1 EC key is refused with an error about the PEM
  type label.
- **A lone self-signed certificate is refused** with "the certificate is invalid". The
  C2PA certificate profile wants an end-entity certificate issued by a CA, so
  `scripts/make_signing_cert.py` makes a small root and issues under it, and writes the
  chain end-entity first.

## Consequences

- `make check` does not need the library or a certificate. The manifest shape is pure data
  and the construction guards are type-system work; only the end-to-end signing test needs
  either, and it skips without them. It did run here: 685 passing.
- **The scanner in `test_secrets.py` had a blind spot** and this found it. It resolved
  module-level `NAME = "X"` constants but not `NAME: Final = "X"`, which is how this
  codebase writes nearly all of them — so it silently failed to see two new variables. Its
  own docstring warns about exactly this failure, one syntax node along. Fixed.
- Signing is **not yet wired into the piece scripts**. They produce a `FinalRender`; making
  a `SignedRender` the last step is a small change, held back until there is a decision
  about whether we sign every experiment or only pieces headed for review.
- Nothing about publishing is unblocked by this alone. **D-C (the dlib licence) and D7
  (counsel) still block**, and so does the unverified MediaPipe pose-weights licence.
