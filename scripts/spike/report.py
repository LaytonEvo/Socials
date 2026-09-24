"""Gate A report generator.

Produces the eight sections docs/BUILD_ORDER.md Section 3.3 requires, from run
artifacts rather than from anything typed in by hand.

The refusal in :func:`render_gate_report` is the important part. A human reads
this document to decide whether to build the system at all. Evidence from stub
providers or a stub embedder must never reach that decision silently, so the
generator raises unless the caller states explicitly that it knows.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from .calibrate import Calibration
from .errors import FakeDataInReport
from .matrix import GOLF_BATTERY
from .score import ClipScore, identity_rate_by_condition


def _pct(value: float | None) -> str:
    return "--" if value is None else f"{value:.0%}"


def _num(value: float | None, places: int = 4) -> str:
    return "--" if value is None else f"{value:.{places}f}"


def _calibration_section(cal: Calibration) -> list[str]:
    lines = [
        "## 1. Threshold calibration",
        "",
        f"- Embedder: `{cal.embedder_key}`",
        f"- Calibrated: {cal.calibrated_on.isoformat()}",
        "",
        "| Statistic | Value | Reading |",
        "|---|---|---|",
        f"| Distribution overlap | **{cal.overlap:.3f}** | "
        "0 = disjoint, 1 = indistinguishable. **Read this first.** |",
        f"| ROC AUC | {cal.auc:.4f} | P(same-face pair scores above different-face pair) |",
        f"| d' | {cal.d_prime:.3f} | Separation in pooled standard deviations |",
        f"| Equal error rate | {cal.eer:.4f} | at threshold {cal.eer_threshold:.4f} |",
        f"| **Chosen threshold** | **{cal.threshold:.4f}** | "
        f"FPR {cal.fpr_at_threshold:.4f}, TPR {cal.tpr_at_threshold:.4f} "
        f"(target FPR {cal.target_fpr:.3f}) |",
        "",
        f"**Verdict: {cal.verdict}**",
        "",
        "| Distribution | n | mean | sd | p05 | median | p95 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, d in (("Same face", cal.positives), ("Different faces", cal.negatives)):
        if d.get("n"):
            lines.append(
                f"| {name} | {int(d['n'])} | {d['mean']:.4f} | {d['sd']:.4f} | "
                f"{d['p05']:.4f} | {d['median']:.4f} | {d['p95']:.4f} |"
            )
    if cal.warnings:
        lines += ["", "**Warnings**", ""]
        lines += [f"- {w}" for w in cal.warnings]
    return lines


def _matrix_section(scores: list[ClipScore]) -> list[str]:
    total = len(scores)
    identity_passed = sum(1 for s in scores if s.identity_passed)
    lines = [
        "## 2. Identity pass rate by condition",
        "",
        f"{identity_passed} of {total} clips passed the IDENTITY gate "
        f"({(identity_passed / total if total else 0):.0%}). That is not a usable "
        f"rate: the identity gate cannot see motion, anatomy or shot adherence "
        f"(docs/reports/identity-gate-blind-spot-2026-09-24.md).",
        "",
        "A single headline number is not the finding. The breakdown is:",
        "",
    ]
    breakdown = identity_rate_by_condition(scores)
    for axis, levels in breakdown.items():
        lines += [
            f"### {axis}",
            "",
            "| Level | Clips | Passed | Pass rate | Worst min score | Mean min score |",
            "|---|---|---|---|---|---|",
        ]
        for level, stats in sorted(levels.items(), key=lambda kv: kv[1]["identity_pass_rate"]):
            lines.append(
                f"| {level} | {stats['clips']} | {stats['identity_passed']} | "
                f"{stats['identity_pass_rate']:.0%} | {_num(stats['worst_min_score'])} | "
                f"{_num(stats['mean_min_score'])} |"
            )
        lines.append("")

    lost = [s for s in scores if s.no_face_frames or s.multi_face_frames]
    lines += [
        "### Frames where the face was lost",
        "",
        "Clips with no-face or multi-face frames. These do not show up in a "
        "similarity score, which is why the pass rule also requires face presence.",
        "",
    ]
    if not lost:
        lines.append("None.")
    else:
        lines += [
            "| Clip | Sampled | Usable | No face | Multi face | Presence | Identity |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in lost:
            lines.append(
                f"| {s.label} | {s.frames_sampled} | {s.frames_usable} | "
                f"{s.no_face_frames} | {s.multi_face_frames} | "
                f"{_pct(s.face_presence)} | {s.identity_verdict} |"
            )
    lines.append("")
    return lines


def _contact_sheet_section(sheet: Path | None) -> list[str]:
    lines = ["## 3. Worst-frame contact sheet", ""]
    if sheet is None:
        lines.append("_Not generated._")
    else:
        lines += [
            f"![Worst frames]({sheet})",
            "",
            "**This is the check on the instrument, not an illustration.** Look at "
            "the worst frame of every clip marked PASS. If the scorer passed clips "
            "you would reject, that is a Gate A finding in itself: automated scoring "
            "becomes advisory rather than gating, and BUILD_PLAN task 3.4's "
            "auto-reject design needs rework before it is built on top of it.",
        ]
    lines.append("")
    return lines


def _lipsync_section(probe: dict[str, Any] | None) -> list[str]:
    lines = ["## 4. Lip-sync drift probe (S0.8)", ""]
    if not probe:
        lines += ["_Not run._", ""]
        return lines
    lines += [
        "Identity re-scored after lip sync. BUILD_ORDER amendment A5: the pipeline "
        "as planned scores takes *before* lip sync and never again, so the recorded "
        "score does not describe what ships.",
        "",
        "| Clip | Min before | Min after | Delta | Still passes |",
        "|---|---|---|---|---|",
    ]
    for row in probe.get("clips", []):
        lines.append(
            f"| {row['label']} | {_num(row['before_min'])} | {_num(row['after_min'])} | "
            f"{_num(row['delta'])} | {'yes' if row['after_identity_passes'] else 'no'} |"
        )
    mean_delta = probe.get("mean_delta")
    if mean_delta is not None:
        lines += ["", f"Mean change in minimum identity score: **{mean_delta:+.4f}**."]
        if mean_delta < -0.01:
            lines.append(
                "Lip sync measurably degrades identity. Amendment A5 should be "
                "adopted: score the render after lip sync and gate on that."
            )
    lines.append("")
    return lines


def _battery_section(ratings: list[dict[str, Any]] | None) -> list[str]:
    lines = ["## 5. Golf format matrix (S0.7)", ""]
    if not ratings:
        lines += [
            "_No ratings recorded._ Generate the rating sheet with "
            "`python -m scripts.spike.cli battery-sheet`, rate every take by hand, "
            "then re-run the report.",
            "",
        ]
        return lines

    hard = {item["id"]: item["hard"] for item in GOLF_BATTERY}
    by_format: dict[str, dict[str, Any]] = {}
    for row in ratings:
        fid = row["format_id"]
        agg = by_format.setdefault(
            fid, {"takes": 0, "usable": 0, "ratings": [], "tags": {}, "providers": set()}
        )
        agg["takes"] += 1
        rating = int(row.get("rating") or 0)
        agg["ratings"].append(rating)
        agg["usable"] += int(rating >= 4)
        agg["providers"].add(row.get("provider", "?"))
        for tag in str(row.get("failure_tags") or "").split("|"):
            if tag.strip():
                agg["tags"][tag.strip()] = agg["tags"].get(tag.strip(), 0) + 1

    lines += [
        "Usable = rated 4 or 5. `predicted hard` is what BUILD_PLAN Phase 2 and "
        "ADR 0003 expected to break, recorded before the test ran.",
        "",
        "| Format | Predicted hard | Takes | Usable | Usable rate | Dominant failure tags |",
        "|---|---|---|---|---|---|",
    ]
    for fid, agg in sorted(by_format.items(), key=lambda kv: kv[1]["usable"] / kv[1]["takes"]):
        top = sorted(agg["tags"].items(), key=lambda kv: -kv[1])[:3]
        tags = ", ".join(f"{t} ({n})" for t, n in top) or "--"
        lines.append(
            f"| {fid} | {'yes' if hard.get(fid) else 'no'} | {agg['takes']} | "
            f"{agg['usable']} | {agg['usable'] / agg['takes']:.0%} | {tags} |"
        )

    surprises = [
        fid
        for fid, agg in by_format.items()
        if hard.get(fid) and agg["usable"] / agg["takes"] >= 0.5
    ] + [
        fid
        for fid, agg in by_format.items()
        if not hard.get(fid) and agg["usable"] / agg["takes"] < 0.5
    ]
    lines += ["", "**Where the prediction was wrong:** " + (", ".join(surprises) or "nowhere."), ""]
    return lines


def _cost_section(
    ledger_summary: dict[str, Any], identity_passing_seconds: float | None
) -> list[str]:
    lines = [
        "## 6. Cost",
        "",
        f"- Budget: ${ledger_summary.get('budget_usd')}",
        f"- Spent: **${ledger_summary.get('spent_usd')}**",
        f"- Calls: {ledger_summary.get('calls')} "
        f"({ledger_summary.get('failed_calls')} failed, and still paid for)",
        "",
    ]
    by_provider = ledger_summary.get("by_provider") or {}
    if by_provider:
        lines += ["| Provider | Calls | Failed | Units | Spend |", "|---|---|---|---|---|"]
        for name, agg in sorted(by_provider.items()):
            lines.append(
                f"| {name} | {agg['calls']} | {agg['failed']} | "
                f"{agg['units']:.1f} | ${agg['total_usd']} |"
            )
        lines.append("")
    if identity_passing_seconds:
        spent = float(ledger_summary.get("spent_usd", 0) or 0)
        lines += [
            f"**Cost per identity-passing second of video: "
            f"${spent / identity_passing_seconds:.4f}**",
            "",
            "Identity-passing is an UPPER BOUND on usable: the gate cannot see "
            "motion, anatomy or whether the clip is the shot that was asked for, "
            "and passed a visibly AI-generated clip on 2026-09-24. Read this as "
            "the best case for BUILD_PLAN Section 9, not the real discard rate.",
            "",
            "This number, not the brief's assumed 3-in-5 discard rate, is the input "
            "to BUILD_PLAN Section 9's budget model and to the Phase 0 cost guard.",
            "",
        ]
    return lines


def _operator_time_section(entries: list[dict[str, Any]]) -> list[str]:
    lines = ["## 7. Operator time", ""]
    if not entries:
        lines += [
            "_Nothing logged._ BUILD_PLAN Section 9 calls operator time the number "
            "that decides whether the operation is viable. Log it with "
            "`python -m scripts.spike.cli time --task S0.x --minutes N`.",
            "",
        ]
        return lines
    total = sum(float(e.get("minutes", 0)) for e in entries)
    by_task: dict[str, float] = {}
    for e in entries:
        by_task[e.get("task", "?")] = by_task.get(e.get("task", "?"), 0.0) + float(
            e.get("minutes", 0)
        )
    lines += ["| Task | Minutes |", "|---|---|"]
    for task, minutes in sorted(by_task.items()):
        lines.append(f"| {task} | {minutes:.0f} |")
    lines += [
        f"| **Total** | **{total:.0f}** |",
        "",
        f"That is {total / 60:.1f} hours. Section 9 is right that this, not "
        "generation spend, is the line that decides viability -- and BUILD_ORDER "
        "amendment A1 exists because the production schema has nowhere to record it.",
        "",
    ]
    return lines


def render_gate_report(
    *,
    run_id: str,
    calibration: Calibration,
    scores: list[ClipScore],
    ledger_summary: dict[str, Any],
    contact_sheet: Path | None = None,
    lipsync_probe: dict[str, Any] | None = None,
    battery_ratings: list[dict[str, Any]] | None = None,
    operator_time: list[dict[str, Any]] | None = None,
    identity_passing_seconds: float | None = None,
    allow_fake: bool = False,
    today: dt.date | None = None,
) -> str:
    """Render the Gate A report, or refuse if the evidence is synthetic."""
    fake_reasons = []
    if calibration.embedder_is_stub:
        fake_reasons.append("the calibration used the stub embedder (pixel statistics)")
    if ledger_summary.get("contains_fake_spend"):
        fake_reasons.append("the run contains spend from stub providers")
    if fake_reasons and not allow_fake:
        raise FakeDataInReport(
            "Refusing to write a Gate A report because "
            + " and ".join(fake_reasons)
            + ". A human reads this document to decide whether to build the system at "
            "all. Pass --allow-fake only when producing a sample of the report's "
            "shape, never when producing evidence."
        )

    today = today or dt.date.today()
    header = [
        "# Gate A report — identity and format feasibility",
        "",
        f"**Run:** `{run_id}` · **Generated:** {today.isoformat()}",
        "**Stage:** Spike 0 (docs/BUILD_ORDER.md Section 3)",
        "",
    ]
    if fake_reasons:
        header += [
            "> [!WARNING]",
            "> **THIS REPORT IS NOT EVIDENCE.** It was generated with `--allow-fake`: "
            + " and ".join(fake_reasons).capitalize()
            + ". It shows the report's shape only. Do not make a gate decision from it.",
            "",
        ]

    body: list[str] = []
    body += _calibration_section(calibration)
    body += [""]
    body += _matrix_section(scores)
    body += _contact_sheet_section(contact_sheet)
    body += _lipsync_section(lipsync_probe)
    body += _battery_section(battery_ratings)
    body += _cost_section(ledger_summary, identity_passing_seconds)
    body += _operator_time_section(operator_time or [])
    body += [
        "## 8. Recommendation",
        "",
        "_To be written by the person running the spike._ One of:",
        "",
        "- **Proceed** — identity holds at a threshold that separates, the scorer "
        "agrees with human judgement, and enough golf formats survive to carry a "
        "content concept. Build Phase 0, sized by the evidence above.",
        "- **Change approach** — identity holds only in a narrow band of conditions, "
        "or the scorer is unreliable. The architecture may still be right; the shot "
        "vocabulary, provider mix, or the role of automated scoring needs rework "
        "before Phase 0 is built around it.",
        "- **Stop** — identity does not hold, or the surviving formats cannot carry the concept.",
        "",
        "A failed Gate A is a successful spike.",
        "",
        "---",
        "",
        "### Decisions this report should unblock",
        "",
        "| Decision | Where |",
        "|---|---|",
        "| D1 — persona name, look, backstory, voice | informed by section 5 |",
        "| ADR 0003 — content format constraints | section 5 |",
        "| Amendment A5 — re-score after lip sync | section 4 |",
        "| BUILD_PLAN Section 9 — budget model | section 6 |",
        "| BUILD_PLAN task 0.7 — cost guard design | section 6 |",
    ]
    return "\n".join(header + body) + "\n"
