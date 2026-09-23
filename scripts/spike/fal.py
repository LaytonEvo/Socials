"""fal.ai queue adapter.

Implements exactly the contract recorded in `docs/decisions/0006-fal-api-contract.md`,
which was read from fal's own documentation on 2026-09-23. Nothing here is
inferred from how other providers behave; where a behaviour was not verified,
this module does not depend on it.

Four verified details shape the code, and each is a bug if assumed away:

* **COMPLETED is not success.** A completed request can carry ``error`` and
  ``error_type``. Treating the terminal state as success would record a failed
  generation as a good take while still charging the ledger for it.
* **The result is a URL, not bytes.** Fetching a clip is two calls, and the
  second can fail after the money is gone.
* **fal retries internally, up to 10 times.** This adapter therefore does not
  retry submissions itself; stacking retries would multiply latency and
  possibly spend.
* **No price comes back.** The ledger figure is computed from configured price
  and duration, which makes it our estimate rather than fal's bill. See ADR
  0006 for why that is acceptable for the spike and not beyond it.

No vendor SDK: the transport is stdlib, and it is injectable so the whole
adapter is testable without a network or a key.
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .config import ProviderConfig
from .embedders import ASPECT_9_16, crop_to_aspect
from .errors import ProviderFailed, ProviderNotConfigured, ProviderRefused, ProviderTimeout
from .providers import VideoRequest

QUEUE_ROOT = "https://queue.fal.run"
API_KEY_ENV = "FAL_KEY"

#: Terminal state. Says the request stopped, not that it worked.
COMPLETED = "COMPLETED"
IN_QUEUE = "IN_QUEUE"
IN_PROGRESS = "IN_PROGRESS"

#: (url, method, body, headers) -> (status_code, bytes)
Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]]


def urllib_transport(
    url: str, method: str, body: bytes | None, headers: dict[str, str]
) -> tuple[int, bytes]:
    """The real one. Kept tiny so the injected fake in tests is faithful."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@dataclass
class QueuedRequest:
    """A submitted request, and the URLs fal gave us for following it.

    The URLs come from the submit response rather than being rebuilt from the
    model id, because they are not the same shape. Submitting to
    ``fal-ai/veo3.1/image-to-video`` returns status and response URLs under
    ``fal-ai/veo3.1/requests/...`` -- the queue groups by app, not by endpoint.
    Reconstructing them by pattern worked for single-app models and returned an
    empty-bodied 405 for this one, after the job had been queued and paid for.

    So: follow the links the provider hands you. ADR 0006 recorded these fields
    and the first implementation ignored them.
    """

    request_id: str
    status_url: str
    response_url: str
    cancel_url: str | None = None

    @classmethod
    def from_response(cls, res: dict[str, Any], model_id: str) -> QueuedRequest:
        request_id = str(res["request_id"])
        # Fall back to the conventional shape only if fal omits a URL, so a
        # missing field degrades instead of crashing -- but prefer theirs.
        base = f"{QUEUE_ROOT}/{model_id}/requests/{request_id}"
        return cls(
            request_id=request_id,
            status_url=str(res.get("status_url") or f"{base}/status"),
            response_url=str(res.get("response_url") or base),
            cancel_url=str(res["cancel_url"]) if res.get("cancel_url") else None,
        )


