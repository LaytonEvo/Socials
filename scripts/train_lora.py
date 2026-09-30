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
from app.storage.s3 import S3Storage, bucket_from_env

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

    Only usable for a small archive. fal fetches this URL itself and rejects a long one
    AFTER queueing and running the job, so an oversized one arrives as a billed
    COMPLETED with no weights — see MAX_DATA_URI_BYTES. A real training set goes to the
    bucket instead.
    """
    return "data:application/zip;base64," + base64.b64encode(archive).decode()


def archive_to_bucket(archive: bytes, dataset_hash: str, *, expires_in: int) -> str:
    """Upload the training set privately and hand fal a short, expiring URL.

    Private rather than fal's own upload endpoint, whose CDN is public (ADR 0006):
    anyone with the URL could download the persona's entire reference set. The key is
    the dataset hash, so the same split uploads to the same place and a re-run does not
    litter the bucket with copies.
    """
    storage = S3Storage(bucket=bucket_from_env())
    key = f"training-sets/{dataset_hash}.zip"
    storage.put(key, archive, content_type="application/zip", overwrite=True)
    return storage.presign_get(key, expires_in=expires_in)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--trigger-word", default="mollie")
    parser.add_argument("--holdout-fraction", type=float, default=0.15)
    parser.add_argument("--budget", type=Decimal, default=None, help="USD ceiling for this run")
    parser.add_argument("--dry-run", action="store_true", help="stop after the estimate")
    parser.add_argument("--fake", action="store_true", help="use the offline trainer")
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "lora")
    parser.add_argument(
        "--data-uri",
        action="store_true",
        help="inline the archive instead of uploading it; only viable for a tiny set",
    )
    parser.add_argument(
        "--presign-seconds",
        type=int,
        default=3600,
        help="lifetime of the URL handed to fal; long enough to queue and fetch",
    )
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
    print(f"archive       {len(archive) / 1048576:.2f} MB")

    # ------------------------------------------------------------- pricing --
    # `lora` is a settings block rather than a priced provider group, so the estimate
    # comes from the trainer, which reads price_usd_per_step from config. The guard is
    # still the thing that says yes: it owns the per-run budget and the ceilings.
    lora = config.providers.lora
    trainer = FakeLoraTrainer(settings=lora) if args.fake else FalLoraTrainer(settings=lora)
    estimate = (lora.price_usd_per_step or Decimal("0")) * args.steps
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

    # Uploading is a side effect, so it happens only once the run is authorised.
    if args.data_uri:
        archive_url = archive_as_data_uri(archive)
        print(f"archive url   data URI, {len(archive_url) / 1048576:.2f} MB")
    else:
        archive_url = archive_to_bucket(archive, dataset_hash, expires_in=args.presign_seconds)
        print(f"archive url   presigned, expires in {args.presign_seconds}s")

    request = TrainingRequest(
        archive_url=archive_url,
        trigger_word=args.trigger_word,
        steps=args.steps,
        dataset_hash=dataset_hash,
    )

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
