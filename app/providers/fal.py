"""The fal.ai image adapter. Real, and the first one.

Built on the contract recorded in `docs/decisions/0006-fal-api-contract.md`, which was
read from fal's own documentation rather than guessed. No vendor SDK: ADR 0006
established that the queue contract is three plain HTTP calls and that the endpoint is
derived from the model id, so an HTTP client is enough and one fewer dependency is one
fewer thing to pin.

Three things ADR 0006 warns about, each of which a naive implementation gets wrong.

**`COMPLETED` does not mean the request worked.** fal returns a clean status for a
request whose arguments were never validated, and the status does not say so. Checking
the status is necessary and not sufficient — the output has to be inspected, so a
completed response with no image is treated as a failure here.

**A refusal costs nothing, and the difference matters.** A 401 or 403 is billed for
nothing; a failure after generation started is billed. The adapter reports which,
because amendment A2 puts that cost in the ledger either way and a guess in the wrong
direction either loses money or invents it.

**fal's CDN is public.** "Anyone with the URL can download." So her reference stills are
sent as data URIs rather than uploaded: nothing of hers lands on a public host, and
every still in the master set fits — the largest is 2.87 MB base64 against a 4 MB cap.
"""

from __future__ import annotations

import base64
import datetime as dt
import mimetypes
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from .types import (
    AssetResult,
    Capabilities,
    ImageRequest,
    JobStatus,
    ProviderError,
    ProviderJob,
    ProviderRefused,
    SeedSupport,
)

QUEUE_ROOT = "https://queue.fal.run"
KEY_VAR = "FAL_KEY"

#: fal's queue states. Anything else is unknown and treated as still running rather
#: than guessed at.
IN_QUEUE = "IN_QUEUE"
IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"

#: Statuses that mean nothing was billed. ADR 0006 and the spike agree: a 403 is free
#: on every operation, not only on submit.
FREE_STATUS_CODES = frozenset({401, 403, 404, 422})


class FalNotConfigured(RuntimeError):
    """No route to an authenticated fal request."""


def api_key() -> str | None:
    """The key from the environment, or None when something else authenticates.

    Two ways this runs, and the second is why this returns None rather than raising.

    **From a deployment**, `FAL_KEY` is in the environment and the adapter sends it.

    **From a Claude Code cloud session**, the credential is configured as an
    environment *API credential* rather than a variable: an egress proxy holds it,
    scoped to `*.fal.run`, `*.fal.ai` and `*.fal.media`, and injects it into outbound
    requests. The session never sees the value — that is the point of the feature.
    Verified here on 2026-09-29: an unauthenticated POST and one carrying a
    deliberately wrong key returned the same 404 for a nonexistent model rather than a
    401, which only happens if the header is being replaced.

    So an absent key is not an error. Sending no Authorization header lets the proxy
    supply one; if nothing does, fal answers 401 and the adapter reports it as a free
    refusal, which is accurate.
    """
    return os.environ.get(KEY_VAR, "").strip() or None


def data_uri(path: Path) -> str:
    """A still as a data URI, so it never reaches a public CDN.

    fal's uploads are public by default (ADR 0006). For a persona's reference set that
    is not an acceptable default, and the cap makes it unnecessary: every master still
    fits.
    """
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


