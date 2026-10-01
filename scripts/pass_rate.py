"""Measure the single-shot pass rate by running the real pipeline N times.

Why this exists, and why it is a script rather than a number I chose:

The keyframe screen (ADR 0011) was built after four draws of the *same prompt and the
same LoRA* scored 0.95049 / 0.96813 / 0.96162 / 0.97841 — a spread of 0.028 straddling
the threshold. The lesson was that a single draw of a stochastic generator tells you
almost nothing, and the first accepted single shot is itself a single draw.

Two things downstream need this number and cannot be built honestly without it:

- **`BUILD_PLAN` task 3.4** specifies a retry cap. A cap is a bet on the pass rate; if
  shots pass 9 times in 10, a cap of 3 is generous, and if they pass 5 times in 10 it is
  a coin flip whether a shot ever completes.
- **The Phase 3 gate** wants a 30-60 second piece with a cost report. That is 6-12 shots,
  and the cost of a piece is the cost of a shot divided by the pass rate, not multiplied
  by the number of shots.

Each run is independent and goes through `make_single_shot.py` as a subprocess — the real
path, not a reimplementation of it, so what is measured is what production would do.

Where a run stops matters as much as whether it passed, because the stages cost different
amounts. A keyframe refusal costs the keyframes alone and is the screen working as
designed; a gate refusal after the sync has been paid for is the expensive outcome the
screen was built to prevent.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Where a run ended. Ordered cheapest-to-dearest, which is also the order in which a run
# can fail: a stage cannot refuse before the stages above it have been paid for.
KEYFRAME_REFUSED = "keyframe refused"
GATE_REFUSED = "gate refused"
ACCEPTED = "accepted"
ERROR = "error"

KEYFRAME_SCORE = re.compile(r"keyframe (\d+)/(\d+): ([0-9.]+) (pass|below)")
TAKE_LINE = re.compile(r"(take_\d+\.mp4): head roll sd ([0-9.]+) deg over (\d+)/(\d+)")
BLOCKING = re.compile(r"\[BLOCKING\] (.+)")
NO_KEYFRAME = re.compile(r"no keyframe reached the still threshold")
ESTIMATE = re.compile(r"ESTIMATE\s+\$([0-9.]+)")


@dataclass
class RunResult:
    """One independent pass through the pipeline."""

    index: int
    outcome: str
    seconds: float
    keyframe_scores: list[float]
    keyframe_passes: int
    best_keyframe: float | None
    take_coverage: list[float]
    blocking: list[str]
    exit_code: int

    @property
    def paid_for_the_chain(self) -> bool:
        """Whether this run spent money below the keyframe stage.

        A keyframe refusal stops before the takes and the sync, so it costs about a
        quarter of what a gate refusal costs. Averaging the two together would report a
        cost per attempt that no attempt actually has.
        """
        return self.outcome in {ACCEPTED, GATE_REFUSED}


def run_once(index: int, *, out: Path, budget: Decimal, keyframes: int, takes: int) -> RunResult:
    """One run, through the real script, with its own output directory."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "make_single_shot.py"),
            "--out",
            str(out),
            "--budget",
            str(budget),
            "--keyframes",
            str(keyframes),
            "--takes",
            str(takes),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    elapsed = time.monotonic() - started
    log = completed.stdout + completed.stderr
    (out / "run.log").write_text(log)

    scores = [float(m.group(3)) for m in KEYFRAME_SCORE.finditer(log)]
    passes = sum(1 for m in KEYFRAME_SCORE.finditer(log) if m.group(4) == "pass")
    coverage = [int(m.group(3)) / int(m.group(4)) for m in TAKE_LINE.finditer(log)]
    blocking = [m.group(1) for m in BLOCKING.finditer(log)]

    if completed.returncode == 0:
        outcome = ACCEPTED
    elif NO_KEYFRAME.search(log):
        outcome = KEYFRAME_REFUSED
    elif blocking:
        outcome = GATE_REFUSED
    else:
        outcome = ERROR

    return RunResult(
        index=index,
        outcome=outcome,
        seconds=elapsed,
        keyframe_scores=scores,
        keyframe_passes=passes,
        best_keyframe=max(scores) if scores else None,
        take_coverage=coverage,
        blocking=blocking,
        exit_code=completed.returncode,
    )


