"""The fidelity pass, and the guard that stops it redrawing her face.

Measured 2026-10-01: a flux+LoRA keyframe carries 100.2 of fine detail against 222.7 for
her own training stills, and the pass takes it to 204.2 while moving identity by -0.00165.
The provider's job is inventing detail that was not in the input, so the interesting tests
are the ones about what happens when it invents too much.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.pipeline.fidelity import DetailPassFailed, detail_pass, require_identity_preserved


def _handler(
    sent: list[dict[str, Any]], *, image: str | None = "https://cdn/out.png", status: int = 200
):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            sent.append(json.loads(request.content))
            return httpx.Response(
                200, json={"status_url": "https://s", "response_url": "https://r"}
            )
        if str(request.url) == "https://s":
            return httpx.Response(200, json={"status": "COMPLETED"})
        if str(request.url) == "https://r":
            if status >= 400:
                return httpx.Response(status, json={"detail": "nope"})
            return httpx.Response(200, json={"image": {"url": image} if image else {}})
        return httpx.Response(200, content=b"detailed-bytes")

    return handle


def test_the_keyframe_goes_as_a_data_uri_with_the_configured_settings() -> None:
    """Settings come from config, never from the provider's defaults.

    Its defaults are creativity 0.35 and resemblance 0.6, which invent far too freely for
    a face. The low-creativity settings are the whole reason identity survives.
    """
    sent: list[dict[str, Any]] = []
    with (
        httpx.Client(transport=httpx.MockTransport(_handler(sent))) as client,
        tempfile.TemporaryDirectory() as tmp,
    ):
        src = Path(tmp) / "kf.png"
        src.write_bytes(b"\x89PNG fake")
        out = detail_pass(
            client,
            queue_root="https://queue",
            model="m",
            source=src,
            dest=Path(tmp) / "out.png",
            base={"creativity": 0.1, "resemblance": 0.9, "upscale_factor": 2},
            poll_interval_s=0.0,
        )
        assert out.read_bytes() == b"detailed-bytes"

    assert sent[0]["image_url"].startswith("data:image/png;base64,")
    assert sent[0]["creativity"] == 0.1
    assert sent[0]["resemblance"] == 0.9


def test_a_completed_job_with_no_image_is_a_failure() -> None:
    """ADR 0006: COMPLETED can mean "never validated" on this platform."""
    sent: list[dict[str, Any]] = []
    with (
        httpx.Client(transport=httpx.MockTransport(_handler(sent, image=None))) as client,
        tempfile.TemporaryDirectory() as tmp,
    ):
        src = Path(tmp) / "kf.png"
        src.write_bytes(b"x")
        with pytest.raises(DetailPassFailed, match="COMPLETED with no image"):
            detail_pass(
                client,
                queue_root="https://queue",
                model="m",
                source=src,
                dest=Path(tmp) / "out.png",
                base={},
                poll_interval_s=0.0,
            )


def test_a_pass_that_preserves_identity_is_allowed() -> None:
    """The measured delta is -0.00165, well inside tolerance."""
    require_identity_preserved(0.97028, 0.96862)


def test_a_pass_that_redrew_her_face_is_refused() -> None:
    """A large drop means invented detail changed the features, not the texture."""
    with pytest.raises(DetailPassFailed, match="redrew her rather than sharpening her"):
        require_identity_preserved(0.97028, 0.95000)


def test_a_pass_that_raises_the_score_is_not_treated_as_a_fault() -> None:
    """Sharpening can help the scorer. That is not suspicious, and the gate still decides."""
    require_identity_preserved(0.96000, 0.96500)


def test_the_tolerance_is_about_three_times_the_observed_movement() -> None:
    """Loose enough not to fire on noise, tight enough to catch a redraw."""
    require_identity_preserved(0.97000, 0.96550)  # -0.0045, inside
    with pytest.raises(DetailPassFailed):
        require_identity_preserved(0.97000, 0.96400)  # -0.0060, outside