@dataclass
class FalClient:
    """The queue protocol, with no opinion about what is being generated.

    ``api_key`` is optional because there are two legitimate ways this gets
    authenticated, and they must not both happen at once:

    * **The adapter sends it.** ``FAL_KEY`` is in the environment and this class
      sets the header. That is the shape for an ordinary deployment.
    * **Something in front injects it.** A proxy adds the header to outbound
      requests and the key never enters the process at all. Better isolation,
      and the case where sending our own header risks a duplicate or a
      conflicting one.

    So: send a header only when we actually hold a key, and make the failure
    legible when neither route turned out to be configured.
    """

    api_key: str | None = None
    transport: Transport = urllib_transport
    poll_interval_s: float = 2.0
    timeout_s: float = 600.0
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            # Verified 2026-09-23: "Key", not "Bearer".
            headers["Authorization"] = f"Key {self.api_key}"
        return headers

    def _json(
        self,
        url: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        *,
        refusal_is_free: bool = False,
    ) -> Any:
        """One request, with the failure classified by who wasted what.

        ``refusal_is_free`` says whether a 4xx on *this* call means no work was
        done. True for submitting: fal rejected the request, nothing ran, so it
        costs nothing. False for polling and fetching results: the submission
        already succeeded by then, so a later 4xx says nothing about whether
        compute was spent, and the safe assumption is that it was.
        """
        payload = json.dumps(body).encode() if body is not None else None
        status, raw = self.transport(url, method, payload, self._headers())

        # Parse leniently and classify on the status. Parsing first meant a 405
        # with an empty body was reported as "not JSON" -- true, useless, and
        # billed as if a runner had done the work.
        try:
            parsed: Any = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = None

        if status >= 400:
            detail = parsed.get("detail") if isinstance(parsed, dict) else None
            if detail is None and isinstance(parsed, dict):
                detail = parsed.get("error") or parsed.get("message")
            said = detail or (raw[:200].decode("utf-8", "replace") or "(empty body)")
            # 422 means the request body itself was rejected, so nothing ran
            # whichever call surfaces it -- and fal surfaces it late: a request
            # with a missing field reaches COMPLETED with error: None, and only
            # the result fetch returns the 422. See ADR 0006.
            if status == 422 or (400 <= status < 500 and refusal_is_free):
                # fal uses 403 for an exhausted balance as well as for bad
                # credentials, and its own words are the only thing that tells
                # them apart. Ours go second, and conditionally: leading with an
                # auth diagnosis once sent the reader to the wrong settings page
                # for a problem that was about money.
                raise ProviderRefused(
                    f"fal refused the request ({status}): {said}\n"
                    f"  If that is about credentials: {API_KEY_ENV} is "
                    f"{'set' if self.api_key else 'NOT set'} in this process, so either "
                    "set it or inject the header in front — not both, since two "
                    "Authorization headers is its own failure.\n"
                    "  If it is about balance, a lock, or the request shape, nothing in "
                    "this process will fix it."
                )
            raise ProviderFailed(f"fal returned {status}: {said}")

        if parsed is None:
            raise ProviderFailed(
                f"fal returned {status} with a body that is not JSON: {raw[:200]!r}"
            )
        return parsed

    def submit(self, model_id: str, arguments: dict[str, Any]) -> QueuedRequest:
        """Queue a request and return a handle to it. Does not wait."""
        # A refusal here is free: nothing was queued, so no runner ran.
        res = self._json(f"{QUEUE_ROOT}/{model_id}", "POST", arguments, refusal_is_free=True)
        if not isinstance(res, dict) or not res.get("request_id"):
            raise ProviderFailed(f"fal accepted the submission but returned no request_id: {res!r}")
        return QueuedRequest.from_response(res, model_id)

    def wait(self, queued: QueuedRequest) -> dict[str, Any]:
        """Poll until the request reaches COMPLETED, then return its status.

        Raises on timeout rather than returning a partial result, and carries
        the request id on the exception: a timed-out request may still have
        been billed, so the run has to be reconcilable afterwards.
        """
        request_id = queued.request_id
        deadline = self.now() + self.timeout_s
        status_url = queued.status_url
        while True:
            status = self._json(status_url)
            state = status.get("status") if isinstance(status, dict) else None
            if state == COMPLETED:
                return dict(status)
            if state not in (IN_QUEUE, IN_PROGRESS):
                raise ProviderFailed(
                    f"fal reported an unrecognised status {state!r} for {request_id}. "
                    "The contract in ADR 0006 has three states; this is not one of them, "
                    "so re-read the docs before assuming what it means."
                )
            if self.now() >= deadline:
                raise ProviderTimeout(
                    f"fal request {request_id} was still {state} after {self.timeout_s:.0f}s. "
                    "It may still complete and may still be billed — reconcile before re-running.",
                    request_id=request_id,
                )
            self.sleep(self.poll_interval_s)

    def result(self, queued: QueuedRequest) -> dict[str, Any]:
        res = self._json(queued.response_url)
        if not isinstance(res, dict):
            raise ProviderFailed(
                f"fal returned a non-object result for {queued.request_id}: {res!r}"
            )
        return res


def raise_if_failed(status: dict[str, Any], request_id: str) -> None:
    """COMPLETED carrying an error is a failure, not a success (ADR 0006).

    Separated out and named so the reason is visible at the call site: this is
    the single most consequential thing a guessed adapter gets wrong.
    """
    error = status.get("error")
    if error:
        raise ProviderFailed(
            f"fal request {request_id} completed with an error "
            f"[{status.get('error_type', 'unknown')}]: {error}"
        )


