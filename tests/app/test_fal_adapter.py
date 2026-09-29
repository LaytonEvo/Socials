"""The fal image adapter, against a mock transport.

No network and no key: `httpx.MockTransport` lets the test assert what the adapter
actually *sends*, which is the part ADR 0006 says a guessed implementation gets wrong.
Four of the tests here exist because that ADR names four specific mistakes.

The most important is the `COMPLETED with no image` case. fal returns a clean status for
a request whose arguments were never validated and the status does not say so, which
means a naive adapter reports success, stores nothing, and the failure surfaces much
later as a missing file.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.providers import ImageProvider, ImageRequest, JobStatus, ProviderError
from app.providers.fal import QUEUE_ROOT, FalImageProvider, api_key, data_uri
from app.storage import MemoryStorage, key_for

from .test_storage import PERSONA

MODEL = "fal-ai/nano-banana-2/edit"
KEY = key_for(PERSONA, "reference", "outfit-m_000.png")
IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake png payload"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAL_KEY", "test-key")


@pytest.fixture
def still(tmp_path: Path) -> Path:
    path = tmp_path / "m_000.png"
    path.write_bytes(IMAGE_BYTES)
    return path


def _provider(
    handler: httpx.MockTransport, storage: MemoryStorage | None = None, **shape: object
) -> FalImageProvider:
    return FalImageProvider(
        model=MODEL,
        price_usd_per_image=Decimal("0.08"),
        price_verified_on=dt.date(2026, 9, 28),
        storage=storage or MemoryStorage(),
        request_shape=shape or {"image_field": "image_urls", "image_field_is_list": True},
        client=httpx.Client(transport=handler, headers={"Authorization": "Key test-key"}),
        poll_interval_s=0.0,
    )


def _queue(
    *, images: list[dict[str, str]] | None = None, statuses: list[str] | None = None
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """A transport that walks the documented submit → status → retrieve sequence."""
    seen: list[httpx.Request] = []
    remaining = list(statuses or ["COMPLETED"])
    payload = {"images": images if images is not None else [{"url": "https://v3b.fal.media/x.png"}]}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req-1", "status": "IN_QUEUE"})
        if url.endswith("/status"):
            return httpx.Response(
                200, json={"status": remaining.pop(0) if remaining else "COMPLETED"}
            )
        if url.startswith("https://v3b.fal.media"):
            return httpx.Response(200, content=IMAGE_BYTES, headers={"content-type": "image/png"})
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handle), seen


# --------------------------------------------------------------- happy path --
async def test_an_edit_is_submitted_polled_and_stored(still: Path) -> None:
    transport, seen = _queue()
    storage = MemoryStorage()
    provider = _provider(transport, storage)

    job = await provider.generate(
        ImageRequest(prompt="a low-cut polo and a skort"), key=KEY, source=still
    )
    result = await provider.poll(job)

    assert job.status is JobStatus.SUCCEEDED
    assert job.provider_job_id == "req-1"
    assert job.cost_usd == Decimal("0.08")
    assert result.storage_key == KEY
    assert storage.get(KEY) == IMAGE_BYTES

    assert str(seen[0].url) == f"{QUEUE_ROOT}/{MODEL}"
    assert seen[0].headers["authorization"] == "Key test-key"


async def test_it_polls_until_the_request_completes(still: Path) -> None:
    transport, seen = _queue(statuses=["IN_QUEUE", "IN_PROGRESS", "COMPLETED"])
    provider = _provider(transport)
    await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)
    assert sum(1 for r in seen if str(r.url).endswith("/status")) == 3


def test_it_satisfies_the_image_provider_protocol() -> None:
    transport, _ = _queue()
    assert isinstance(_provider(transport), ImageProvider)


# ------------------------------------- her stills never reach a public CDN --
async def test_the_source_image_is_sent_inline_not_uploaded(still: Path) -> None:
    """ADR 0006: fal's CDN files are public — "anyone with the URL can download".

    For a persona's reference set that is not an acceptable default, and the size cap
    makes it unnecessary: every master still fits as a data URI. This asserts nothing is
    uploaded and the bytes travel in the request.
    """
    transport, seen = _queue()
    provider = _provider(transport)
    await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)

    body = json.loads(seen[0].content)
    sent = body["image_urls"][0]
    assert sent.startswith("data:image/png;base64,")
    assert base64.b64decode(sent.split(",", 1)[1]) == IMAGE_BYTES
    assert not any("upload" in str(r.url) for r in seen)


async def test_the_image_field_name_comes_from_config(still: Path) -> None:
    """Every fal model names it differently and the wrong name is a 422, so it lives in
    config beside the model id rather than in the adapter."""
    transport, seen = _queue()
    provider = _provider(transport, None, image_field="start_image_url")
    await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)
    assert "start_image_url" in json.loads(seen[0].content)


async def test_a_source_with_no_configured_field_is_refused(still: Path) -> None:
    transport, _ = _queue()
    provider = _provider(transport, None, base={})
    with pytest.raises(ProviderError, match="no `image_field`"):
        await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)


# ----------------------------------------- [ADR 0006] COMPLETED is not enough --
async def test_completed_with_no_image_is_a_failure(still: Path) -> None:
    """The trap ADR 0006 exists to document.

    fal returns a clean COMPLETED for a request whose arguments were never validated. A
    naive adapter reports success, stores nothing, and the failure surfaces later as a
    missing file — after it has been paid for.
    """
    transport, _ = _queue(images=[])
    provider = _provider(transport)
    with pytest.raises(ProviderError, match="COMPLETED with no image"):
        await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)

    job = provider.jobs[-1]
    assert job.status is JobStatus.FAILED
    assert job.billed is True, "generation was reached, so this is spend"
    assert job.cost_usd == Decimal("0.08")


async def test_an_unrecognised_status_is_treated_as_billed(still: Path) -> None:
    """Generation may well have happened, so the safe direction is to assume it did."""
    transport, _ = _queue(statuses=["WHO_KNOWS"])
    provider = _provider(transport)
    with pytest.raises(ProviderError, match="unrecognised status"):
        await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)
    assert provider.jobs[-1].billed is True


# ---------------------------------------------- billed versus free failures --
@pytest.mark.parametrize("code", [401, 403, 422])
async def test_a_refusal_before_work_costs_nothing(still: Path, code: int) -> None:
    """A 403 is free on every operation, not only on submit — the spike measured this."""
    transport = httpx.MockTransport(lambda r: httpx.Response(code, text="nope"))
    provider = _provider(transport)
    with pytest.raises(ProviderError) as exc:
        await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)

    assert exc.value.billed is False
    job = provider.jobs[-1]
    assert job.billed is False
    assert job.cost_usd == Decimal("0")


async def test_a_server_error_is_treated_as_billed(still: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    provider = _provider(transport)
    with pytest.raises(ProviderError) as exc:
        await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)
    assert exc.value.billed is True


async def test_a_timeout_is_billed_because_generation_had_started(still: Path) -> None:
    """Amendment A2's case exactly: paid, and nothing to show for it."""
    transport, _ = _queue(statuses=["IN_PROGRESS"] * 200)
    provider = _provider(transport)
    provider.timeout_s = 0.01
    with pytest.raises(ProviderError, match="did not finish"):
        await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)
    assert provider.jobs[-1].billed is True


