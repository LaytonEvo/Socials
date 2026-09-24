"""The identity condition matrix (BUILD_PLAN task 1.6 / spike task S0.6).

The axes are taken verbatim from the plan:

    angle (front, 3/4, profile) x distance (close, medium, wide)
    x light (midday, golden hour, overcast, indoor) x motion (static, walking, turning)

That is 108 combinations and the plan asks for at least 20 clips, so the cells
have to be *sampled*. Sampling them at random would leave axis levels unevenly
covered, and the whole point of task 1.7 is a pass rate broken down *by
condition* -- a level that appears once tells you nothing.

So the sampler is balanced: it cycles each axis independently with a seeded
shuffle per cycle, which keeps every level's count within one of every other
level's on the same axis, while still spreading combinations.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

AXES: dict[str, tuple[str, ...]] = {
    "angle": ("front", "three_quarter", "profile"),
    "distance": ("close", "medium", "wide"),
    "light": ("midday", "golden_hour", "overcast", "indoor"),
    "motion": ("static", "walking", "turning"),
}

FULL_MATRIX_SIZE = 3 * 3 * 4 * 3


@dataclass(frozen=True)
class Condition:
    angle: str
    distance: str
    light: str
    motion: str

    @property
    def cell_id(self) -> str:
        return f"{self.angle}-{self.distance}-{self.light}-{self.motion}"

    def as_dict(self) -> dict[str, str]:
        return {
            "angle": self.angle,
            "distance": self.distance,
            "light": self.light,
            "motion": self.motion,
            "cell_id": self.cell_id,
        }

    def prompt_fragment(self) -> str:
        """Condition language for the generation prompt.

        Deliberately fixed phrasing: the same condition must read identically
        every time it appears, or the matrix measures prompt wording rather than
        the condition. This is the spike's stand-in for BUILD_PLAN task 3.3's
        locked prompt fragments.
        """
        angle = {
            "front": "facing the camera straight on",
            "three_quarter": "at a three-quarter angle to the camera",
            "profile": "in profile to the camera",
        }[self.angle]
        distance = {
            "close": "close-up head and shoulders framing",
            "medium": "medium shot from the waist up",
            "wide": "wide shot, full body in frame",
        }[self.distance]
        light = {
            "midday": "harsh midday sunlight",
            "golden_hour": "warm low golden hour light",
            "overcast": "flat overcast daylight",
            "indoor": "soft indoor lighting",
        }[self.light]
        motion = {
            "static": "standing still",
            "walking": "walking steadily",
            "turning": "turning her head towards the camera",
        }[self.motion]
        return f"{distance}, {angle}, {motion}, {light}"


def _balanced_cycle(levels: tuple[str, ...], n: int, rng: random.Random) -> list[str]:
    """n picks from ``levels``, shuffled within each full cycle.

    Guarantees counts differ by at most one across levels.
    """
    out: list[str] = []
    while len(out) < n:
        block = list(levels)
        rng.shuffle(block)
        out.extend(block)
    return out[:n]


def sample_matrix(n: int, seed: int = 0) -> list[Condition]:
    """``n`` conditions with balanced coverage of every axis level.

    Duplicate combinations are re-drawn by rotating the light axis, which can
    leave that one axis off perfect balance by a clip or two. Every other axis
    stays exactly balanced. Always check :func:`coverage` before reading a
    per-condition breakdown, and :func:`coverage_gaps` to confirm no level was
    missed entirely.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    rng = random.Random(seed)
    columns = {name: _balanced_cycle(levels, n, rng) for name, levels in AXES.items()}
    seen: set[str] = set()
    conditions: list[Condition] = []
    for i in range(n):
        cond = Condition(
            angle=columns["angle"][i],
            distance=columns["distance"][i],
            light=columns["light"][i],
            motion=columns["motion"][i],
        )
        for _ in range(8):
            if cond.cell_id not in seen:
                break
            # Rotate one axis rather than re-randomising, so balance holds.
            levels = AXES["light"]
            cond = Condition(
                cond.angle,
                cond.distance,
                levels[(levels.index(cond.light) + 1) % len(levels)],
                cond.motion,
            )
        seen.add(cond.cell_id)
        conditions.append(cond)
    return conditions


def coverage(conditions: list[Condition]) -> dict[str, dict[str, int]]:
    """How many clips landed on each level of each axis."""
    out: dict[str, dict[str, int]] = {}
    for axis, levels in AXES.items():
        counts = dict.fromkeys(levels, 0)
        for cond in conditions:
            counts[getattr(cond, axis)] += 1
        out[axis] = counts
    return out


