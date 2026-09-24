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
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from .calibrate import Calibration, calibrate
from .config import (
    DEFAULT_CONFIG_PATH,
    EmbedderConfig,
    SpikeConfig,
    load_config,
    write_threshold,
)
from .contactsheet import build_contact_sheet, worst_first
from .embed import (
    EmbeddingSet,
    centroid_similarities,
    embed_images,
    leave_one_out_centroid_similarities,
    load_embedder,
)
from .embedders import DETECTORS
from .errors import BudgetExceeded, BudgetNotSet, ProviderRefused, SpikeError
from .frames import ImageSequenceFrames
from .ingest import IMAGE_SUFFIXES, find_images, format_report, ingest
from .inspect import format_inspection, inspect_sets
from .ledger import CostLedger
from .matrix import (
    FAILURE_TAGS,
    PROMPT_SETS,
    Condition,
    coverage,
    coverage_gaps,
    sample_matrix,
    select_shots,
)
from .models import MODELS, config_snippet, fetch, sha256_of, write_paths
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
from .selfcheck import (
    format_result,
    run_check,
    sample_images_from,
)

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


def _embedder_config(cfg: SpikeConfig, override: str | None) -> EmbedderConfig:
    """Resolve a backend's config, filling in defaults for ones with no block.

    The stub has no entry under ``embedder.backends`` because it has nothing
    real to declare, so it would otherwise fail the dimension gate that exists
    to stop real backends being left unpinned.
    """
    emb_cfg = cfg.embedder_for(override)
    if emb_cfg.dim is None:
        emb_cfg = dataclasses.replace(
            emb_cfg,
            model=emb_cfg.model or f"{emb_cfg.backend}-override",
            version=emb_cfg.version or "0",
            dim=256,
        )
    return emb_cfg


def _embedder(cfg: SpikeConfig, override: str | None) -> Any:
    embedder = load_embedder(_embedder_config(cfg, override))
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


def _stills_in(directory: Path, which: str) -> list[Path]:
    """Every image in a set directory, whatever the file extension.

    Deliberately not `glob("*.png")`, which is what this was and which made
    calibration silently see an empty folder for any set of JPEGs. `prepare-set`
    preserves the extension it was given, and most people's photographs are
    JPEG, so the two halves disagreed about what an image was.
    """
    if not directory.is_dir():
        raise SpikeError(
            f"No {which} directory at {directory}. Add stills with "
            f"`prepare-set <folder> --which {which}`."
        )
    stills = find_images(directory)
    if not stills:
        raise SpikeError(
            f"No {which} stills in {directory}. The folder exists but holds no images "
            f"(looked for {', '.join(IMAGE_SUFFIXES)})."
        )
    return stills


def _master_set(run_dir: Path, embedder: Any) -> EmbeddingSet:
    return embed_images(embedder, _stills_in(run_dir / "master", "master"), label="master")


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
        for derived in (
            "face_presence",
            "fraction_below_threshold",
            "longest_run_fraction",
            "identity_verdict",
            "identity_passed",
            "needs_review",
            "failure_reason",
        ):
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


def cmd_prepare_set(args: argparse.Namespace) -> int:
    """S0.1: validate a folder of stills, then copy the usable ones into the run.

    Fails early and legibly. Calibrating on a set the detector cannot read
    gives either a crash or, worse, a confident threshold computed from three
    images — which reaches the Gate A report looking like a finding about the
    persona rather than a problem with the input.
    """
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    embedder = _embedder(cfg, args.embedder)

    source = Path(args.source)
    if not source.is_dir():
        raise SpikeError(f"{source} is not a directory")

    dest = run_dir / args.which
    report = ingest(source, dest, args.which, embedder, copy=not args.dry_run)
    print(format_report(report, dest))

    log = RunLog(run_dir)
    if report.sources:
        # Merged, not overwritten: master and control are prepared by separate
        # invocations and both belong in the same map.
        merged = {**_read_sources(run_dir), **report.sources}
        log.write_artifact(SOURCES_ARTIFACT, merged)

    log.event(
        "set_prepared",
        which=args.which,
        source=str(source),
        candidates=len(report.candidates),
        usable=len(report.usable),
        copied=len(report.copied),
        dry_run=args.dry_run,
    )
    return 0 if report.usable else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    log = RunLog(run_dir)
    embedder = _embedder(cfg, args.embedder)

    master = _master_set(run_dir, embedder)
    control_stills = _stills_in(run_dir / "control", "control")
    control = embed_images(embedder, control_stills, label="control")

    positives, negatives = _calibration_distributions(master, control)
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


