"""A fidelity pass on a keyframe, because the generator renders her too smoothly.

The owner's verdict on an otherwise-passing shot was *"it's her but almost a more AI
version of her"*, and that turned out to be measurable rather than impressionistic.
Laplacian variance inside the face box, measured at the size the video model actually
renders from, puts a flux+LoRA keyframe at **100.2** against **222.7** for her own
training stills — under half the fine detail of the real photographs the LoRA was trained
on. Running a detail pass takes it to **204.2**, or 92% of her stills, and moves identity
by **-0.00165**.

**Why this is a separate pass and not a better model.** The LoRA is a FLUX.1 [dev] LoRA, so
inference has to stay on that architecture, and ADR 0010 pins it to fal besides.
`fal-ai/flux-2-pro` accepts no LoRAs at all; `fal-ai/flux-general` accepts them but is the
same FLUX.1 [dev] base at double the price — control extensions rather than fidelity.
Changing the image model means retraining, which re-opens D-C before anything can publish.

**Why identity must be re-scored after it.** This provider's whole job is inventing detail
that was not in the input, and invented detail on a face is a different face. Its defaults
(`creativity: 0.35`, `resemblance: 0.6`) are far too loose for that; the settings live in
`config/providers.yaml` and the measured identity delta is recorded beside them. Nothing
here is trusted to preserve identity — it is checked, by the caller, against the same
threshold the gate will use.

**Licence, unresolved.** clarity-upscaler is built on Stable Diffusion 1.5 plus a
ControlNet tile and an ESRGAN upscaler, whose licences differ from each other and from
FLUX's. No weights are pulled locally, but commercial output licensing is unanswered, so
the slot is marked measurement-only. Like D-C, this does not block measuring and does block
publishing.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx

from app.pipeline.errors import PipelineError


class DetailPassFailed(PipelineError):
    """The fidelity pass did not return a usable image."""


def detail_pass(
    client: httpx.Client,
    *,
    queue_root: str,
    model: str,
    source: Path,
    dest: Path,
    base: dict[str, Any],
    poll_interval_s: float = 3.0,
    max_polls: int = 150,
) -> Path:
    """Run one keyframe through the fidelity pass.

    The image goes as a data URI rather than a presigned URL because it is one keyframe at
    about a megabyte, and a bucket round-trip buys nothing at that size. The 2MB ceiling
    that `app.identity.training` enforces for LoRA archives does not apply — that guard
    exists because a 22MB archive was silently billed as COMPLETED with no weights, which
    is a training-endpoint failure, not an inference one.
    """
    payload = base64.b64encode(source.read_bytes()).decode()
    arguments: dict[str, Any] = {"image_url": f"data:image/png;base64,{payload}", **base}

    response = client.post(f"{queue_root}/{model}", json=arguments)
    if response.status_code >= 400:
        raise DetailPassFailed(f"submit failed {response.status_code}: {response.text[:400]}")
    submitted = response.json()
    status_url = str(submitted.get("status_url") or "")
    response_url = str(submitted.get("response_url") or "")
    if not status_url or not response_url:
        raise DetailPassFailed("provider accepted the job but returned no URLs to follow it")

    for _ in range(max_polls):
        if client.get(status_url).json().get("status") in {"COMPLETED", "FAILED", "ERROR"}:
            break
        time.sleep(poll_interval_s)

    result = client.get(response_url)
    if result.status_code >= 400:
        raise DetailPassFailed(f"detail pass failed {result.status_code}: {result.text[:400]}")
    url = str((result.json().get("image") or {}).get("url") or "")
    if not url:
        raise DetailPassFailed(f"COMPLETED with no image: {str(result.json())[:400]}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(client.get(url, timeout=300.0).content)
    return dest


def require_identity_preserved(before: float, after: float, *, tolerance: float = 0.005) -> None:
    """Refuse a detail pass that moved the face, not just its texture.

    The measured delta is -0.00165, so a tolerance of 0.005 is about three times the
    observed movement — loose enough not to fire on noise, tight enough that a pass which
    actually redrew her features cannot slip through. A pass that *raises* the score is not
    cause for alarm and is not refused; identity is still judged on its own merits
    afterwards by the gate.
    """
    if after < before - tolerance:
        raise DetailPassFailed(
            f"the detail pass moved identity from {before:.5f} to {after:.5f}, a drop of "
            f"{before - after:.5f} against a {tolerance} tolerance. This provider invents "
            f"detail, and invented detail on a face is a different face — so a drop this "
            f"size means it redrew her rather than sharpening her."
        )