def coverage_gaps(conditions: list[Condition]) -> list[str]:
    """Axis levels with no clips. A non-empty result invalidates the breakdown."""
    return [
        f"{axis}.{level}"
        for axis, counts in coverage(conditions).items()
        for level, count in counts.items()
        if count == 0
    ]


# --------------------------------------------------------------------------
# Golf format battery (BUILD_PLAN task 2.1 / spike task S0.7)
# --------------------------------------------------------------------------

#: Formats are tagged `expected_hard` where BUILD_PLAN Section 6 Phase 2 and
#: ADR 0003 predict the models break. Tagging the prediction up front means the
#: gate report can show where it was right and, more usefully, where it was
#: wrong -- a prediction confirmed by a test you designed to confirm it is
#: worth much less than one that survived a fair trial.
GOLF_BATTERY: tuple[dict[str, Any], ...] = (
    {"id": "talking_head_course", "hard": False, "prompt": "talking to camera on the course"},
    {"id": "walking_fairway", "hard": False, "prompt": "walking the fairway, relaxed"},
    {"id": "equipment_closeup", "hard": False, "prompt": "close-up handling a golf club"},
    {"id": "apparel", "hard": False, "prompt": "presenting golf apparel, turning to camera"},
    {"id": "clubhouse", "hard": False, "prompt": "seated in a clubhouse, talking"},
    {"id": "reaction", "hard": False, "prompt": "reacting to a shot, expressive"},
    {"id": "putting_stroke", "hard": True, "prompt": "making a putting stroke on the green"},
    {"id": "chip", "hard": True, "prompt": "playing a short chip shot"},
    {"id": "full_swing_address", "hard": True, "prompt": "addressing the ball, full swing setup"},
    {"id": "full_swing_top", "hard": True, "prompt": "at the top of a full backswing"},
    {"id": "full_swing_impact", "hard": True, "prompt": "club-ball impact, full swing"},
    {"id": "full_swing_follow", "hard": True, "prompt": "follow-through of a full swing"},
    {"id": "ball_flight", "hard": True, "prompt": "ball flight away down the fairway"},
)

#: Coverage probe. NOT a test of the provider -- a test of *our* scoring rule.
#:
#: The face-presence floor is bracketed to (0.375, 0.875] by the 30 clips the
#: spike has generated, because 29 of them kept the face in nearly every frame
#: and one lost it entirely (docs/reports/face-presence-rule-2026-09-24.md).
#: Nothing populates the middle, so no value in that range can be preferred to
#: another on evidence. These prompts each describe a *transition* -- the face
#: entering or leaving frame partway through -- which is what produces partial
#: coverage.
#:
#: `expect` is the coverage band predicted BEFORE generating, recorded so the
#: probe can be wrong. A prediction that cannot fail measures nothing, which is
#: the same reasoning behind `hard` in the golf battery above.
COVERAGE_PROBE: tuple[dict[str, Any], ...] = (
    {
        "id": "turn_away_hold",
        "hard": False,
        "expect": (0.35, 0.55),
        "prompt": "turning away from camera to look down the fairway, holding that view",
    },
    {
        "id": "glance_back",
        "hard": False,
        "expect": (0.25, 0.50),
        "prompt": "walking away from camera, then glancing back over her shoulder",
    },
    {
        "id": "look_down_and_up",
        "hard": False,
        "expect": (0.65, 0.90),
        "prompt": "looking down to line up a putt, then looking up to camera",
    },
    {
        "id": "approach_camera",
        "hard": False,
        "expect": (0.50, 0.80),
        "prompt": "walking toward camera from the middle distance",
    },
    {
        "id": "profile_to_camera",
        "hard": False,
        "expect": (0.40, 0.65),
        "prompt": "standing in profile looking across the course, then turning to face camera",
    },
    {
        "id": "point_to_green",
        "hard": False,
        "expect": (0.60, 0.85),
        "prompt": "talking to camera, then turning to point down the course",
    },
)

#: Prompt sets the `battery` command can run. The golf battery measures the
#: provider; the coverage probe measures our own scoring rule.
PROMPT_SETS: dict[str, tuple[dict[str, Any], ...]] = {
    "golf": GOLF_BATTERY,
    "coverage": COVERAGE_PROBE,
}


#: Failure tags from BUILD_PLAN task 2.3, used for manual rating in S0.7.
FAILURE_TAGS = (
    "hands_grip",
    "club_distortion",
    "contact_physics",
    "ball",
    "swing_plane",
    "background",
    "face_drift",
)