SOURCES_ARTIFACT = "sources.json"


def _read_sources(run_dir: Path) -> dict[str, str]:
    """Prepared filename -> the image it was copied from.

    Absent for runs prepared before this was recorded, and for fixture runs.
    Missing entries degrade to bare filenames rather than failing: a run you
    cannot fully trace is still worth inspecting.
    """
    path = run_dir / SOURCES_ARTIFACT
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}


def _calibration_distributions(
    master: EmbeddingSet, control: EmbeddingSet
) -> tuple[list[float], list[float]]:
    """The two distributions a threshold is drawn between.

    Both are measured in the space `score.py` scores in — cosine against the
    master centroid — because a threshold is only meaningful in the space it
    was measured in. This was pairwise once, and the mismatch made every
    threshold systematically too lenient: centroid similarity runs higher than
    pairwise similarity, so a cut point drawn on pairwise numbers sits below
    where the scorer reads. Every calibration path goes through here so the
    two cannot drift apart again.
    """
    return (
        leave_one_out_centroid_similarities(list(master.vectors)),
        centroid_similarities(list(control.vectors), master.centroid()),
    )


def _generate_with_retry(*, attempts: int = 3, **kwargs: Any) -> ClipScore:
    """Retry a refusal the provider is measurably inconsistent about.

    fal's content checker refused an image-and-prompt pair and then accepted
    the identical pair moments later, so a single refusal says little (ADR
    0006). Retrying is close to free: a refused call is never billed, and the
    alternative is losing the cell and biasing the matrix towards whichever
    conditions the checker happened to allow that minute.

    Only refusals on the provider's own retryable list are re-attempted. A
    no_media_generated is a property of the input -- one master still failed
    four times out of four -- so retrying it spends time to learn nothing.
    """
    from .fal import RETRYABLE_REFUSALS

    last: ProviderRefused | None = None
    for attempt in range(max(1, attempts)):
        try:
            return _generate_and_score(**kwargs)
        except ProviderRefused as exc:
            if exc.error_type not in RETRYABLE_REFUSALS:
                raise
            last = exc
            if attempt + 1 < attempts:
                print(f"      retrying after {exc.error_type} ({attempt + 1}/{attempts - 1})")
    assert last is not None
    raise last


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
    keyframe: Path | None = None,
    last_keyframe: Path | None = None,
) -> ClipScore:
    """Keyframe -> clip -> score, with every paid step through the ledger.

    ``keyframe`` supplies an existing still instead of generating one. That is
    the S0.5 shape: the question is whether a still of her survives being
    animated, and the keyframe generator it would otherwise use is the LoRA
    from S0.4, which does not exist yet. Supplying one skips the image
    provider entirely, so no image slot needs configuring and no image cost is
    incurred.
    """
    video_cfg = cfg.provider("video", video_slot)
    video_provider = load_provider(video_cfg)
    duration = float(cfg.generation.get("clip_duration_s", 5))

    if keyframe is not None:
        keyframe_path = keyframe
    else:
        image_cfg = cfg.provider("image", image_slot)
        image_provider = load_provider(image_cfg)
        keyframe_path = run_dir / "keyframes" / f"{ref}.png"
        with ledger.paid_call(image_cfg, 1, ref=f"{ref}:keyframe", prompt=prompt) as outcome:
            image_provider.generate(ImageRequest(prompt=prompt, seed=seed, ref=ref), keyframe_path)
            outcome.ok = True

    # Which still produced a clip decides what to do about that clip, and it
    # was not recorded: a no_media refusal is a property of the (keyframe,
    # prompt) pair, and a clip whose body or limbs come out wrong implicates
    # the still it was animated from. Both had to be reconstructed by replaying
    # the keyframe cursor against the queue timestamps, which is guesswork the
    # log should not require.
    log.event(
        "keyframe_selected",
        ref=ref,
        keyframe=str(keyframe_path),
        supplied=keyframe is not None,
    )

    clip_path = run_dir / "clips" / ref
    # Clear whatever is already there. Providers legitimately disagree about
    # the shape of a clip -- the fake writes a directory of stills so it needs
    # no encoder, a hosted one writes a single file -- so a re-run that changes
    # provider finds the wrong kind of thing in the way. That cost a paid clip
    # once: the video generated, and the download died on IsADirectoryError
    # against a directory the previous dry run had left behind.
    if clip_path.is_dir():
        shutil.rmtree(clip_path)
    elif clip_path.exists():
        clip_path.unlink()

    # Record the provider's own id for the job the instant it is queued. A run
    # that dies between submitting and downloading has still been billed, and
    # without this the paid-for clip is unfindable -- which happened once, for
    # $2 and nothing to show.
    if hasattr(video_provider, "on_submit") and video_provider.on_submit is None:
        video_provider.on_submit = lambda q: log.event(
            "provider_request_queued", ref=ref, request_id=q.request_id, status_url=q.status_url
        )

    with ledger.paid_call(video_cfg, duration, ref=f"{ref}:clip", prompt=prompt) as outcome:
        video_provider.generate(
            VideoRequest(
                keyframe=keyframe_path,
                last_keyframe=last_keyframe,
                prompt=prompt,
                duration_s=duration,
                seed=seed,
                ref=ref,
            ),
            clip_path,
        )
        outcome.ok = True
        outcome.artifact = str(clip_path)

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
        identity_passed=score.identity_passed,
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

    # getattr, not args.keyframes: `demo` reuses this function through its own
    # parser, which has no such option. A test caught it.
    keyframe_dir = getattr(args, "keyframes", None)
    keyframes: list[Path] = []
    if keyframe_dir:
        keyframes = _stills_in(Path(keyframe_dir), "keyframes")
        print(f"using {len(keyframes)} existing keyframes from {keyframe_dir}")

    n = args.cells or int(cfg.generation.get("identity_matrix_cells", 24))
    seed = int(cfg.generation.get("seed", 0))
    conditions: list[Condition] = sample_matrix(n, seed=seed)
    gaps = coverage_gaps(conditions)
    if gaps:
        raise SpikeError(f"Condition sample misses axis levels {gaps}; breakdown would be invalid.")
    log.event("matrix_sampled", cells=n, coverage=coverage(conditions))

    scores: list[ClipScore] = []
    #: Cells the provider would not produce. Reported separately from failures:
    #: a clip that was never generated is not a clip that scored badly, and
    #: conflating them would understate the identity result.
    skipped: list[tuple[str, str]] = []
    max_skips = max(3, n // 3)
    retries = int(cfg.generation.get("refusal_retries", 3))
    for i, cond in enumerate(conditions):
        ref = f"matrix-{i:03d}-{cond.cell_id}"
        prompt = f"{args.subject}, {cond.prompt_fragment()}"
        try:
            score = _generate_with_retry(
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
                keyframe=keyframes[i % len(keyframes)] if keyframes else None,
                attempts=retries,
            )
        except (BudgetExceeded, BudgetNotSet) as exc:
            # The one thing that must stop the run. Carrying on past the cap is
            # the failure the guard exists to prevent.
            log.event("matrix_halted", ref=ref, error=str(exc))
            print(f"halted at clip {i + 1}/{n}: {exc}", file=sys.stderr)
            break
        except SpikeError as exc:
            # One cell the provider would not produce must not end the matrix.
            # fal's content checker is non-deterministic (ADR 0006), so halting
            # on the first refusal means a matrix rarely finishes -- and the
            # cells that do finish are not a random sample of those attempted,
            # which is a biased result wearing the clothes of a partial one.
            skipped.append((ref, str(exc)))
            log.event("matrix_cell_skipped", ref=ref, error=str(exc))
            first = str(exc).splitlines()[0]
            print(f"  [{i + 1:>3}/{n}] {cond.cell_id:<44} SKIPPED ({first[:80]})")
            if len(skipped) >= max_skips:
                log.event("matrix_halted", ref=ref, error=f"{len(skipped)} cells skipped")
                print(
                    f"stopping: {len(skipped)} cells could not be generated. "
                    "Something systematic is wrong, and burning budget discovering "
                    "that one cell at a time helps nobody.",
                    file=sys.stderr,
                )
                break
            continue
        scores.append(score)
        flag = (
            "identity ok"
            if score.identity_passed
            else f"identity {score.identity_verdict.upper()} ({score.failure_reason})"
        )
        print(f"  [{i + 1:>3}/{n}] {cond.cell_id:<44} {flag}")

    if skipped:
        print(f"\n{len(skipped)} cell(s) never generated — not scored, not failures:")
        for ref, err in skipped:
            print(f"  {ref}: {err.splitlines()[0][:100]}")
        print(
            "  A cell the provider refused is missing evidence, not bad evidence. "
            "Read the pass rate below as being over the cells that ran."
        )

    _save_scores(run_dir, scores)
    log.write_artifact("ledger_summary.json", ledger.summary())
    identity_passed = sum(1 for s in scores if s.identity_passed)
    print(
        f"\n{identity_passed}/{len(scores)} passed the identity gate "
        f"· spent ${ledger.spent} of ${ledger.budget_usd}"
    )
    return 0


def _generate_trying_keyframes(
    keyframes: list[Path], start: int, last_keyframes: list[Path] | None = None, **kwargs: Any
) -> tuple[ClipScore, int]:
    """Generate a shot, moving to another keyframe if one is refused outright.

    ``no_media_generated`` is deterministic for a given (keyframe, prompt)
    pair -- one master still failed four times out of four (ADR 0006) -- so
    retrying it unchanged spends time to learn nothing, but retrying it with a
    different still is a genuinely different request. Refused calls are never
    billed, so this costs time only.

    Indexing used to advance only on success, which meant one bad still jammed
    every shot after it: three of the six coverage-probe shots were refused in
    a row on 2026-09-24, all against the same keyframe.
    """
    if not keyframes:
        return _generate_with_retry(keyframe=None, last_keyframe=None, **kwargs), start
    last: ProviderRefused | None = None
    for offset in range(len(keyframes)):
        index = (start + offset) % len(keyframes)
        try:
            last_frame = last_keyframes[index % len(last_keyframes)] if last_keyframes else None
            return (
                _generate_with_retry(keyframe=keyframes[index], last_keyframe=last_frame, **kwargs),
                index + 1,
            )
        except ProviderRefused as exc:
            last = exc
    assert last is not None
    raise last


def cmd_battery(args: argparse.Namespace) -> int:
    """Generate the golf battery and emit a rating sheet for manual scoring."""
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    log = RunLog(run_dir)
    ledger = _ledger(cfg, log, args.budget)
    embedder = _embedder(cfg, args.embedder)
    master = _master_set(run_dir, embedder)
    cal = _load_calibration(run_dir)

    prompt_set = getattr(args, "prompt_set", "golf")
    items = PROMPT_SETS[prompt_set]
    try:
        items = select_shots(items, getattr(args, "shots", None), prompt_set)
    except ValueError as exc:
        raise SpikeError(str(exc)) from exc
    # The ref prefix keeps the two sets' artifacts apart in a shared run dir.
    prefix = "battery" if prompt_set == "golf" else prompt_set

    takes = args.takes or int(cfg.generation.get("takes_per_battery_prompt", 2))
    keyframe_dir = getattr(args, "keyframes", None)
    keyframes: list[Path] = []
    if keyframe_dir:
        keyframes = _stills_in(Path(keyframe_dir), "keyframes")
        print(f"using {len(keyframes)} existing keyframes from {keyframe_dir}")
    last_keyframes: list[Path] = []
    last_dir = getattr(args, "last_keyframes", None)
    if last_dir:
        last_keyframes = _stills_in(Path(last_dir), "last-keyframes")
        print(f"using {len(last_keyframes)} last-frame stills from {last_dir}")

    retries = int(cfg.generation.get("refusal_retries", 3))
    skipped: list[tuple[str, str]] = []
    max_skips = max(3, (len(items) * len(args.video_slots) * takes) // 3)
    slots = args.video_slots
    seed = int(cfg.generation.get("seed", 0))
    rows: list[dict[str, Any]] = []
    scores: list[ClipScore] = []
    keyframe_cursor = 0

    for item in items:
        for slot in slots:
            for take in range(takes):
                ref = f"{prefix}-{item['id']}-{slot}-{take}"
                prompt = f"{args.subject}, {item['prompt']}"
                try:
                    score, keyframe_cursor = _generate_trying_keyframes(
                        keyframes,
                        keyframe_cursor,
                        last_keyframes=last_keyframes,
                        attempts=retries,
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
                except (BudgetExceeded, BudgetNotSet) as exc:
                    log.event("battery_halted", ref=ref, error=str(exc))
                    print(f"halted: {exc}", file=sys.stderr)
                    _write_battery_sheet(run_dir, rows, prefix)
                    return 1
                except SpikeError as exc:
                    # Same reasoning as the matrix: one shot the provider will
                    # not produce must not end the battery, and a shot never
                    # generated is missing evidence rather than a bad take.
                    skipped.append((ref, str(exc)))
                    log.event("battery_cell_skipped", ref=ref, error=str(exc))
                    print(f"  {ref}: SKIPPED ({str(exc).splitlines()[0][:70]})")
                    if len(skipped) >= max_skips:
                        log.event("battery_halted", ref=ref, error=f"{len(skipped)} skipped")
                        print(
                            f"stopping: {len(skipped)} shots could not be generated.",
                            file=sys.stderr,
                        )
                        _write_battery_sheet(run_dir, rows, prefix)
                        return 1
                    continue
                scores.append(score)
                rows.append(
                    {
                        "ref": ref,
                        "format_id": item["id"],
                        "predicted_hard": "yes" if item["hard"] else "no",
                        "expected_coverage": (
                            f"{item['expect'][0]:.0%}-{item['expect'][1]:.0%}"
                            if "expect" in item
                            else ""
                        ),
                        "face_presence": f"{score.face_presence:.3f}",
                        "identity_verdict": score.identity_verdict,
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

    _save_scores(run_dir, scores, f"{prefix}_scores.json")
    sheet = _write_battery_sheet(run_dir, rows, prefix)
    log.write_artifact(f"ledger_summary_{prefix}.json", ledger.summary())
    print(f"\n{len(rows)} takes · spent ${ledger.spent}")
    print(f"rating sheet: {sheet}")
    if prompt_set == "golf":
        print(f"  fill in `rating` 1-5 and `failure_tags` from: {'|'.join(FAILURE_TAGS)}")
    else:
        print("  measured face_presence and verdict are in the sheet, per shot.")
    return 0


def _write_battery_sheet(
    run_dir: Path, rows: list[dict[str, Any]], prefix: str = "battery"
) -> Path:
    """Write the rating sheet.

    The prefix keeps prompt sets from overwriting each other's sheet in a
    shared run directory -- the same collision that cost a paid clip when a
    stale fake-provider output sat in a real clip's path.
    """
    dest = run_dir / f"{prefix}_ratings.csv"
    if not rows:
        return dest
    # --shots runs a subset, so these rows are a subset too. Overwriting would
    # drop shots already generated and paid for; merge on ref instead, newest
    # winning, so resuming a part-finished set accumulates.
    if dest.exists():
        with dest.open(newline="", encoding="utf-8") as fh:
            previous = {r["ref"]: r for r in csv.DictReader(fh)}
        fresh = {r["ref"]: r for r in rows}
        merged = {**previous, **fresh}
        rows = [merged[ref] for ref in sorted(merged)]
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

    before = [s for s in _load_scores(run_dir) if s.identity_passed][: args.count]
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
                "after_identity_passes": after.identity_passed,
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
    # Identity-passing is NOT the same as usable: a clip can clear the identity
    # gate and still be unpublishable (broken motion, anatomy, wrong shot). This
    # is therefore an UPPER BOUND on usable seconds, and the cost-per-usable-
    # second it feeds into BUILD_PLAN section 9 is correspondingly optimistic.
    identity_passing_seconds = sum(1 for s in scores if s.identity_passed) * duration

    text = render_gate_report(
        run_id=run_dir.name,
        calibration=cal,
        scores=scores,
        ledger_summary=ledger_summary,
        contact_sheet=sheet if sheet.exists() else None,
        lipsync_probe=probe,
        battery_ratings=ratings,
        operator_time=log.read("operator_time"),
        identity_passing_seconds=identity_passing_seconds or None,
        allow_fake=args.allow_fake,
    )
    dest = Path(args.out) if args.out else run_dir / "gate-a.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"gate report: {dest}")
    if args.allow_fake:
        print("  ! marked NOT EVIDENCE: generated with --allow-fake")
    return 0


def _require_usable_embeddings(embeddings: EmbeddingSet, which: str, backend: str) -> None:
    """Refuse to calibrate on a set the detector found no faces in.

    Without this the bake-off reaches ``calibrate`` with two empty lists and
    dies on a ValueError traceback that says nothing about the actual problem,
    which is images the face detector could not read. Seen for real: a fully
    configured DINOv2 pointed at the synthetic fixture images, where YuNet
    correctly finds nothing, because they are coloured shapes rather than
    photographs.
    """
    counts = embeddings.counts()
    if counts["usable"]:
        return
    raise SpikeError(
        f"{backend}: no usable embeddings from the {which} set. Of {counts['frames']} "
        f"images, {counts['no_face']} had no face detected and {counts['multi_face']} "
        f"had several.\n"
        f"  Most likely the {which} images are not photographs of one face each. The "
        f"fixtures written by `make-fixtures` are coloured shapes for harness testing "
        f"and a real detector will find nothing in them — put real stills in "
        f"<run>/{which}/ before calibrating.\n"
        f"  To test the model itself without detection, use "
        f"`check-embedder --detector whole-image`."
    )


def _calibrate_with(
    cfg: SpikeConfig, run_dir: Path, backend: str, target_fpr: float
) -> Calibration:
    embedder = _embedder(cfg, backend)
    master = _master_set(run_dir, embedder)
    control_stills = _stills_in(run_dir / "control", "control")
    control = embed_images(embedder, control_stills, label="control")

    _require_usable_embeddings(master, "master", backend)
    _require_usable_embeddings(control, "control", backend)

    positives, negatives = _calibration_distributions(master, control)
    return calibrate(positives, negatives, embedder.info, target_fpr=target_fpr)


def cmd_check_embedder(args: argparse.Namespace) -> int:
    """Does the chosen scorer actually load and produce sensible numbers here?

    The question worth answering before spending anything. Deliberately not a
    calibration: it reports that plainly, because a plumbing check mistaken for
    evidence would be worse than no check.
    """
    cfg = load_config(args.config)
    backend = args.embedder or cfg.embedder.backend
    if backend is None:
        raise SpikeError(
            "No embedder configured and none given. Pass --embedder, or set "
            "embedder.backend in config/spike.yaml."
        )

    emb_cfg = _embedder_config(cfg, backend)
    if args.detector:
        emb_cfg = dataclasses.replace(
            emb_cfg, options={**emb_cfg.options, "detector": args.detector}
        )

    print(f"\nchecking: {backend}")
    print(f"  model      {emb_cfg.model}")
    print(f"  dimension  {emb_cfg.dim}")
    print(
        f"  licence    {emb_cfg.licence or '(not recorded)'}"
        + (f", read {emb_cfg.licence_verified_on}" if emb_cfg.licence_verified_on else "")
    )
    if args.detector:
        print(f"  detector   {args.detector} (overridden)")

    embedder = load_embedder(emb_cfg)
    workdir = Path(args.workdir) if args.workdir else cfg.run_root / "_selfcheck"
    result = run_check(
        embedder,
        workdir=workdir,
        expected_dim=emb_cfg.dim,
        sample_images=sample_images_from(Path(args.images) if args.images else None),
        fps=cfg.embedder.frame_sample_fps,
        clip_s=float(cfg.generation.get("clip_duration_s", 5)),
        clips=int(cfg.generation.get("identity_matrix_cells", 24)),
    )
    print(format_result(result, backend))
    return 0 if result.ok else 1


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
            print(f"  {'':<18} FAILED — see below")
            continue
        fetched[model.key] = path
        print(f"  {'':<18} -> {path}  ({path.stat().st_size:,} bytes)")
        print(f"  {'':<18}    sha256 {sha256_of(path)}")

    if failures:
        # stdout, not stderr. A download that quietly failed left a config
        # field null and the command still exited 0, so the next step reported
        # "not set" with no trace of why — twice.
        print("\nSome files did not download:")
        for failure in failures:
            print(f"\n  {failure}")

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
    if args.write_config:
        written = write_paths(Path(args.config), fetched)
        if written:
            print(f"Wrote into {args.config}:\n")
            for line in written:
                print(f"  {line}")
            print(
                "\nLicence fields were NOT touched. A path says where a file landed; a "
                "\nlicence says the terms are acceptable, and that one is yours to set."
            )
        else:
            print(f"Nothing to write — those paths are already set in {args.config}.")
    else:
        print("Then paste into config/spike.yaml, filling in the two blank fields:\n")
        print(config_snippet(fetched))
    print("\nThen: python -m scripts.spike.cli bake-off --backends dinov2")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Per-image view of a calibration, for checking a headline against your eye.

    A distribution cannot tell you whether a clean separation is real or an
    artefact of how the sets were built. For that you need the closest call in
    each direction, and to go and look at those two images.
    """
    cfg = load_config(args.config)
    run_dir = _run_dir(cfg, args.run)
    embedder = _embedder(cfg, args.embedder)

    ins = inspect_sets(
        embedder,
        _stills_in(run_dir / "master", "master"),
        _stills_in(run_dir / "control", "control"),
        _read_sources(run_dir),
    )
    print(format_inspection(ins, show=args.show))

    RunLog(run_dir).write_artifact(
        f"inspection_{embedder.info.backend}.json",
        {
            "embedder_key": ins.embedder_key,
            "margin": ins.margin,
            "master": [
                {"name": s.name, "similarity": s.similarity, "status": s.status} for s in ins.master
            ],
            "control": [
                {"name": s.name, "similarity": s.similarity, "status": s.status}
                for s in ins.control
            ],
        },
    )
    margin = ins.margin
    return 0 if margin is not None and margin > 0 else 1


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
        except Exception as exc:
            # Every exception, not just SpikeError. A dlib RuntimeError from
            # incompatible weights took the whole bake-off down and destroyed
            # the other candidates' results with it -- one broken entrant must
            # not cost you the comparison.
            #
            # Reported in the table below rather than on stderr: a candidate
            # that could not run is a RESULT of the bake-off, and on a CI
            # runner stderr is buried under pages of library warnings.
            results[backend] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        results[backend] = cal.to_json()
        log.write_artifact(f"calibration_{backend}.json", cal.to_json())

    usable = {k: v for k, v in results.items() if "error" not in v}
    print(
        f"\n{'backend':<14} {'verdict':<11} {'overlap':>8} {'auc':>8} "
        f"{'thr':>8} {'tpr':>7} {'dim':>5}"
    )
    print("-" * 67)
    for name, cal in usable.items():
        mark = "   (STUB - not a candidate)" if cal["embedder_is_stub"] else ""
        print(
            f"{name:<14} {cal['verdict']:<11} {cal['overlap']:>8.3f} {cal['auc']:>8.4f} "
            f"{cal['threshold']:>8.4f} {cal['tpr_at_threshold']:>7.3f} "
            f"{cal['embedder_key'].rsplit('d', 1)[-1]:>5}{mark}"
        )

    failed = {k: v for k, v in results.items() if "error" in v}
    for name in failed:
        print(f"{name:<14} {'DID NOT RUN'}")

    if failed:
        print("\nWhy they did not run:\n")
        for name, row in failed.items():
            print(f"  {name}:\n    {' '.join(str(row['error']).split())}\n")

    if not usable:
        print("No candidate ran. Fill in the model paths in config/spike.yaml first.")
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
        # --backend is an accepted alias. bake-off takes --backends, everything
        # else took --embedder, and the mismatch is a foot-gun: a CI step that
        # named the wrong one failed with "unrecognized arguments" rather than
        # doing the obvious thing. One concept, either spelling.
        sp.add_argument(
            "--embedder",
            "--backend",
            dest="embedder",
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

    sp = sub.add_parser("prepare-set", help="S0.1 validate stills and add them to a run")
    add_run(sp)
    add_embedder(sp)
    sp.add_argument("source", help="folder of images you generated")
    sp.add_argument(
        "--which",
        choices=["master", "control"],
        required=True,
        help="master = the persona. control = other, different people.",
    )
    sp.add_argument("--dry-run", action="store_true", help="report only, copy nothing")
    sp.set_defaults(func=cmd_prepare_set)

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
    sp.add_argument(
        "--keyframes",
        help="a directory of existing stills to animate, instead of generating "
        "keyframes. The S0.5 shape: the generator would be the S0.4 LoRA, which "
        "does not exist yet, and these are the images the question is about.",
    )
    sp.set_defaults(func=cmd_run_matrix)

    sp = sub.add_parser("battery", help="S0.7 golf format battery + rating sheet")
    sp.add_argument(
        "--last-keyframes",
        help="a directory of stills pinning the LAST frame, paired with --keyframes "
        "by index. Supplying it asks for first/last-frame conditioning, which needs "
        "a video slot whose model accepts it (ADR 0007).",
    )
    sp.add_argument(
        "--shots",
        nargs="+",
        help="run only these shot ids from the prompt set. Use it to resume a "
        "part-finished set: every shot named is generated and billed again.",
    )
    sp.add_argument(
        "--prompt-set",
        choices=sorted(PROMPT_SETS),
        default="golf",
        help="'golf' measures the provider (S0.7); 'coverage' measures our own "
        "face-presence rule by generating shots where the face leaves frame.",
    )
    add_run(sp)
    add_embedder(sp)
    add_budget(sp)
    sp.add_argument("--takes", type=int)
    sp.add_argument("--subject", default="the persona")
    sp.add_argument("--image-slot", default="primary")
    sp.add_argument("--video-slots", nargs="+", default=["flagship", "budget"])
    sp.add_argument(
        "--keyframes",
        help="a directory of existing stills to animate, instead of generating "
        "keyframes from the image provider (which is the S0.4 LoRA, not yet built).",
    )
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

    sp = sub.add_parser(
        "check-embedder", help="does the chosen scorer load and work on this machine?"
    )
    add_embedder(sp)
    sp.add_argument(
        "--detector",
        choices=sorted(DETECTORS),
        help="override the detector. 'whole-image' skips detection, which tests the "
        "model on its own.",
    )
    sp.add_argument("--images", help="a directory of real photographs, to exercise detection")
    sp.add_argument("--workdir", help="where to write probe images")
    sp.set_defaults(func=cmd_check_embedder)

    sp = sub.add_parser("fetch-models", help="download the ADR 0002 candidate weights")
    sp.add_argument("--dest", default="models", help="where to put them (default: models/)")
    # Derived, not listed. A hardcoded pair here silently refused
    # `--backend dlib-densenet` after that backend was added everywhere else.
    sp.add_argument(
        "--backend",
        choices=sorted({m.backend for m in MODELS}),
        help="just one candidate",
    )
    sp.add_argument("--force", action="store_true", help="re-download existing files")
    sp.add_argument(
        "--write-config",
        action="store_true",
        help="fill the downloaded paths into config. Licence fields are left alone.",
    )
    sp.add_argument(
        "--include",
        nargs="+",
        default=[],
        metavar="KEY",
        help="also fetch an alternative file, e.g. dlib-densenet",
    )
    sp.set_defaults(func=cmd_fetch_models)

    sp = sub.add_parser(
        "inspect", help="per-image similarities, to check a calibration against your eye"
    )
    add_run(sp)
    add_embedder(sp)
    sp.add_argument("--show", type=int, default=8, help="rows per set (default 8)")
    sp.set_defaults(func=cmd_inspect)

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
