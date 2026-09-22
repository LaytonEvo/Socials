"""Command line for the Spike 0 harness.

    python -m scripts.spike.cli <command> --help

Every command that can spend money requires ``--budget``. There is no default
and no way to omit it (BUILD_ORDER amendment A7).

Offline work requires ``--embedder stub``, which must be asked for explicitly.
The stub is pixel statistics, not a face recognition model, and anything
measured with it is marked as such all the way through to the report.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from .calibrate import Calibration, calibrate
from .config import DEFAULT_CONFIG_PATH, SpikeConfig, load_config, write_threshold
from .contactsheet import build_contact_sheet, worst_first
from .embed import EmbeddingSet, cross_similarities, embed_images, load_embedder
from .embedders import DETECTORS  # noqa: F401  (import registers dlib + dinov2)
from .errors import SpikeError
from .frames import ImageSequenceFrames
from .ledger import CostLedger
from .matrix import FAILURE_TAGS, GOLF_BATTERY, Condition, coverage, coverage_gaps, sample_matrix
from .models import MODELS, config_snippet, fetch, sha256_of
from .providers import (
    ImageRequest,
    LipSyncRequest,
    VideoRequest,
    load_provider,
    render_fake_face,
)
from .report import render_gate_report
from .runlog import RunLog, new_run_id
from .score import ClipScore, score_clip

CONTROL_IDENTITIES = ("control-b", "control-c", "control-d", "control-e")


# --------------------------------------------------------------------------
# Shared plumbing
# --------------------------------------------------------------------------


def _run_dir(cfg: SpikeConfig, run_id: str | None) -> Path:
    if run_id:
        return cfg.run_root / run_id
    existing = sorted(p for p in cfg.run_root.glob("*") if p.is_dir())
    if not existing:
        raise SpikeError(f"No runs under {cfg.run_root}. Start one with `init-run`, or pass --run.")
    return existing[-1]


def _embedder(cfg: SpikeConfig, override: str | None) -> Any:
    emb_cfg = cfg.embedder_for(override)
    if override and emb_cfg.backend == override and emb_cfg.dim is None:
        # A backend with no entry under embedder.backends (e.g. the stub).
        emb_cfg = dataclasses.replace(
            emb_cfg,
            model=emb_cfg.model or f"{override}-override",
            version=emb_cfg.version or "0",
            dim=256,
        )
    embedder = load_embedder(emb_cfg)
    if embedder.info.is_stub:
        print(
            "  ! stub embedder in use: pixel statistics, not face recognition. "
            "Results describe the harness, not the identity approach.",
            file=sys.stderr,
        )
    return embedder


def _load_calibration(run_dir: Path) -> Calibration:
    path = run_dir / "calibration.json"
    if not path.exists():
        raise SpikeError(f"No calibration at {path}. Run `calibrate` first.")
    data = json.loads(path.read_text())
    data["calibrated_on"] = dt.date.fromisoformat(data["calibrated_on"])
    return Calibration(**data)


def _master_set(run_dir: Path, embedder: Any) -> EmbeddingSet:
    master_dir = run_dir / "master"
    stills = sorted(master_dir.glob("*.png"))
    if not stills:
        raise SpikeError(f"No master stills in {master_dir}. Run `make-fixtures` or add them.")
    return embed_images(embedder, stills, label="master")


def _ledger(cfg: SpikeConfig, log: RunLog, budget: str) -> CostLedger:
    return CostLedger(
        budget_usd=Decimal(budget),
        log=log,
        price_max_age_days=cfg.price_max_age_days,
    )


def _save_scores(run_dir: Path, scores: list[ClipScore], name: str = "scores.json") -> Path:
    dest = run_dir / name
    dest.write_text(json.dumps([s.to_json() for s in scores], indent=2))
    return dest


def _load_scores(run_dir: Path, name: str = "scores.json") -> list[ClipScore]:
    path = run_dir / name
    if not path.exists():
        return []
    out = []
    for raw in json.loads(path.read_text()):
        raw = dict(raw)
        for derived in ("face_presence", "passed", "failure_reason"):
            raw.pop(derived, None)
        raw["per_frame"] = []
        out.append(ClipScore(**raw))
    return out


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_init_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    run_id = args.run or new_run_id()
    log = RunLog(cfg.run_root / run_id)
    log.event("run_started", config=str(cfg.source_path), note=args.note or "")
    print(f"run {run_id}\n  {log.run_dir}")
    return 0


def cmd_make_fixtures(args: argparse.Namespace) -> int:
    """Synthetic master and control sets, for validating the harness offline.

    These are NOT a persona. They are coloured shapes that give the stub
    embedder similarity structure to work on.
    """
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    master_dir, control_dir = run_dir / "master", run_dir / "control"
    master_dir.mkdir(parents=True, exist_ok=True)
    control_dir.mkdir(parents=True, exist_ok=True)

    for i in range(args.master_count):
        render_fake_face("throwaway-look-a", variation=i).save(master_dir / f"master_{i:02d}.png")
    per = max(1, args.control_count // len(CONTROL_IDENTITIES))
    n = 0
    for ident in CONTROL_IDENTITIES:
        for i in range(per):
            render_fake_face(ident, variation=i).save(control_dir / f"control_{ident}_{i:02d}.png")
            n += 1
    print(f"fixtures: {args.master_count} master, {n} control -> {run_dir}")
    print("  ! synthetic shapes for harness validation, not a persona")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    log = RunLog(run_dir)
    embedder = _embedder(cfg, args.embedder)

    master = _master_set(run_dir, embedder)
    control_stills = sorted((run_dir / "control").glob("*.png"))
    if not control_stills:
        raise SpikeError(
            f"No control stills in {run_dir / 'control'}. Calibration needs a set of "
            f"DIFFERENT faces to measure separation against; without it there is no "
            f"threshold, only a number."
        )
    control = embed_images(embedder, control_stills, label="control")

    positives = _pairwise(master)
    negatives = cross_similarities(list(master.vectors), list(control.vectors))
    cal = calibrate(positives, negatives, embedder.info, target_fpr=args.target_fpr)

    log.write_artifact("calibration.json", cal.to_json())
    log.event("calibrated", verdict=cal.verdict, threshold=cal.threshold, auc=cal.auc)

    print(f"calibration  verdict={cal.verdict}")
    print(f"  overlap  {cal.overlap:.3f}   auc {cal.auc:.4f}   d' {cal.d_prime:.2f}")
    print(
        f"  threshold {cal.threshold:.4f}  (fpr {cal.fpr_at_threshold:.4f}, "
        f"tpr {cal.tpr_at_threshold:.4f})"
    )
    print(f"  master {master.counts()}  control {control.counts()}")
    for w in cal.warnings:
        print(f"  ! {w}")

    if args.write_config and not cal.embedder_is_stub:
        write_threshold(args.config, cal.threshold, cal.calibrated_on)
        print(f"  threshold written to {args.config}")
    elif args.write_config:
        print("  (refusing to write a stub-derived threshold to config)")
    return 0


def _pairwise(es: EmbeddingSet) -> list[float]:
    from .embed import pairwise_similarities

    return pairwise_similarities(list(es.vectors))


def _generate_and_score(
    *,
    cfg: SpikeConfig,
    run_dir: Path,
    log: RunLog,
    ledger: CostLedger,
    embedder: Any,
    master: EmbeddingSet,
    cal: Calibration,
    ref: str,
    prompt: str,
    seed: int,
    image_slot: str,
    video_slot: str,
    condition: dict[str, str] | None = None,
) -> ClipScore:
    """Keyframe -> clip -> score, with every paid step through the ledger."""
    image_cfg = cfg.provider("image", image_slot)
    video_cfg = cfg.provider("video", video_slot)
    image_provider = load_provider(image_cfg)
    video_provider = load_provider(video_cfg)
    duration = float(cfg.generation.get("clip_duration_s", 5))

    keyframe_path = run_dir / "keyframes" / f"{ref}.png"
    with ledger.paid_call(image_cfg, 1, ref=f"{ref}:keyframe", prompt=prompt) as outcome:
        image_provider.generate(ImageRequest(prompt=prompt, seed=seed, ref=ref), keyframe_path)
        outcome.ok = True

    clip_path = run_dir / "clips" / ref
    with ledger.paid_call(video_cfg, duration, ref=f"{ref}:clip", prompt=prompt) as outcome:
        video_provider.generate(
            VideoRequest(
                keyframe=keyframe_path, prompt=prompt, duration_s=duration, seed=seed, ref=ref
            ),
            clip_path,
        )
        outcome.ok = True

    score = score_clip(
        clip_path,
        embedder,
        master,
        cal,
        ref=ref,
        fps=cfg.embedder.frame_sample_fps,
        frames_dir=run_dir / "frames" / ref,
        frame_source=ImageSequenceFrames() if clip_path.is_dir() else None,
        condition=condition,
    )
    log.event(
        "scored",
        ref=ref,
        passed=score.passed,
        min_score=score.identity_score_min,
        presence=score.face_presence,
        reason=score.failure_reason,
    )
    return score


def cmd_run_matrix(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    log = RunLog(run_dir)
    ledger = _ledger(cfg, log, args.budget)
    embedder = _embedder(cfg, args.embedder)
    master = _master_set(run_dir, embedder)
    cal = _load_calibration(run_dir)

    n = args.cells or int(cfg.generation.get("identity_matrix_cells", 24))
    seed = int(cfg.generation.get("seed", 0))
    conditions: list[Condition] = sample_matrix(n, seed=seed)
    gaps = coverage_gaps(conditions)
    if gaps:
        raise SpikeError(f"Condition sample misses axis levels {gaps}; breakdown would be invalid.")
    log.event("matrix_sampled", cells=n, coverage=coverage(conditions))

    scores: list[ClipScore] = []
    for i, cond in enumerate(conditions):
        ref = f"matrix-{i:03d}-{cond.cell_id}"
        prompt = f"{args.subject}, {cond.prompt_fragment()}"
        try:
            score = _generate_and_score(
                cfg=cfg,
                run_dir=run_dir,
                log=log,
                ledger=ledger,
                embedder=embedder,
                master=master,
                cal=cal,
                ref=ref,
                prompt=prompt,
                seed=seed + i,
                image_slot=args.image_slot,
                video_slot=args.video_slot,
                condition=cond.as_dict(),
            )
        except SpikeError as exc:
            log.event("matrix_halted", ref=ref, error=str(exc))
            print(f"halted at clip {i + 1}/{n}: {exc}", file=sys.stderr)
            break
        scores.append(score)
        flag = "pass" if score.passed else f"FAIL ({score.failure_reason})"
        print(f"  [{i + 1:>3}/{n}] {cond.cell_id:<44} {flag}")

    _save_scores(run_dir, scores)
    log.write_artifact("ledger_summary.json", ledger.summary())
    passed = sum(1 for s in scores if s.passed)
    print(f"\n{passed}/{len(scores)} passed · spent ${ledger.spent} of ${ledger.budget_usd}")
    return 0


def cmd_battery(args: argparse.Namespace) -> int:
    """Generate the golf battery and emit a rating sheet for manual scoring."""
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    log = RunLog(run_dir)
    ledger = _ledger(cfg, log, args.budget)
    embedder = _embedder(cfg, args.embedder)
    master = _master_set(run_dir, embedder)
    cal = _load_calibration(run_dir)

    takes = args.takes or int(cfg.generation.get("takes_per_battery_prompt", 2))
    slots = args.video_slots
    seed = int(cfg.generation.get("seed", 0))
    rows: list[dict[str, Any]] = []
    scores: list[ClipScore] = []

    for item in GOLF_BATTERY:
        for slot in slots:
            for take in range(takes):
                ref = f"battery-{item['id']}-{slot}-{take}"
                prompt = f"{args.subject}, {item['prompt']}"
                try:
                    score = _generate_and_score(
                        cfg=cfg,
                        run_dir=run_dir,
                        log=log,
                        ledger=ledger,
                        embedder=embedder,
                        master=master,
                        cal=cal,
                        ref=ref,
                        prompt=prompt,
                        seed=seed + len(rows),
                        image_slot=args.image_slot,
                        video_slot=slot,
                    )
                except SpikeError as exc:
                    log.event("battery_halted", ref=ref, error=str(exc))
                    print(f"halted: {exc}", file=sys.stderr)
                    _write_battery_sheet(run_dir, rows)
                    return 1
                scores.append(score)
                rows.append(
                    {
                        "ref": ref,
                        "format_id": item["id"],
                        "predicted_hard": "yes" if item["hard"] else "no",
                        "provider": slot,
                        "take": take,
                        "clip_path": str(run_dir / "clips" / ref),
                        "identity_min": (
                            f"{score.identity_score_min:.4f}"
                            if score.identity_score_min is not None
                            else ""
                        ),
                        "rating": "",
                        "failure_tags": "",
                        "notes": "",
                    }
                )
                print(f"  {ref}")

    _save_scores(run_dir, scores, "battery_scores.json")
    sheet = _write_battery_sheet(run_dir, rows)
    log.write_artifact("ledger_summary_battery.json", ledger.summary())
    print(f"\n{len(rows)} takes · spent ${ledger.spent}")
    print(f"rating sheet: {sheet}")
    print(f"  fill in `rating` 1-5 and `failure_tags` from: {'|'.join(FAILURE_TAGS)}")
    return 0


def _write_battery_sheet(run_dir: Path, rows: list[dict[str, Any]]) -> Path:
    dest = run_dir / "battery_ratings.csv"
    if not rows:
        return dest
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return dest


def cmd_lipsync_probe(args: argparse.Namespace) -> int:
    """S0.8: does lip sync move the identity score, and by how much?"""
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    log = RunLog(run_dir)
    ledger = _ledger(cfg, log, args.budget)
    embedder = _embedder(cfg, args.embedder)
    master = _master_set(run_dir, embedder)
    cal = _load_calibration(run_dir)

    before = [s for s in _load_scores(run_dir) if s.passed][: args.count]
    if not before:
        raise SpikeError(
            "No passing clips to probe. Run `run-matrix` first; the probe measures "
            "what lip sync does to takes that had already been accepted."
        )

    lip_cfg = cfg.provider("lipsync", args.lipsync_slot)
    provider = load_provider(lip_cfg)
    duration = float(cfg.generation.get("clip_duration_s", 5))
    results: list[dict[str, Any]] = []
    for s in before:
        src = run_dir / "clips" / s.ref
        dest = run_dir / "lipsync" / s.ref
        with ledger.paid_call(lip_cfg, duration, ref=f"{s.ref}:lipsync") as outcome:
            provider.apply(LipSyncRequest(clip=src, audio=None, ref=s.ref), dest)
            outcome.ok = True
        after = score_clip(
            dest,
            embedder,
            master,
            cal,
            ref=f"{s.ref}:lipsync",
            fps=cfg.embedder.frame_sample_fps,
            frames_dir=run_dir / "frames" / f"{s.ref}-lipsync",
            frame_source=ImageSequenceFrames(),
            condition=s.condition,
        )
        delta = (
            after.identity_score_min - s.identity_score_min
            if after.identity_score_min is not None and s.identity_score_min is not None
            else None
        )
        results.append(
            {
                "label": s.ref,
                "before_min": s.identity_score_min,
                "after_min": after.identity_score_min,
                "delta": delta,
                "after_passes": after.passed,
            }
        )
        print(
            f"  {s.ref}: {s.identity_score_min:.4f} -> "
            f"{after.identity_score_min:.4f} ({delta:+.4f})"
        )

    deltas = [r["delta"] for r in results if r["delta"] is not None]
    probe: dict[str, Any] = {
        "clips": results,
        "mean_delta": sum(deltas) / len(deltas) if deltas else None,
    }
    log.write_artifact("lipsync_probe.json", probe)
    if probe["mean_delta"] is not None:
        print(f"\nmean delta {probe['mean_delta']:+.4f}")
    return 0


def cmd_contact_sheet(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    scores = _load_scores(run_dir)
    if not scores:
        raise SpikeError("No scores.json in the run. Run `run-matrix` first.")
    dest = build_contact_sheet(worst_first(scores), run_dir / "contact_sheet.png")
    print(f"contact sheet: {dest}  ({len(scores)} clips, worst first)")
    return 0


def cmd_time(args: argparse.Namespace) -> int:
    """Log operator minutes. BUILD_PLAN Section 9's deciding metric."""
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    log = RunLog(run_dir)
    log.event("operator_time", task=args.task, minutes=args.minutes, note=args.note or "")
    total = sum(float(e.get("minutes", 0)) for e in log.read("operator_time"))
    print(f"logged {args.minutes} min to {args.task} · run total {total:.0f} min")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    log = RunLog(run_dir)
    cal = _load_calibration(run_dir)
    scores = _load_scores(run_dir)

    summary_path = run_dir / "ledger_summary.json"
    ledger_summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    probe_path = run_dir / "lipsync_probe.json"
    probe = json.loads(probe_path.read_text()) if probe_path.exists() else None
    ratings_path = run_dir / "battery_ratings.csv"
    ratings = None
    if ratings_path.exists():
        with ratings_path.open(encoding="utf-8") as fh:
            ratings = [r for r in csv.DictReader(fh) if (r.get("rating") or "").strip()]

    sheet = run_dir / "contact_sheet.png"
    duration = float(cfg.generation.get("clip_duration_s", 5))
    usable_seconds = sum(1 for s in scores if s.passed) * duration

    text = render_gate_report(
        run_id=run_dir.name,
        calibration=cal,
        scores=scores,
        ledger_summary=ledger_summary,
        contact_sheet=sheet if sheet.exists() else None,
        lipsync_probe=probe,
        battery_ratings=ratings,
        operator_time=log.read("operator_time"),
        usable_seconds=usable_seconds or None,
        allow_fake=args.allow_fake,
    )
    dest = Path(args.out) if args.out else run_dir / "gate-a.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"gate report: {dest}")
    if args.allow_fake:
        print("  ! marked NOT EVIDENCE: generated with --allow-fake")
    return 0