def first_media_url(result: dict[str, Any]) -> str:
    """Find the generated file's URL in a model's output.

    Output shape is per-model, so this looks for the common containers rather
    than assuming one. It raises with the payload when it cannot find a URL,
    because a silent None here becomes a mystery much further downstream.
    """
    for key in ("video", "image", "audio", "file"):
        node = result.get(key)
        if isinstance(node, dict) and isinstance(node.get("url"), str):
            return str(node["url"])
    for key in ("videos", "images", "files", "outputs"):
        node = result.get(key)
        if isinstance(node, list) and node:
            first = node[0]
            if isinstance(first, dict) and isinstance(first.get("url"), str):
                return str(first["url"])
            if isinstance(first, str) and first.startswith("http"):
                return first
    if isinstance(result.get("url"), str):
        return str(result["url"])
    raise ProviderFailed(
        f"fal returned a result with no recognisable media URL. Keys: {sorted(result)}. "
        "Per-model output shapes differ; check this model's page and extend first_media_url."
    )


@dataclass
class FalVideoProvider:
    """Image-to-video through fal's queue.

    The model id and price come from config, never from here — CLAUDE.md
    rule 1. This class knows how to talk to fal; it does not know which model
    it is talking to or what that costs.
    """

    cfg: ProviderConfig
    client: FalClient | None = None
    download: Callable[[str, Path], Path] | None = None
    #: Local keyframe -> a URL fal can fetch. Its own collaborator because this
    #: is the one piece of the flow that is still unverified: fal's upload API
    #: was not read when ADR 0006 was written, so the default refuses rather
    #: than guesses. Everything either side of it is implemented and tested.
    resolve_keyframe: Callable[[Path], str] | None = None
    #: Called with the handle as soon as a request is queued, before any
    #: polling. The moment money is committed is the moment the id becomes
    #: worth recording: if everything after this fails, that id is the only way
    #: to find what was paid for.
    on_submit: Callable[[QueuedRequest], None] | None = None
    #: Per-model input fields. Every fal model has its own schema — the queue
    #: contract is shared, the arguments are not — so this is the seam for a
    #: model that wants something the defaults above do not cover.
    extra_arguments: dict[str, Any] | None = None
    #: Content-moderation strictness, 1 (most strict) to 6 (least). Left at
    #: fal's own default: loosening a provider's safety setting is an owner
    #: decision, not an engineering convenience, and this project's whole
    #: posture is that such choices get made deliberately and written down.
    safety_tolerance: str = "4"
    name: str = field(default="fal-video", init=False)

    def __post_init__(self) -> None:
        if self.client is None:
            # No key is not an error here: it may be injected in front of us.
            # A real misconfiguration surfaces as a 401, which says so plainly.
            self.client = FalClient(api_key=os.environ.get(API_KEY_ENV))
        if self.download is None:
            self.download = _download
        if self.resolve_keyframe is None:
            self.resolve_keyframe = data_uri_keyframe

    def generate(self, req: VideoRequest, dest: Path) -> Path:
        if not self.cfg.model:
            raise ProviderNotConfigured(
                f"providers.{self.cfg.kind}.{self.cfg.slot} has no model id. "
                "Read the model's own page for its id and price, then record both "
                "in config/spike.yaml with a verified_on date."
            )
        # All three are set in __post_init__.
        assert self.client is not None
        assert self.download is not None
        assert self.resolve_keyframe is not None

        arguments: dict[str, Any] = {
            "prompt": req.prompt,
            "image_url": self.resolve_keyframe(req.keyframe),
            "duration": veo_duration(req.duration_s),
            # Audio defaults to TRUE on this model and doubles the per-second
            # rate. S0.5 asks whether her face survives being animated, which no
            # soundtrack affects, so paying double across the matrix would be
            # spending on the wrong question. Whether native audio can replace
            # the lip-sync stage is a separate run (ADR 0005).
            "generate_audio": False,
            "resolution": "720p",
            # NEVER true. auto_fix rewrites a prompt that trips the content
            # checker and runs the rewrite instead. In a condition matrix the
            # prompt IS the variable, so a silent rewrite means the cell you
            # recorded is not the cell that ran -- the same class of error as
            # calibrating in a space the scorer does not read. Explicit rather
            # than inherited, so a change of provider default cannot turn it on.
            "auto_fix": False,
            # 1 strictest, 6 loosest; fal's default is 4. Stated explicitly for
            # the same reason: a moderation setting that moves because someone
            # changed a default is a silent change to what the run measured.
            "safety_tolerance": self.safety_tolerance,
        }
        arguments.update(self.extra_arguments or {})
        queued = self.client.submit(self.cfg.model, arguments)
        # Surfaced so a run whose polling fails can still be reconciled against
        # fal: without the id, a job that was queued and billed is unfindable.
        if self.on_submit is not None:
            self.on_submit(queued)
        status = self.client.wait(queued)
        raise_if_failed(status, queued.request_id)
        result = self.client.result(queued)
        return self.download(first_media_url(result), dest)


