"""Condition sampling. A breakdown by condition is only meaningful if the
sample actually covers every condition."""

from __future__ import annotations

from typing import cast

import pytest

from scripts.spike.matrix import (
    AXES,
    FULL_MATRIX_SIZE,
    GOLF_BATTERY,
    coverage,
    coverage_gaps,
    sample_matrix,
)


def test_every_axis_level_is_covered_at_the_planned_size():
    assert coverage_gaps(sample_matrix(24, seed=20260922)) == []


def test_no_gaps_across_many_seeds_and_sizes():
    for seed in range(15):
        for n in (20, 24, 30, 40):
            assert coverage_gaps(sample_matrix(n, seed=seed)) == [], (seed, n)


def test_axes_are_near_balanced():
    conditions = sample_matrix(24, seed=7)
    for axis, counts in coverage(conditions).items():
        spread = max(counts.values()) - min(counts.values())
        assert spread <= 2, (axis, counts)


def test_sampling_is_deterministic():
    a = [c.cell_id for c in sample_matrix(24, seed=3)]
    b = [c.cell_id for c in sample_matrix(24, seed=3)]
    assert a == b
    assert a != [c.cell_id for c in sample_matrix(24, seed=4)]


def test_prompt_fragment_is_identical_for_identical_conditions():
    """Otherwise the matrix measures prompt wording, not the condition."""
    conditions = sample_matrix(40, seed=1)
    by_cell: dict[str, set[str]] = {}
    for c in conditions:
        by_cell.setdefault(c.cell_id, set()).add(c.prompt_fragment())
    assert all(len(v) == 1 for v in by_cell.values())


def test_full_matrix_size_matches_the_axes():
    total = 1
    for levels in AXES.values():
        total *= len(levels)
    assert total == FULL_MATRIX_SIZE


def test_battery_records_the_prediction_before_the_test_runs():
    """ADR 0003's prediction is tagged up front so the report can show where
    it was wrong, not just where it was right."""
    hard = {i["id"] for i in GOLF_BATTERY if i["hard"]}
    assert {"full_swing_impact", "ball_flight", "putting_stroke"} <= hard
    assert "talking_head_course" not in hard


def test_coverage_probe_predicts_a_band_it_could_miss():
    """The probe exists to pin a floor the current clips only bracket.

    Every shot records the coverage band expected BEFORE generating. A probe
    whose prediction cannot be wrong measures nothing -- the same reasoning as
    `hard` in the golf battery -- so the bands must be real intervals strictly
    inside (0, 1), and they must span the gap the evidence left open.
    """
    from scripts.spike.matrix import COVERAGE_PROBE, PROMPT_SETS

    assert PROMPT_SETS["coverage"] is COVERAGE_PROBE
    assert len({item["id"] for item in COVERAGE_PROBE}) == len(COVERAGE_PROBE)
    for item in COVERAGE_PROBE:
        lo, hi = item["expect"]
        assert 0.0 < lo < hi < 1.0, item["id"]
        assert item["prompt"], item["id"]
    # The bracket left open by docs/reports/face-presence-rule-2026-09-24.md.
    lows = [item["expect"][0] for item in COVERAGE_PROBE]
    highs = [item["expect"][1] for item in COVERAGE_PROBE]
    assert min(lows) <= 0.375, "nothing probes the bottom of the open bracket"
    assert max(highs) >= 0.875, "nothing probes the top of the open bracket"


def test_shot_filter_rejects_an_unknown_id():
    """A typo must not silently generate the whole set at $1.60 a clip."""
    from scripts.spike.matrix import COVERAGE_PROBE, select_shots

    assert select_shots(COVERAGE_PROBE, None, "coverage") is COVERAGE_PROBE
    picked = select_shots(COVERAGE_PROBE, ["glance_back", "point_to_green"], "coverage")
    assert [item["id"] for item in picked] == ["glance_back", "point_to_green"]
    with pytest.raises(ValueError, match="typo"):
        select_shots(COVERAGE_PROBE, ["glance_back", "typo"], "coverage")


def test_a_refused_keyframe_does_not_jam_the_rest_of_the_run(monkeypatch, tmp_path):
    """Three coverage-probe shots were refused in a row against one still.

    Indexing advanced only on success, so a keyframe that draws
    no_media_generated was handed to every subsequent shot for ever. A refusal
    is free, and is specific to the (keyframe, prompt) pair, so the next still
    is tried instead.
    """
    from scripts.spike import cli
    from scripts.spike.errors import ProviderRefused

    frames = [tmp_path / f"kf_{i}.png" for i in range(3)]
    bad = frames[1]
    seen = []

    def fake_generate(*, keyframe, **kwargs):
        seen.append(keyframe)
        if keyframe == bad:
            raise ProviderRefused("no media", error_type="no_media_generated")
        return f"score-for-{keyframe.name}"

    monkeypatch.setattr(cli, "_generate_with_retry", fake_generate)

    # Starting on the bad still, it moves on rather than giving up.
    score, cursor = cli._generate_trying_keyframes(frames, 1)
    assert cast(str, score) == "score-for-kf_2.png"
    assert seen == [bad, frames[2]]
    # And the cursor advances, so the next shot does not start on the same one.
    assert cursor == 3


def test_every_keyframe_refused_still_raises(monkeypatch, tmp_path):
    from scripts.spike import cli
    from scripts.spike.errors import ProviderRefused

    frames = [tmp_path / f"kf_{i}.png" for i in range(2)]

    def always_refuse(*, keyframe, **kwargs):
        raise ProviderRefused("no media", error_type="no_media_generated")

    monkeypatch.setattr(cli, "_generate_with_retry", always_refuse)
    with pytest.raises(ProviderRefused):
        cli._generate_trying_keyframes(frames, 0)


def test_resuming_a_prompt_set_keeps_the_shots_already_paid_for(tmp_path):
    """--shots writes a subset; overwriting would discard generated clips."""
    from scripts.spike.cli import _write_battery_sheet

    _write_battery_sheet(tmp_path, [{"ref": "a", "verdict": "pass"}], "coverage")
    _write_battery_sheet(tmp_path, [{"ref": "b", "verdict": "fail"}], "coverage")

    import csv as _csv

    with (tmp_path / "coverage_ratings.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    assert [r["ref"] for r in rows] == ["a", "b"]