def _calibrate_with(
    cfg: SpikeConfig, run_dir: Path, backend: str, target_fpr: float
) -> Calibration:
    embedder = _embedder(cfg, backend)
    master = _master_set(run_dir, embedder)
    control_stills = sorted((run_dir / "control").glob("*.png"))
    if not control_stills:
        raise SpikeError(f"No control stills in {run_dir / 'control'}.")
    control = embed_images(embedder, control_stills, label="control")
    return calibrate(
        _pairwise(master),
        cross_similarities(list(master.vectors), list(control.vectors)),
        embedder.info,
        target_fpr=target_fpr,
    )


def cmd_fetch_models(args: argparse.Namespace) -> int:
    """Download the ADR 0002 candidate weights, then tell you what to read.

    Deliberately does not fill in the licence fields. The gate in
    EmbedderConfig.require_usable exists so that somebody read the text; a
    fetcher that ticked it off would defeat the point of having it.
    """
    dest_dir = Path(args.dest)
    wanted = [
        m
        for m in MODELS
        if args.backend in (None, m.backend) and (not m.optional or m.key in args.include)
    ]
    if not args.include:
        skipped = [m.key for m in MODELS if m.optional and args.backend in (None, m.backend)]
        if skipped:
            print(f"  (skipping alternatives: {', '.join(skipped)} — add with --include)\n")
    fetched: dict[str, Path] = {}
    failures: list[str] = []

    for model in wanted:
        print(f"  {model.key:<18} {model.url}")
        try:
            path = fetch(model, dest_dir, force=args.force)
        except SpikeError as exc:
            failures.append(f"{model.key}: {exc}")
            print(f"  {'':<18} FAILED — see below", file=sys.stderr)
            continue
        fetched[model.key] = path
        print(f"  {'':<18} -> {path}  ({path.stat().st_size:,} bytes)")
        print(f"  {'':<18}    sha256 {sha256_of(path)}")

    if failures:
        print("\nSome files did not download:", file=sys.stderr)
        for failure in failures:
            print(f"\n  {failure}", file=sys.stderr)

    if not fetched:
        return 2

    print("\n" + "=" * 72)
    print("NOW READ THE LICENCES. Nothing runs until you have.\n")
    for model in wanted:
        if model.key not in fetched:
            continue
        print(f"  {model.key}")
        print(f"    {model.licence_where}")
        print(f"    {model.licence_note}\n")

    print("=" * 72)
    print("Then paste into config/spike.yaml, filling in the two blank fields:\n")
    print(config_snippet(fetched))
    print("\nThen: python -m scripts.spike.cli bake-off --backends dlib dinov2")
    return 0