def per_run_estimate(keyframes: int, takes: int) -> Decimal:
    """What one run costs if it goes all the way through, from the script itself.

    Asked of `make_single_shot.py --dry-run` rather than recomputed here, so this cannot
    drift from the prices the run will actually be charged.
    """
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "make_single_shot.py"),
            "--dry-run",
            "--keyframes",
            str(keyframes),
            "--takes",
            str(takes),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    found = ESTIMATE.search(completed.stdout)
    if not found:
        raise SystemExit(f"could not read a per-run estimate from the script:\n{completed.stdout}")
    return Decimal(found.group(1))


def report(results: list[RunResult], *, per_run: Decimal) -> str:
    """The table, and the three numbers that are the point of running this."""
    total = len(results)
    accepted = [r for r in results if r.outcome == ACCEPTED]
    errors = [r for r in results if r.outcome == ERROR]
    chain_runs = [r for r in results if r.paid_for_the_chain]

    lines = [
        f"# Single-shot pass rate — {datetime.now(UTC).date().isoformat()}",
        "",
        f"{total} independent runs of `scripts/make_single_shot.py` through the real path.",
        "",
        "| run | outcome | keyframes | best kf | take coverage | time | blocking |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        kf = f"{r.keyframe_passes}/{len(r.keyframe_scores)} pass" if r.keyframe_scores else "—"
        best = f"{r.best_keyframe:.5f}" if r.best_keyframe is not None else "—"
        cov = f"{min(r.take_coverage):.0%}-{max(r.take_coverage):.0%}" if r.take_coverage else "—"
        why = "; ".join(r.blocking)[:70] or "—"
        lines.append(
            f"| {r.index} | {r.outcome} | {kf} | {best} | {cov} | {r.seconds / 60:.1f}m | {why} |"
        )

    lines += ["", "## The numbers", ""]
    if errors:
        # An error is not a refusal. Counting one as a failure would blame the pipeline
        # for something that did not get far enough to be judged.
        lines.append(
            f"**{len(errors)} of {total} runs errored** rather than being judged, and are "
            "excluded from the rate below. An error is not a refusal."
        )
        lines.append("")
    judged = [r for r in results if r.outcome != ERROR]
    if judged:
        rate = len(accepted) / len(judged)
        lines += [
            f"- **Pass rate: {len(accepted)}/{len(judged)} = {rate:.0%}**",
            f"- Keyframe refusals (cheap, the screen working): "
            f"{sum(1 for r in judged if r.outcome == KEYFRAME_REFUSED)}",
            f"- Gate refusals after paying for the chain: "
            f"{sum(1 for r in judged if r.outcome == GATE_REFUSED)}",
        ]
        if rate > 0:
            # The number task 3.4's retry cap is actually a bet on.
            expected = 1 / rate
            lines.append(
                f"- **Expected attempts per finished shot: {expected:.2f}** — a 30-60s piece "
                f"is 6-12 shots, so {expected * 6:.0f}-{expected * 12:.0f} attempts."
            )
        else:
            lines.append(
                "- **No run passed.** A retry cap cannot be set from this; the pipeline is "
                "not yet producing finished shots at any rate."
            )
    if chain_runs:
        lines.append(
            f"- Runs that paid for the full chain: {len(chain_runs)}/{total} "
            f"(at about ${per_run} each)"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--keyframes", type=int, default=4)
    parser.add_argument("--takes", type=int, default=4)
    parser.add_argument(
        "--budget",
        type=Decimal,
        required=True,
        help="ceiling for ALL runs together, not per run",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "passrate")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    per_run = per_run_estimate(args.keyframes, args.takes)
    worst_case = per_run * args.runs
    print(f"{args.runs} runs, up to ${per_run} each, worst case ${worst_case}")
    print(f"total budget ${args.budget}")
    if worst_case > args.budget:
        raise SystemExit(
            f"worst case ${worst_case} exceeds the total budget ${args.budget}; refusing. "
            "Raise --budget deliberately or ask for fewer runs."
        )
    if args.dry_run:
        print("\n--dry-run: nothing billed.")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    results: list[RunResult] = []
    for index in range(1, args.runs + 1):
        print(f"\n=== run {index}/{args.runs} ===", flush=True)
        result = run_once(
            index,
            out=args.out / f"run_{index}",
            budget=per_run,
            keyframes=args.keyframes,
            takes=args.takes,
        )
        results.append(result)
        print(
            f"  {result.outcome} in {result.seconds / 60:.1f}m"
            + (f" — {'; '.join(result.blocking)}" if result.blocking else ""),
            flush=True,
        )
        (args.out / "results.json").write_text(json.dumps([asdict(r) for r in results], indent=2))

    text = report(results, per_run=per_run)
    (args.out / "report.md").write_text(text)
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)
    print(f"written to {args.out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
