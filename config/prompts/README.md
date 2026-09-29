# Locked prompt fragments

Task 3.3 composes every generation prompt from fragments kept here — character
description, lighting, camera language — plus the shot's own specifics, so
phrasing is identical shot to shot. A prompt assembled ad hoc is a variable
nobody is controlling.

Nothing lives here yet. Two findings from Spike 0 that these fragments have to
carry when they are written:

- **Wardrobe is not a prompt fragment.** Asking for different clothes in a video
  prompt forces a hard cut and a re-rendered person. Clothing is set in the
  keyframe, and the prompt describes the world around her.
  See `docs/reports/wardrobe-control-2026-09-28.md`.
- **Prompt expansion must stay off.** Every provider offers some form of it, and
  it rewrites the prompt before generation — so the clip on record is not the
  clip that was asked for. It was on for three days by mistake and is the most
  likely source of the unrequested multi-shot editing in those clips.