def cmd_bake_off(args: argparse.Namespace) -> int:
    """Calibrate several embedder backends on the same data and compare.

    This is how ADR 0002 gets decided: not on published benchmarks, which
    measure real-identity recognition, but on which candidate separates OUR
    distributions -- synthetic renders of one invented character against other
    synthetic faces.
    """
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    log = RunLog(run_dir)

    results: dict[str, Any] = {}
    for backend in args.backends:
        try:
            cal = _calibrate_with(cfg, run_dir, backend, args.target_fpr)
        except SpikeError as exc:
            print(f"  {backend:<10} unavailable: {exc}", file=sys.stderr)
            results[backend] = {"error": str(exc)}
            continue
        results[backend] = cal.to_json()
        log.write_artifact(f"calibration_{backend}.json", cal.to_json())

    usable = {k: v for k, v in results.items() if "error" not in v}
    print(
        f"\n{'backend':<10} {'verdict':<10} {'overlap':>8} {'auc':>8} "
        f"{'thr':>8} {'tpr':>7} {'dim':>5}"
    )
    print("-" * 62)
    for name, cal in usable.items():
        mark = "   (STUB - not a candidate)" if cal["embedder_is_stub"] else ""
        print(
            f"{name:<10} {cal['verdict']:<10} {cal['overlap']:>8.3f} {cal['auc']:>8.4f} "
            f"{cal['threshold']:>8.4f} {cal['tpr_at_threshold']:>7.3f} "
            f"{cal['embedder_key'].rsplit('d', 1)[-1]:>5}{mark}"
        )

    if not usable:
        print("\nNo candidate ran. Fill in the model paths in config/spike.yaml first.")
        return 2

    # A stub can post a perfect score on fixtures it was never going to fail.
    # Letting one win a bake-off that decides ADR 0002 would be the worst failure
    # this command could have, so stubs are shown and never selected.
    real = {k: v for k, v in usable.items() if not v["embedder_is_stub"]}
    if not real:
        print(
            "\nOnly stub backends ran, and a stub is never a candidate: it is pixel "
            "statistics scoring fixtures it cannot fail. Configure dlib or dinov2 in "
            "config/spike.yaml and run this again."
        )
        return 2

    # Rank on overlap, then TPR: the winner is the one that separates, and
    # among those, the one that throws away fewest good takes.
    winner = min(real.items(), key=lambda kv: (kv[1]["overlap"], -kv[1]["tpr_at_threshold"]))
    log.write_artifact("bake_off.json", {"results": results, "winner": winner[0]})
    print(f"\nseparates best: {winner[0]}")
    if not Calibration(
        **{**winner[1], "calibrated_on": dt.date.fromisoformat(winner[1]["calibrated_on"])}
    ).trustworthy:
        print(
            "  ! No candidate is trustworthy. Neither free option separates your data, "
            "which is the evidence for buying a commercial licence (ADR 0002 route A) "
            "-- or a finding that automated scoring must be advisory, not gating."
        )
    print(
        "  Check the worst-frame contact sheet before accepting this: a scorer that "
        "agrees with the statistics and disagrees with your eye is still the wrong scorer."
    )
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Run the whole harness offline on fakes, to validate it end to end."""
    ns = argparse.Namespace(config=args.config, run=None, embedder="stub")
    cfg = load_config(args.config)
    run_id = new_run_id()
    RunLog(cfg.run_root / run_id).event("run_started", note="offline demo")
    print(f"run {run_id}")
    ns.run = run_id

    cmd_make_fixtures(argparse.Namespace(**vars(ns), master_count=10, control_count=16))
    cmd_calibrate(argparse.Namespace(**vars(ns), target_fpr=0.01, write_config=False))
    cmd_run_matrix(
        argparse.Namespace(
            **vars(ns),
            budget="5.00",
            cells=args.cells,
            subject="the persona",
            image_slot="fake",
            video_slot="fake",
        )
    )
    cmd_contact_sheet(argparse.Namespace(config=args.config, run=run_id))
    cmd_lipsync_probe(argparse.Namespace(**vars(ns), budget="5.00", count=3, lipsync_slot="fake"))
    cmd_time(
        argparse.Namespace(
            config=args.config, run=run_id, task="S0-demo", minutes=0, note="automated demo"
        )
    )
    cmd_report(argparse.Namespace(config=args.config, run=run_id, allow_fake=True, out=None))
    return 0


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spike", description=__doc__)
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    sub = p.add_subparsers(dest="command", required=True)

    def add_run(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--run", help="run id (default: most recent)")

    def add_embedder(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--embedder",
            help="override embedder backend. Use 'stub' for offline work; it is "
            "pixel statistics, not face recognition.",
        )

    def add_budget(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--budget",
            required=True,
            help="hard spend cap in USD for this command. Required: no live provider "
            "call happens outside an explicitly budgeted run.",
        )

    sp = sub.add_parser("init-run", help="start a run directory")
    add_run(sp)
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_init_run)

    sp = sub.add_parser("make-fixtures", help="synthetic master/control sets for offline work")
    add_run(sp)
    sp.add_argument("--master-count", type=int, default=10)
    sp.add_argument("--control-count", type=int, default=16)
    sp.set_defaults(func=cmd_make_fixtures)

    sp = sub.add_parser("calibrate", help="S0.3 threshold calibration")
    add_run(sp)
    add_embedder(sp)
    sp.add_argument("--target-fpr", type=float, default=0.01)
    sp.add_argument("--write-config", action="store_true", help="persist the threshold")
    sp.set_defaults(func=cmd_calibrate)

    sp = sub.add_parser("matrix", help="print the sampled condition matrix")
    sp.add_argument("--cells", type=int, default=24)
    sp.add_argument("--seed", type=int, default=20260922)
    sp.set_defaults(func=cmd_matrix)

    sp = sub.add_parser("run-matrix", help="S0.5/S0.6 generate and score the condition matrix")
    add_run(sp)
    add_embedder(sp)
    add_budget(sp)
    sp.add_argument("--cells", type=int)
    sp.add_argument("--subject", default="the persona")
    sp.add_argument("--image-slot", default="primary")
    sp.add_argument("--video-slot", default="flagship")
    sp.set_defaults(func=cmd_run_matrix)

    sp = sub.add_parser("battery", help="S0.7 golf format battery + rating sheet")
    add_run(sp)
    add_embedder(sp)
    add_budget(sp)
    sp.add_argument("--takes", type=int)
    sp.add_argument("--subject", default="the persona")
    sp.add_argument("--image-slot", default="primary")
    sp.add_argument("--video-slots", nargs="+", default=["flagship", "budget"])
    sp.set_defaults(func=cmd_battery)

    sp = sub.add_parser("lipsync-probe", help="S0.8 identity drift through lip sync")
    add_run(sp)
    add_embedder(sp)
    add_budget(sp)
    sp.add_argument("--count", type=int, default=3)
    sp.add_argument("--lipsync-slot", default="primary")
    sp.set_defaults(func=cmd_lipsync_probe)

    sp = sub.add_parser("contact-sheet", help="worst-frame contact sheet")
    add_run(sp)
    sp.set_defaults(func=cmd_contact_sheet)

    sp = sub.add_parser("time", help="S0.9 log operator minutes")
    add_run(sp)
    sp.add_argument("--task", required=True)
    sp.add_argument("--minutes", type=float, required=True)
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_time)

    sp = sub.add_parser("report", help="S0.10 render the Gate A report")
    add_run(sp)
    sp.add_argument("--out")
    sp.add_argument(
        "--allow-fake",
        action="store_true",
        help="render from stub data. Stamps the report NOT EVIDENCE.",
    )
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("fetch-models", help="download the ADR 0002 candidate weights")
    sp.add_argument("--dest", default="models", help="where to put them (default: models/)")
    sp.add_argument("--backend", choices=["dlib", "dinov2"], help="just one candidate")
    sp.add_argument("--force", action="store_true", help="re-download existing files")
    sp.add_argument(
        "--include",
        nargs="+",
        default=[],
        metavar="KEY",
        help="also fetch an alternative file, e.g. dlib-densenet",
    )
    sp.set_defaults(func=cmd_fetch_models)

    sp = sub.add_parser("bake-off", help="ADR 0002: calibrate several backends side by side")
    add_run(sp)
    sp.add_argument("--backends", nargs="+", default=["dlib", "dinov2"])
    sp.add_argument("--target-fpr", type=float, default=0.01)
    sp.set_defaults(func=cmd_bake_off)

    sp = sub.add_parser("demo", help="run the whole harness offline on fakes")
    sp.add_argument("--cells", type=int, default=12)
    sp.set_defaults(func=cmd_demo)

    return p


def cmd_matrix(args: argparse.Namespace) -> int:
    conditions = sample_matrix(args.cells, seed=args.seed)
    for i, cond in enumerate(conditions):
        print(f"{i:>3}  {cond.cell_id:<46} {cond.prompt_fragment()}")
    print("\ncoverage:")
    for axis, counts in coverage(conditions).items():
        print(f"  {axis:<9} {counts}")
    gaps = coverage_gaps(conditions)
    print(f"gaps: {gaps or 'none'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except SpikeError as exc:
        print(f"\n{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
