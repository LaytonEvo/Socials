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

from .config import ProviderConfig
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

    def _json(self, url: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
        payload = json.dumps(body).encode() if body is not None else None
        status, raw = self.transport(url, method, payload, self._headers())
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderFailed(
                f"fal returned {status} with a body that is not JSON: {raw[:200]!r}"
            ) from None
        if status in (401, 403):
            raise ProviderRefused(
                f"fal rejected the request ({status}). Neither authentication route is "
                f"working: {API_KEY_ENV} is "
                f"{'set' if self.api_key else 'NOT set'} in this process, and no "
                "credential appears to be injected in front of it. Set the environment "
                "variable, or configure header injection for *.fal.run — but not both, "
                "since two Authorization headers is its own failure."
            )
        if status >= 400:
            detail = parsed.get("detail") if isinstance(parsed, dict) else parsed
            raise ProviderFailed(f"fal returned {status}: {detail!r}")
        return parsed

    def submit(self, model_id: str, arguments: dict[str, Any]) -> str:
        """Queue a request and return its id. Does not wait."""
        res = self._json(f"{QUEUE_ROOT}/{model_id}", "POST", arguments)
        request_id = res.get("request_id") if isinstance(res, dict) else None
        if not request_id:
            raise ProviderFailed(f"fal accepted the submission but returned no request_id: {res!r}")
        return str(request_id)

    def wait(self, model_id: str, request_id: str) -> dict[str, Any]:
        """Poll until the request reaches COMPLETED, then return its status.

        Raises on timeout rather than returning a partial result, and carries
        the request id on the exception: a timed-out request may still have
        been billed, so the run has to be reconcilable afterwards.
        """
        deadline = self.now() + self.timeout_s
        status_url = f"{QUEUE_ROOT}/{model_id}/requests/{request_id}/status"
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

    def result(self, model_id: str, request_id: str) -> dict[str, Any]:
        res = self._json(f"{QUEUE_ROOT}/{model_id}/requests/{request_id}")
        if not isinstance(res, dict):
            raise ProviderFailed(f"fal returned a non-object result for {request_id}: {res!r}")
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
            "duration": req.duration_s,
            "seed": req.seed,
        }
        request_id = self.client.submit(self.cfg.model, arguments)
        status = self.client.wait(self.cfg.model, request_id)
        raise_if_failed(status, request_id)
        result = self.client.result(self.cfg.model, request_id)
        return self.download(first_media_url(result), dest)


#: fal warns against data URIs "for files larger than a few KB" because the
#: whole file rides in the request payload. A keyframe is far larger than that,
#: so this is a deliberate trade rather than an oversight: it is a documented
#: input format, it needs no vendor SDK and no infrastructure of our own, and at
#: spike volumes the inefficiency costs nothing that matters. The cap exists so
#: the trade stays small — past it, the answer is the CDN, not a bigger payload.
MAX_DATA_URI_BYTES = 4 * 1024 * 1024


def data_uri_keyframe(keyframe: Path, max_bytes: int = MAX_DATA_URI_BYTES) -> str:
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
