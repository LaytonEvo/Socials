"""The generation pipeline: shotlist, keyframes, generate, score, assemble.

Per shot: keyframe, then N takes, then identity scoring, then auto-reject below
threshold, then regenerate to a retry cap, then queue for human review
(task 3.4).

Two findings from Spike 0 that this package has to respect:

- **The identity gate routes, it never rejects.** Measured against owner
  verdicts it was right once in three on failures and caught 14% of what a human
  rejected. Automated scoring is a triage signal, not a verdict.
- **The keyframe is authoritative over her body; the prompt is authoritative
  over the world.** Changing clothes in a prompt forces a hard cut and a
  re-rendered person, so wardrobe is set in the keyframe.
"""
