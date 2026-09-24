"""Report integrity, and the whole harness end to end on fakes."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from scripts.spike.calibrate import Calibration
from scripts.spike.cli import main
from scripts.spike.errors import FakeDataInReport
from scripts.spike.report import render_gate_report
from scripts.spike.score import ClipScore

TODAY = dt.date(2026, 9, 22)


def _cal(stub: bool = False) -> Calibration:
    return Calibration(
        embedder_key="stub:p:0:d256" if stub else "real:m:1:d512",
        embedder_is_stub=stub,
        calibrated_on=TODAY,
        threshold=0.82,
        target_fpr=0.01,
        fpr_at_threshold=0.004,
        tpr_at_threshold=0.97,
        eer_threshold=0.80,
        eer=0.01,
        auc=0.998,
        d_prime=4.2,
        overlap=0.02,
        verdict="EXCELLENT",
        positives={"n": 120, "mean": 0.93, "sd": 0.03, "p05": 0.88, "median": 0.93, "p95": 0.97},
        negatives={"n": 300, "mean": 0.31, "sd": 0.09, "p05": 0.18, "median": 0.31, "p95": 0.46},
    )


def _score(ref: str, min_score: float, condition: dict[str, str], below: int = 0) -> ClipScore:
    """`below` is how many readable frames fell under the threshold.

    The verdict turns on that fraction, not on `min_score`, which is kept as a
    reported diagnostic only. See scripts/spike/score.py.
    """
    return ClipScore(
        ref=ref,
        label=ref,
        embedder_key="real:m:1:d512",
        threshold=0.82,
        min_face_presence=0.9,
        max_run_below=0.4,
        frames_sampled=10,
        frames_usable=10,
        no_face_frames=0,
        multi_face_frames=0,
        frames_below_threshold=below,
        longest_run_below_threshold=below,
        identity_score_min=min_score,
        identity_score_mean=min_score + 0.02,
        max_similarity_any_master=min_score + 0.03,
        worst_frame_source=None,
        condition=condition,
    )


SCORES = [
    _score(
        "a",
        0.91,
        {
            "angle": "front",
            "distance": "close",
            "light": "indoor",
            "motion": "static",
            "cell_id": "a",
        },
    ),
    _score(
        "b",
        0.70,
        {
            "angle": "profile",
            "distance": "wide",
            "light": "midday",
            "motion": "turning",
            "cell_id": "b",
        },
        below=8,
    ),
]
LEDGER = {
    "budget_usd": "300",
    "spent_usd": "182.40",
    "calls": 48,
    "failed_calls": 2,
    "contains_fake_spend": False,
    "by_provider": {},
}


def test_report_refuses_stub_evidence():
    """A human makes a go/no-go call from this document."""
    with pytest.raises(FakeDataInReport, match="stub embedder"):
        render_gate_report(
            run_id="r",
            calibration=_cal(stub=True),
            scores=SCORES,
            ledger_summary=LEDGER,
            today=TODAY,
        )


def test_report_refuses_fake_provider_spend():
    ledger = {**LEDGER, "contains_fake_spend": True}
    with pytest.raises(FakeDataInReport, match="stub providers"):
        render_gate_report(
            run_id="r", calibration=_cal(), scores=SCORES, ledger_summary=ledger, today=TODAY
        )


def test_allow_fake_stamps_the_report_loudly():
    text = render_gate_report(
        run_id="r",
        calibration=_cal(stub=True),
        scores=SCORES,
        ledger_summary=LEDGER,
        allow_fake=True,
        today=TODAY,
    )
    assert "THIS REPORT IS NOT EVIDENCE" in text
    assert "Do not make a gate decision from it" in text


def test_real_evidence_needs_no_override_and_has_every_section():
    text = render_gate_report(
        run_id="r",
        calibration=_cal(),
        scores=SCORES,
        ledger_summary=LEDGER,
        identity_passing_seconds=60.0,
        today=TODAY,
    )
    assert "NOT EVIDENCE" not in text
    for heading in (
        "## 1. Threshold calibration",
        "## 2. Identity pass rate by condition",
        "## 3. Worst-frame contact sheet",
        "## 4. Lip-sync drift probe",
        "## 5. Golf format matrix",
        "## 6. Cost",
        "## 7. Operator time",
        "## 8. Recommendation",
    ):
        assert heading in text, heading


def test_report_leads_with_overlap_not_the_threshold():
    text = render_gate_report(
        run_id="r", calibration=_cal(), scores=SCORES, ledger_summary=LEDGER, today=TODAY
    )
    assert text.index("Distribution overlap") < text.index("Chosen threshold")
    assert "**Read this first.**" in text


def test_report_breaks_pass_rate_down_by_condition():
    text = render_gate_report(
        run_id="r", calibration=_cal(), scores=SCORES, ledger_summary=LEDGER, today=TODAY
    )
    assert "A single headline number is not the finding" in text
    for axis in ("### angle", "### distance", "### light", "### motion"):
        assert axis in text


def test_cost_per_identity_passing_second_is_reported_as_an_upper_bound():
    text = render_gate_report(
        run_id="r",
        calibration=_cal(),
        scores=SCORES,
        ledger_summary=LEDGER,
        identity_passing_seconds=60.0,
        today=TODAY,
    )
    assert "Cost per identity-passing second" in text
    # The number must not be presented as a usable rate: identity passing is an
    # upper bound on usable, and saying otherwise is what made a visibly bad
    # clip look fine (docs/reports/identity-gate-blind-spot-2026-09-24.md).
    assert "UPPER BOUND" in text
    assert "$3.0400" in text  # 182.40 / 60


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------


def test_full_harness_runs_offline_and_catches_drift(tmp_path, monkeypatch):
    """The demo path: fixtures -> calibrate -> generate -> score -> report."""
    monkeypatch.chdir(Path.cwd())
    cfg_path = tmp_path / "spike.yaml"
    original = Path("config/spike.yaml").read_text()
    cfg_path.write_text(original.replace("run_root: spike/runs", f"run_root: {tmp_path / 'runs'}"))

    assert main(["--config", str(cfg_path), "demo", "--cells", "10"]) == 0

    run_dir = next((tmp_path / "runs").iterdir())
    scores = json.loads((run_dir / "scores.json").read_text())
    assert len(scores) == 10

    # The fake provider drifts some clips and not others. If everything passed,
    # the harness would be proving only that it runs.
    passed = [s for s in scores if s["identity_passed"]]
    assert 0 < len(passed) < len(scores)

    # Face loss is handled by the coverage rule, not the similarity rule -- and
    # it downgrades rather than fails. A clip that lost a frame or two but still
    # showed most of the face is a pass; one that showed too little to judge is
    # indeterminate and goes to a human. Neither is a similarity failure.
    lost = [s for s in scores if s["no_face_frames"] > 0]
    assert lost, "expected the fixture to lose the face in at least one clip"
    thin = [s for s in lost if s["identity_verdict"] == "indeterminate"]
    assert all(not s["identity_passed"] for s in thin)
    assert all(s["failure_reason"] and "threshold" not in s["failure_reason"] for s in thin)
    # Nothing is certified on coverage the rule calls insufficient.
    assert not [s for s in scores if s["identity_passed"] and s["face_presence"] < 0.5]

    cal = json.loads((run_dir / "calibration.json").read_text())
    assert cal["embedder_is_stub"] is True
    assert cal["verdict"] == "EXCELLENT"

    probe = json.loads((run_dir / "lipsync_probe.json").read_text())
    assert probe["mean_delta"] < 0, "lip sync should measurably degrade identity"

    assert (run_dir / "contact_sheet.png").exists()
    report = (run_dir / "gate-a.md").read_text()
    assert "THIS REPORT IS NOT EVIDENCE" in report


def test_budget_is_mandatory_on_every_spending_command():
    """Amendment A7, enforced by argparse rather than by remembering."""
    import contextlib
    import io

    for command in ("run-matrix", "battery", "lipsync-probe"):
        with pytest.raises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            main([command])


def test_a_rerun_replaces_output_of_a_different_shape(tmp_path, cfg_path=None):
    """Regression: a paid clip was lost to IsADirectoryError.

    The fake provider writes a clip as a directory of stills so it needs no
    encoder; a hosted provider writes a single file. Re-running a ref after
    switching provider therefore finds the wrong kind of thing in the way, and
    the download died *after* the video had been generated and billed.
    """
    import shutil

    clips = tmp_path / "clips"
    stale = clips / "matrix-000"
    stale.mkdir(parents=True)
    (stale / "frame_000.png").write_bytes(b"old")

    # What _generate_and_score now does before handing the path to a provider.
    if stale.is_dir():
        shutil.rmtree(stale)
    elif stale.exists():
        stale.unlink()

    assert not stale.exists()
    stale.write_bytes(b"MP4")  # the write that previously raised
    assert stale.read_bytes() == b"MP4"