async def test_polling_a_failed_job_raises_rather_than_returning_nothing(still: Path) -> None:
    transport, _ = _queue(images=[])
    provider = _provider(transport)
    with pytest.raises(ProviderError):
        await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)
    with pytest.raises(ProviderError):
        await provider.poll(provider.jobs[-1])


# ---------------------------------------------------------------- pricing --
def test_cost_is_estimated_from_the_configured_price() -> None:
    transport, _ = _queue()
    provider = _provider(transport, None, base={"num_images": 3})
    assert provider.estimate_cost(ImageRequest(prompt="p")) == Decimal("0.24")


# ------------------------------------------------------------------- key --
def test_an_absent_key_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Because a proxy may be holding the credential.

    Claude Code's cloud environments offer API credentials as a separate thing from
    environment variables: an egress proxy holds the value, scoped to fal's hostnames,
    and the session never sees it. Verified on 2026-09-29 — an unauthenticated POST and
    one with a deliberately wrong key both returned 404 rather than 401, which only
    happens if the header is being replaced.

    So `api_key()` returns None and the adapter sends no header, rather than raising on
    a configuration that is working correctly.
    """
    monkeypatch.delenv("FAL_KEY", raising=False)
    assert api_key() is None


async def test_no_authorization_header_is_sent_when_there_is_no_key(
    monkeypatch: pytest.MonkeyPatch, still: Path
) -> None:
    """`Key None` would be worse than nothing: it turns a proxy-authenticated request
    into an explicitly bad one."""
    monkeypatch.delenv("FAL_KEY", raising=False)
    transport, seen = _queue()
    provider = FalImageProvider(
        model=MODEL,
        price_usd_per_image=Decimal("0.08"),
        price_verified_on=dt.date(2026, 9, 28),
        storage=MemoryStorage(),
        request_shape={"image_field": "image_urls", "image_field_is_list": True},
        client=httpx.Client(transport=transport),
        poll_interval_s=0.0,
    )
    await provider.generate(ImageRequest(prompt="p"), key=KEY, source=still)
    assert "authorization" not in seen[0].headers


def test_a_data_uri_carries_the_right_media_type(tmp_path: Path) -> None:
    jpg = tmp_path / "x.jpg"
    jpg.write_bytes(b"\xff\xd8\xff")
    assert data_uri(jpg).startswith("data:image/jpeg;base64,")
