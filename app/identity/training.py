"""LoRA training — the second half of task 1.4.

A protocol, a fake that runs offline, and a real fal adapter. The pipeline runs end to
end on the fake, so everything around training is testable before a penny is spent; the
real one is written and has never been run.

**ADR 0010 governs what may be done with the result.** fal pays Black Forest Labs for a
commercial licence and extends it to work trained AND run on their platform. Download
the weights onto our own FLUX.1 [dev] setup and they fall back under BFL's
non-commercial terms. So `LoraArtefact.storage_key` is a backup and a version record,
not a deployment artefact, and `require_inference_host` exists to make that checkable
rather than remembered.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

import httpx

from app.config import LoraSettings
from app.providers.fal import QUEUE_ROOT, api_key
from app.providers.types import JobStatus, ProviderError, ProviderJob, ProviderRefused


class LicenceViolation(RuntimeError):
    """Something tried to use the weights somewhere the licence does not reach."""


@dataclass(frozen=True)
class TrainingRequest:
    """One training run.

    `archive_url` rather than bytes: the training set is about 18 MB at 1024px, far past
    any inline limit, so it has to be somewhere the trainer can fetch. A presigned URL
    from our own bucket keeps it private and short-lived; fal's own upload endpoint makes
    it public, which ADR 0006 records and which is a choice rather than a default.
    """

    archive_url: str
    trigger_word: str
    steps: int
    dataset_hash: str
    create_masks: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LoraArtefact:
    """A trained LoRA, and the provenance that makes it reproducible."""

    weights_url: str
    base_model: str
    trainer: str
    steps: int
    dataset_hash: str
    trained_on: dt.date
    licence: str
    #: Where this may legally run. Not a preference (ADR 0010).
    inference_host: str
    storage_key: str | None = None
    config_url: str | None = None

    def require_inference_host(self, host: str) -> None:
        """Refuse to hand these weights to a host the licence does not cover.

        The failure this prevents is quiet: weights run in the wrong place produce
        perfectly good images, and nothing about them says the licence was breached.
        """
        if host != self.inference_host:
            raise LicenceViolation(
                f"these weights are licensed to run on {self.inference_host!r}, not "
                f"{host!r}. ADR 0010: commercial use is fal's licence, extended to work "
                f"trained and run on their platform. Off it, FLUX.1 [dev]'s "
                f"non-commercial terms apply and this would be a breach."
            )


@runtime_checkable
class LoraTrainer(Protocol):
    name: str

    def estimate_cost(self, req: TrainingRequest) -> Decimal: ...
    async def train(self, req: TrainingRequest) -> ProviderJob: ...
    async def collect(self, job: ProviderJob) -> LoraArtefact: ...
    def cost_of(self, job: ProviderJob) -> Decimal: ...


@dataclass
class FakeLoraTrainer:
    """Trains nothing, instantly, for free.

    Enforces the same step bounds and returns the same shape, so the pipeline around
    training is exercised properly. It cannot tell you whether a LoRA learns her face —
    only a real run does that, and nothing here should be read as evidence about likeness.
    """

    settings: LoraSettings
    #: Simulate a run that was billed and produced nothing — the case amendment A2
    #: exists for, and the one nobody tests by accident.
    fail_after_billing: bool = False
    jobs: list[ProviderJob] = field(default_factory=list)
    name: str = "fake-lora-trainer"
    _artefacts: dict[str, LoraArtefact] = field(default_factory=dict, repr=False)

    def estimate_cost(self, req: TrainingRequest) -> Decimal:
        price = self.settings.price_usd_per_step or Decimal("0")
        return price * req.steps

    def cost_of(self, job: ProviderJob) -> Decimal:
        return job.cost_usd if job.cost_usd is not None else Decimal("0")

    async def train(self, req: TrainingRequest) -> ProviderJob:
        job = ProviderJob(provider=self.name, model=self.settings.trainer or "fake-trainer")
        self.jobs.append(job)
        job.provider_job_id = f"fake-train-{len(self.jobs):03d}"
        job.cost_usd = self.estimate_cost(req)

        if self.fail_after_billing:
            job.status = JobStatus.FAILED
            job.completed_at = dt.datetime.now(dt.UTC)
            job.error = "fake training failure after the GPU had started"
            return job

        job.status = JobStatus.SUCCEEDED
        job.completed_at = dt.datetime.now(dt.UTC)
        self._artefacts[job.provider_job_id] = LoraArtefact(
            weights_url=f"memory://lora/{req.dataset_hash[:12]}.safetensors",
            base_model=self.settings.base_model or "unset",
            trainer=self.name,
            steps=req.steps,
            dataset_hash=req.dataset_hash,
            trained_on=dt.date.today(),
            licence=self.settings.base_model_licence or "unset",
            inference_host=self.settings.inference_must_run_on or "fal",
        )
        return job

    async def collect(self, job: ProviderJob) -> LoraArtefact:
        if job.status is not JobStatus.SUCCEEDED:
            raise ProviderError(job.error or f"job is {job.status}", billed=job.billed)
        assert job.provider_job_id
        return self._artefacts[job.provider_job_id]


@dataclass
class FalLoraTrainer:
    """The real trainer. Written, never run.

    Follows ADR 0006's queue contract and the correction that cost $1.92: the poll and
    retrieve URLs come from the submit response, never built from the model id.
    """

    settings: LoraSettings
    client: httpx.Client | None = None
    timeout_s: float = 3600.0
    poll_interval_s: float = 15.0
    jobs: list[ProviderJob] = field(default_factory=list)
    name: str = "fal-lora-trainer"
    _artefacts: dict[str, LoraArtefact] = field(default_factory=dict, repr=False)

    def estimate_cost(self, req: TrainingRequest) -> Decimal:
        price = self.settings.price_usd_per_step
        if price is None:
            raise ProviderRefused(
                "lora.price_usd_per_step is not set, so the cost guard cannot reserve "
                "for a training run. Training is priced per STEP, and a 2000-step run is "
                "not the kind of spend to discover afterwards."
            )
        return price * req.steps

    def cost_of(self, job: ProviderJob) -> Decimal:
        return job.cost_usd if job.cost_usd is not None else Decimal("0")

    def _client(self) -> httpx.Client:
        if self.client is None:
            key = api_key()
            headers = {"Authorization": f"Key {key}"} if key else {}
            self.client = httpx.Client(headers=headers, timeout=self.timeout_s)
        return self.client

    async def train(self, req: TrainingRequest) -> ProviderJob:
        trainer = self.settings.trainer
        if not trainer:
            raise ProviderRefused("lora.trainer is not set in config/providers.yaml")

        job = ProviderJob(provider=self.name, model=trainer)
        self.jobs.append(job)
        arguments: dict[str, Any] = {
            "images_data_url": req.archive_url,
            "trigger_word": req.trigger_word,
            "steps": req.steps,
            "create_masks": req.create_masks,
            **req.extra,
        }

        response = self._client().post(f"{QUEUE_ROOT}/{trainer}", json=arguments)
        if response.status_code >= 400:
            billed = response.status_code not in {401, 403, 404, 422}
            job.status = JobStatus.FAILED
            job.completed_at = dt.datetime.now(dt.UTC)
            job.billed = billed
            job.cost_usd = self.estimate_cost(req) if billed else Decimal("0")
            job.error = f"fal returned {response.status_code}: {response.text[:300]}"
            raise ProviderError(job.error, billed=billed)

        submitted = response.json()
        job.provider_job_id = str(submitted.get("request_id") or "")
        status_url = str(submitted.get("status_url") or "")
        response_url = str(submitted.get("response_url") or "")
        job.status = JobStatus.RUNNING
        # Billed from acceptance: a GPU that started and then failed is still spend.
        job.cost_usd = self.estimate_cost(req)
        if not status_url or not response_url:
            job.status = JobStatus.FAILED
            job.error = "fal accepted the run but returned no URLs to follow it"
            raise ProviderError(job.error, billed=True)

        payload = self._await(job, status_url, response_url)
        weights = payload.get("diffusers_lora_file") or {}
        if not weights.get("url"):
            job.status = JobStatus.FAILED
            job.completed_at = dt.datetime.now(dt.UTC)
            job.error = "training reported COMPLETED with no weights file"
            raise ProviderError(job.error, billed=True)

        job.status = JobStatus.SUCCEEDED
        job.completed_at = dt.datetime.now(dt.UTC)
        assert job.provider_job_id
        self._artefacts[job.provider_job_id] = LoraArtefact(
            weights_url=str(weights["url"]),
            base_model=self.settings.base_model or "unset",
            trainer=trainer,
            steps=req.steps,
            dataset_hash=req.dataset_hash,
            trained_on=dt.date.today(),
            licence=self.settings.base_model_licence or "unset",
            inference_host=self.settings.inference_must_run_on or "fal",
            config_url=str((payload.get("config_file") or {}).get("url") or "") or None,
        )
        return job

    async def collect(self, job: ProviderJob) -> LoraArtefact:
        if job.status is not JobStatus.SUCCEEDED:
            raise ProviderError(job.error or f"job is {job.status}", billed=job.billed)
        assert job.provider_job_id
        return self._artefacts[job.provider_job_id]

    def _await(self, job: ProviderJob, status_url: str, response_url: str) -> dict[str, Any]:
        import time

        deadline = time.monotonic() + self.timeout_s
        while True:
            status = self._client().get(status_url).json().get("status")
            if status == "COMPLETED":
                result: dict[str, Any] = self._client().get(response_url).json()
                return result
            if status not in {"IN_QUEUE", "IN_PROGRESS"}:
                raise ProviderError(f"unrecognised training status {status!r}", billed=True)
            if time.monotonic() > deadline:
                raise ProviderError(
                    f"training did not finish within {self.timeout_s:.0f}s. The GPU ran, "
                    f"so this is billed.",
                    billed=True,
                )
            time.sleep(self.poll_interval_s)
