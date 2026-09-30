"""Golf plausibility on image prompts.

ADR 0009 decided the dialogue stage needs no golf corpus and was right. It dismissed the
image stage in one line and was wrong: the generator rendered her carrying a bag across
a putting green, which is the single most recognisable tell that nobody involved has
played. These rules are the small fixed list that catches that class of error before it
is paid for.
"""

from __future__ import annotations

from app.pipeline.golf import HOUSE_STYLE, apply_house_style, check


def test_a_bag_on_the_green_is_caught() -> None:
    """The error that prompted all of this."""
    problems = check("she walks across the putting green carrying a golf bag")
    assert problems
    assert "putting green" in problems[0].rule


def test_a_trolley_on_the_green_is_caught() -> None:
    assert check("pulling a trolley onto the green to line up a putt")


def test_the_rule_reads_in_either_order() -> None:
    """The prompt may mention the surface or the bag first."""
    assert check("on the green, a golf bag beside her")
    assert check("a golf bag, then she steps onto the putting green")


def test_a_driver_on_the_green_is_caught() -> None:
    assert check("lining up a putt on the green with a driver")


def test_a_driver_in_a_bunker_is_caught() -> None:
    assert check("playing out of the bunker with a driver")


def test_a_putter_on_the_tee_is_caught() -> None:
    assert check("standing on the tee box holding a putter")


def test_two_gloves_are_caught() -> None:
    assert check("wearing a golf glove on both hands")


def test_a_correct_shot_passes() -> None:
    """The rules must not fire on ordinary golf, or they will be turned off."""
    for prompt in (
        "walking along the fairway carrying a golf bag over her shoulder",
        "at address over a ball on the tee with a driver",
        "putting on the green with a putter",
        "playing out of a bunker with a wedge",
        "head and shoulders portrait on a golf course",
    ):
        assert check(prompt) == [], f"false positive on: {prompt}"


def test_every_problem_explains_itself() -> None:
    """A refusal that does not say why gets worked around rather than fixed."""
    for problem in check("a golf bag on the putting green with a driver"):
        assert problem.why.strip()
        assert problem.rule.strip()


def test_house_style_is_appended_once() -> None:
    once = apply_house_style("a photo of her on the fairway")
    twice = apply_house_style(once)
    assert once.count(HOUSE_STYLE) == 1
    assert twice == once


def test_house_style_forbids_logos() -> None:
    """Not etiquette — liability. The generator put a real trademark on her visor
    unprompted, and in video it was there for the whole clip."""
    assert "no logos" in HOUSE_STYLE
    assert "brand names" in HOUSE_STYLE


def test_house_style_keeps_bags_off_the_green() -> None:
    assert "putting surface" in HOUSE_STYLE
