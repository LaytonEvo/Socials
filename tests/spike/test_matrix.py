"""Condition sampling. A breakdown by condition is only meaningful if the
sample actually covers every condition."""

from __future__ import annotations

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