#: fal warns against data URIs "for files larger than a few KB" because the
#: whole file rides in the request payload. A keyframe is far larger than that,
#: so this is a deliberate trade rather than an oversight: it is a documented
#: input format, it needs no vendor SDK and no infrastructure of our own, and at
#: spike volumes the inefficiency costs nothing that matters. The cap exists so
#: the trade stays small — past it, the answer is the CDN, not a bigger payload.
MAX_DATA_URI_BYTES = 4 * 1024 * 1024

#: veo3.1 image-to-video takes `duration` as one of these literals, not a
#: number, and `generate_audio` defaults to TRUE. Read from the model's API
#: reference 2026-09-23. The queue docs say nothing about either: every model
#: carries its own input schema, and only a real call or its reference page
#: reveals it. Sending 5.0 seconds was rejected with a 422 naming these values.
VEO_DURATIONS = ("4s", "6s", "8s")


def veo_duration(seconds: float, allowed: tuple[str, ...] = VEO_DURATIONS) -> str:
    """Express a duration the way this model wants it, or refuse.

    Deliberately not "snap to the nearest allowed value": silently turning a
    requested 5 seconds into 4 changes both what is measured and what is
    billed, and would do so invisibly. A mismatch is a configuration error and
    says so.
    """
    literal = f"{seconds:g}s"
    if literal not in allowed:
        raise ProviderNotConfigured(
            f"this model accepts durations {', '.join(allowed)}, not {literal}. "
            "Set generation.clip_duration_s to one of them — it is not rounded for "
            "you, because a silently shortened clip changes the measurement and the "
            "bill."
        )
    return literal


def data_uri_keyframe(
    keyframe: Path,
    max_bytes: int = MAX_DATA_URI_BYTES,
    aspect: float | None = ASPECT_9_16,
) -> str:
    """Inline a local keyframe as a `data:` URI.

    One of three documented ways to give fal a file (ADR 0006): the SDK's CDN
    upload, a data URI, or a URL you already host. Raw REST upload is *not*
    documented — the CDN page says auth is handled by the SDK — so implementing
    one would mean reverse-engineering it, which is the guess this project
    refuses to make.

    Refuses rather than truncates above the cap, because a silently shortened
    keyframe would produce a video of something else entirely.
    """
    if not keyframe.is_file():
        raise ProviderNotConfigured(f"keyframe does not exist: {keyframe}")

    raw = keyframe.read_bytes()
    if aspect is not None:
        # veo crops an off-ratio input to fit, blind to where the subject is.
        # Doing it here makes the crop deliberate and reproducible, and means
        # the image that gets animated is one we chose the framing of.
        with Image.open(io.BytesIO(raw)) as img:
            cropped = crop_to_aspect(img.convert("RGB"), aspect)
            if cropped.size != img.size:
                buf = io.BytesIO()
                cropped.save(buf, format="JPEG", quality=95)
                raw = buf.getvalue()
                keyframe = keyframe.with_suffix(".jpg")  # for the media type below
    if len(raw) > max_bytes:
        raise ProviderNotConfigured(
            f"{keyframe.name} is {len(raw) / 1024 / 1024:.1f}MB, over the "
            f"{max_bytes / 1024 / 1024:.0f}MB data-URI cap. fal discourages inlining "
            "large files; upload it to their CDN or host it yourself and pass the URL "
            "via resolve_keyframe."
        )
    mime, _ = mimetypes.guess_type(keyframe.name)
    if mime is None or not mime.startswith("image/"):
        raise ProviderNotConfigured(
            f"cannot tell what image type {keyframe.name} is; fal needs a media type"
        )
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _require_hosted_keyframe(keyframe: Path) -> str:
    """Alternative resolver: accept only files someone else already hosts.

    Kept because it is the right choice once there is somewhere to host
    keyframes: fal's runner fetches the URL itself, so nothing is inlined and
    nothing is uploaded. Not the default, because that host does not exist yet.

    Note a `Path` cannot carry a URL — `Path("https://x/y")` normalises the
    double slash away — so this takes the URL separately rather than sniffing
    the path.
    """
    raise ProviderNotConfigured(
        f"no hosted URL for {keyframe}. Use data_uri_keyframe, or pass a resolver "
        "that returns a publicly fetchable URL — fal's runner downloads it directly, "
        "so it must need no auth header."
    )


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())
    return dest
