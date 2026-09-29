"""Disclosure overlay, C2PA signing, and the policy guard.

Nothing here is optional. CLAUDE.md:

- Every final render gets the on-video disclosure overlay and a C2PA manifest,
  and no flag, env var or code path skips either. `disclosure_applied` is set to
  true only after the overlay pass has actually run.
- The policy guard blocks financial products permanently, and must not be
  weakened. Rules live in `config/content_policy.yaml`.

On C2PA, per amendment A9: most platforms re-encode on upload and strip the
manifest, so it is a provenance record for us rather than a disclosure signal
the audience sees. The on-video overlay does the disclosure work. Keep the
requirement; do not over-invest in it relative to the overlay.
"""
