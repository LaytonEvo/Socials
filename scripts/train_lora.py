"""Run the task 1.4 LoRA training pipeline against the real trainer.

Structured so that everything free happens before anything paid, and the paid part is
refused unless a budget is passed. `--dry-run` stops after the estimate, which is the
recommended way to look at a run before authorising it.

**ADR 0010 governs the result.** fal extends Black Forest Labs' commercial licence to
work trained AND run on their platform. The artefact this produces may not be run
anywhere else, so `inference_host` is recorded on it and checked rather than remembered.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.identity.dataset import NO_FACE_STILLS, TrainingSet, build_archive, collect, split
from app.identity.training import (
    FakeLoraTrainer,
    FalLoraTrainer,
    LoraArtefact,
    TrainingRequest,
)
from app.providers.types import ProviderJob

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ROOT = ROOT / "spike" / "data"


def build_dataset(trigger_word: str, holdout_fraction: float) -> TrainingSet:
    roots = {k: REFERENCE_ROOT / k for k in ("master_v2", "outfit", "lighting", "body")}
    missing = [str(p) for p in roots.values() if not p.is_dir()]
    if missing:
        raise SystemExit(f"reference directories missing: {missing}")
    stills = collect(roots, exclude=NO_FACE_STILLS)
    return split(stills, trigger_word=trigger_word, holdout_fraction=holdout_fraction)


def archive_as_data_uri(archive: bytes) -> str:
    """The training set as a data URI rather than an upload.

    fal's CDN is public (ADR 0006): anything uploaded there can be downloaded by anyone
    with the URL. Her reference set is not going on a public host for the sake of
    convenience, and the private alternative — a presigned URL from our own bucket —
    needs S3 credentials that are not configured yet.
    """
    return "data:application/zip;base64," + base64.b64encode(archive).decode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--trigger-word", default="mollie")
    parser.add_argument("--holdout-fraction", type=float, default=0.15)
    parser.add_argument("--budget", type=Decimal, default=None, help="USD ceiling for this run")
    parser.add_argument("--dry-run", action="store_true", help="stop after the estimate")
    parser.add_argument("--fake", action="store_true", help="use the offline trainer")
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "lora")
    args = parser.parse_args()

    config = load_all(ROOT / "config")

    # ---------------------------------------------------------------- free --
    dataset = build_dataset(args.trigger_word, args.holdout_fraction)
    print(
        f"dataset       {dataset.total} stills -> {len(dataset.train)} train, "
        f"{len(dataset.holdout)} holdout"
    )
    print(f"  train       {dataset.by_kind(dataset.train)}")
    print(f"  holdout     {dataset.by_kind(dataset.holdout)}")
    dataset_hash = dataset.dataset_hash()
    print(f"  hash        {dataset_hash}")

    archive = build_archive(dataset.train, trigger_word=args.trigger_word)
    uri = archive_as_data_uri(archive)
    print(
        f"archive       {len(archive) / 1048576:.2f} MB  ->  "
        f"{len(uri) / 1048576:.2f} MB as data URI"
    )

    # ------------------------------------------------------------- pricing --
    # `lora` is a settings block rather than a priced provider group, so the estimate
    # comes from the trainer, which reads price_usd_per_step from config. The guard is
    # still the thing that says yes: it owns the per-run budget and the ceilings.
    lora = config.providers.lora
    trainer = FakeLoraTrainer(settings=lora) if args.fake else FalLoraTrainer(settings=lora)
    request = TrainingRequest(
        archive_url=uri,
        trigger_word=args.trigger_word,
        steps=args.steps,
        dataset_hash=dataset_hash,
    )
    estimate = trainer.estimate_cost(request)
    print(f"\ntrainer       {lora.trainer}")
    print(f"base model    {lora.base_model}  ({lora.base_model_licence})")
    print(f"price         ${lora.price_usd_per_step} per step  x {args.steps} steps")
    print(f"ESTIMATE      ${estimate}")

    if args.dry_run:
        print("\n--dry-run: stopping before anything is billed.")
        return 0

    guard = BudgetGuard(config.budget, config.providers)
    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")
    print(f"budget        ${run_budget}  (headroom ${run_budget - estimate})")

    async def run() -> tuple[ProviderJob, LoraArtefact]:
        job = await trainer.train(request)
        print(f"\nsubmitted     {job.provider_job_id or '(no id)'}  status={job.status.name}")
        artefact = await trainer.collect(job)
        return job, artefact

    job, artefact = asyncio.run(run())
    print(f"status        {job.status.name}")
    print(f"charged       ${trainer.cost_of(job)}")
    print(f"weights       {artefact.weights_url}")
    print(f"base model    {artefact.base_model}  ({artefact.licence})")
    print(f"runs only on  {artefact.inference_host}")

    args.out.mkdir(parents=True, exist_ok=True)
    record = {
        "trained_on": dt.date.today().isoformat(),
        "steps": artefact.steps,
        "dataset_hash": artefact.dataset_hash,
        "train_count": len(dataset.train),
        "holdout_count": len(dataset.holdout),
        "trigger_word": args.trigger_word,
        "weights_url": artefact.weights_url,
        "config_url": artefact.config_url,
        "base_model": artefact.base_model,
        "trainer": artefact.trainer,
        "licence": artefact.licence,
        "inference_host": artefact.inference_host,
        "cost_usd": str(trainer.cost_of(job)),
        "holdout": [s.path.as_posix() for s in dataset.holdout],
    }
    out = args.out / "artefact.json"
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(f"\nrecorded      {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