@dataclass
class FalImageProvider:
    """One fal image model. Everything model-specific comes from config."""

    model: str
    price_usd_per_image: Decimal
    price_verified_on: dt.date | None
    storage: Any
    #: How this model shapes its request: which field takes the source image, whether
    #: it is a list, and the base arguments. A property of the model, so it lives in
    #: config beside the model id and never here.
    request_shape: dict[str, Any] = field(default_factory=dict)
    client: httpx.Client | None = None
    timeout_s: float = 180.0
    poll_interval_s: float = 2.0
    jobs: list[ProviderJob] = field(default_factory=list)

    name: str = field(default="fal", init=False)
    _results: dict[str, AssetResult] = field(default_factory=dict, repr=False)

    def capabilities(self) -> Capabilities:
        return Capabilities(seed=SeedSupport.ACCEPTED_NOT_HONOURED)

    def estimate_cost(self, req: ImageRequest) -> Decimal:
        count = int(self.request_shape.get("base", {}).get("num_images", 1))
        return self.price_usd_per_image * count

    def cost_of(self, job: ProviderJob) -> Decimal:
        return job.cost_usd if job.cost_usd is not None else Decimal("0")

    # ----------------------------------------------------------------- calls --
    def _client(self) -> httpx.Client:
        if self.client is None:
            key = api_key()
            # No header when there is no key: an egress proxy may be holding the
            # credential and injecting it. Sending `Key None` would be worse than
            # sending nothing.
            headers = {"Authorization": f"Key {key}"} if key else {}
            self.client = httpx.Client(headers=headers, timeout=self.timeout_s)
        return self.client

    def _arguments(self, req: ImageRequest, source: Path | None) -> dict[str, Any]:
        arguments: dict[str, Any] = {"prompt": req.prompt}
        arguments.update(self.request_shape.get("base", {}))
        if req.seed is not None:
            arguments["seed"] = req.seed

        if source is not None:
            field_name = self.request_shape.get("image_field")
            if not field_name:
                raise ProviderRefused(
                    f"{self.model} was given a source image but config declares no "
                    f"`image_field` for it. The field name is a property of the model, so "
                    f"it belongs in config/providers.yaml — sending the wrong one is a 422."
                )
            uri = data_uri(source)
            arguments[field_name] = [uri] if self.request_shape.get("image_field_is_list") else uri
        return arguments

    async def generate(
        self, req: ImageRequest, *, key: str, source: Path | None = None
    ) -> ProviderJob:
        """Submit, wait, and store the result. Returns the job either way.

        Synchronous HTTP inside an async signature on purpose: the protocol is async
        because real providers are slow, and httpx's sync client is enough while this
        runs one request at a time from a worker. Swapping to AsyncClient is a change
        inside this method and nothing above it.
        """
        job = ProviderJob(provider=self.name, model=self.model)
        self.jobs.append(job)

        try:
            submitted = self._post(f"{QUEUE_ROOT}/{self.model}", self._arguments(req, source))
        except ProviderError as exc:
            job.status = JobStatus.FAILED
            job.completed_at = dt.datetime.now(dt.UTC)
            job.billed = exc.billed
            job.cost_usd = self.estimate_cost(req) if exc.billed else Decimal("0")
            job.error = str(exc)
            raise

        job.provider_job_id = str(submitted.get("request_id") or "")
        job.status = JobStatus.RUNNING
        # Billed from here: the request is accepted and generation has started, so a
        # later failure still costs. Reserved at the estimate rather than left null.
        job.cost_usd = self.estimate_cost(req)

        try:
            payload = self._await_result(job)
            images = payload.get("images") or []
            if not images:
                # ADR 0006: a COMPLETED status can mean the arguments were never
                # validated, and the status does not say so. An empty output is the
                # symptom, and it is a failure rather than an empty success.
                raise ProviderError(
                    f"{self.model} reported COMPLETED with no image. ADR 0006: a clean "
                    f"status is not sufficient to conclude a request worked.",
                    billed=True,
                )
            url = str(images[0]["url"])
            content = self._download(url)
            content_type = str(images[0].get("content_type") or "image/png")
            self.storage.put(key, content, content_type=content_type)
            result = AssetResult(key, content_type, len(content))
        except ProviderError as exc:
            job.status = JobStatus.FAILED
            job.completed_at = dt.datetime.now(dt.UTC)
            job.billed = exc.billed
            if not exc.billed:
                job.cost_usd = Decimal("0")
            job.error = str(exc)
            raise

        job.status = JobStatus.SUCCEEDED
        job.completed_at = dt.datetime.now(dt.UTC)
        assert job.provider_job_id
        self._results[job.provider_job_id] = result
        return job

    async def poll(self, job: ProviderJob) -> AssetResult:
        if job.status is not JobStatus.SUCCEEDED:
            raise ProviderError(job.error or f"job is {job.status}", billed=job.billed)
        assert job.provider_job_id
        return self._results[job.provider_job_id]

    # ----------------------------------------------------------------- HTTP --
    def _post(self, url: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self._client().post(url, json=arguments)
        self._raise_for_status(response)
        body: dict[str, Any] = response.json()
        return body

    def _get(self, url: str) -> dict[str, Any]:
        response = self._client().get(url)
        self._raise_for_status(response)
        body: dict[str, Any] = response.json()
        return body

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        detail = response.text[:400]
        if response.status_code in FREE_STATUS_CODES:
            raise ProviderRefused(
                f"fal refused with {response.status_code} before doing any work, so "
                f"nothing was billed: {detail}"
            )
        raise ProviderError(f"fal returned {response.status_code}: {detail}", billed=True)

    def _await_result(self, job: ProviderJob) -> dict[str, Any]:
        """Poll the queue until the request completes, then retrieve it."""
        import time

        base = f"{QUEUE_ROOT}/{self.model}/requests/{job.provider_job_id}"
        deadline = time.monotonic() + self.timeout_s
        while True:
            status = self._get(f"{base}/status").get("status")
            if status == COMPLETED:
                return self._get(base)
            if status not in {IN_QUEUE, IN_PROGRESS}:
                # An unknown status is not assumed benign. Generation may well have
                # happened, so this is reported as billed.
                raise ProviderError(
                    f"{self.model} returned an unrecognised status {status!r}", billed=True
                )
            if time.monotonic() > deadline:
                raise ProviderError(
                    f"{self.model} did not finish within {self.timeout_s:.0f}s. Generation "
                    f"had started, so this is billed — amendment A2's case exactly.",
                    billed=True,
                )
            time.sleep(self.poll_interval_s)

    def _download(self, url: str) -> bytes:
        response = self._client().get(url)
        self._raise_for_status(response)
        return response.content
