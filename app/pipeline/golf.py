"""Golf plausibility for image and video prompts.

ADR 0009 decided against a golf knowledge base and was right about the stage it
examined: the model writing her dialogue already knows the rules, the etiquette and the
equipment, and a retrieval layer would buy nothing but cost and an authority voice the
persona spec spends a section avoiding.

It scoped the question to dialogue, and dismissed the image stage in one line — *"the
video model needs none, it renders pictures and never knows what a handicap is"*. True,
and beside the point. The image model does not need to know what a handicap is. It needs
to know that **a golf bag does not go on a putting green**, which it does not, and which
it demonstrated by rendering exactly that.

This is the other kind of golf knowledge: not facts she might say, but what a golf
photograph can contain without a golfer wincing. It is small, it is a fixed list, and it
belongs in the prompt rather than in a corpus.

**Everything here is a visual rule.** Nothing in this module decides what she says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Implausibility:
    """Something a golfer would notice. `rule` is what it violates, in plain words."""

    rule: str
    why: str


#: Surfaces, and what may happen on them. The green is the one with real etiquette
#: attached — a bag or a trolley on the putting surface is the error that marks content
#: as made by someone who has never played.
_GREEN = r"(putting green|the green\b|on a green\b|on the green)"
_BAG = r"(golf bag|carry bag|stand bag|tour bag|trolley|pull cart|golf cart)"
_DRIVER = r"(driver|3 wood|three wood|fairway wood)"
_BUNKER = r"(bunker|sand trap)"

RULES: Final[tuple[tuple[str, str, str], ...]] = (
    (
        rf"{_BAG}.{{0,60}}{_GREEN}|{_GREEN}.{{0,60}}{_BAG}",
        "a bag, trolley or cart on the putting green",
        "bags and trolleys never go on the putting surface — it is the single most "
        "recognisable tell that nobody involved has played",
    ),
    (
        rf"{_DRIVER}.{{0,60}}{_GREEN}|{_GREEN}.{{0,60}}{_DRIVER}",
        "a driver or fairway wood on the green",
        "only a putter is used on the green",
    ),
    (
        rf"{_DRIVER}.{{0,60}}{_BUNKER}|{_BUNKER}.{{0,60}}{_DRIVER}",
        "a driver in a bunker",
        "a wedge is played from sand; a driver off sand is not a shot",
    ),
    (
        r"(tee|teeing ground|tee box).{0,50}(putter)",
        "a putter on the tee",
        "a tee shot is not played with a putter",
    ),
    (
        r"(golf glove).{0,40}(both hands|two gloves)",
        "a glove on both hands",
        "a golfer wears one glove, on the lead hand",
    ),
    (
        r"(swinging|swing|hitting).{0,40}(right.handed).{0,40}(left.handed)",
        "a stance that contradicts itself",
        "handedness has to be consistent within a shot",
    ),
)

#: Appended to every golf prompt. Short, because a long tail of instructions dilutes
#: the subject — these are the faults actually seen in generated frames.
HOUSE_STYLE: Final = (
    "correct golf equipment for the shot, plausible stance and grip, "
    "no logos or brand names or text on clothing or equipment, "
    "bag and trolley kept off the putting surface"
)


def check(prompt: str) -> list[Implausibility]:
    """Everything in this prompt that a golfer would notice. Empty is the good case."""
    lowered = " ".join(prompt.lower().split())
    found = []
    for pattern, rule, why in RULES:
        if re.search(pattern, lowered):
            found.append(Implausibility(rule=rule, why=why))
    return found


def apply_house_style(prompt: str) -> str:
    """Add the standing visual constraints to a prompt, once.

    Includes the no-logos instruction, which is not etiquette but liability: the
    generator put a real trademark on her visor unprompted, and in video it was present
    for the whole clip.
    """
    if HOUSE_STYLE in prompt:
        return prompt
    return f"{prompt.rstrip().rstrip(',')}, {HOUSE_STYLE}"
