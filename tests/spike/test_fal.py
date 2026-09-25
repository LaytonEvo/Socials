"""The fal adapter, against the contract recorded in ADR 0006.

Every fixture response here is shaped from fal's own documented examples, read
2026-09-23. No network, no key: the transport is injected, which is the point
of it being injectable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.spike.config import ProviderConfig
from scripts.spike.errors import ProviderFailed, ProviderNotConfigured, ProviderTimeout
from scripts.spike.fal import (
    FalClient,
    FalVideoProvider,
    QueuedRequest,
    first_media_url,
    raise_if_failed,
)
from scripts.spike.providers import VideoRequest

MODEL = "fal-ai/some-video-model"

#: A handle as fal would return it, for tests that poll without submitting.
QUEUED = QueuedRequest(
    request_id="abc",
    status_url=f"https://queue.fal.run/{MODEL}/requests/abc/status",
    response_url=f"https://queue.fal.run/{MODEL}/requests/abc",
)


class FakeTransport:
    """Records calls and replays queued responses."""

    def __init__(self, responses: list[tuple[int, dict[str, object]]]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, object] | None, dict[str, str]]] = []

    def __call__(self, url, method, body, headers):
        self.calls.append((url, method, json.loads(body) if body else None, headers))
        if not self._responses:
            raise AssertionError(f"unexpected extra call to {url}")
        status, payload = self._responses.pop(0)
        return status, json.dumps(payload).encode()


def _client(responses, **kw) -> FalClient:
    return FalClient(
        api_key="test-key",
        transport=FakeTransport(responses),
        poll_interval_s=0,
        sleep=lambda _s: None,
        **kw,
    )


def _cfg() -> ProviderConfig:
    import datetime as dt

    return ProviderConfig(
        slot="flagship",
        kind="video",
        backend="fal",
        model=MODEL,
        endpoint=None,
        price=0.10,
        price_unit="second",
        verified_on=dt.date(2026, 9, 23),
    )


def test_auth_header_is_Key_not_Bearer():
    """Verified 2026-09-23. Getting this wrong is a 401 on the first live call."""
    c = _client([(200, {"request_id": "abc"})])
    c.submit(MODEL, {"prompt": "x"})
    _url, _m, _b, headers = c.transport.calls[0]  # type: ignore[attr-defined]
    assert headers["Authorization"] == "Key test-key"


def test_submit_posts_arguments_unwrapped_to_the_queue_host():
    """REST takes the arguments directly; `input:` is a client-library shape."""
    c = _client([(200, {"request_id": "abc"})])
    assert c.submit(MODEL, {"prompt": "a swing"}).request_id == "abc"
    url, method, body, _h = c.transport.calls[0]  # type: ignore[attr-defined]
    assert url == f"https://queue.fal.run/{MODEL}"
    assert method == "POST"
    assert body == {"prompt": "a swing"}
    assert "input" not in body


def test_completed_carrying_an_error_is_a_failure():
    """THE one a guessed adapter gets wrong. COMPLETED is terminal, not good."""
    with pytest.raises(ProviderFailed, match="content_policy"):
        raise_if_failed(
            {"status": "COMPLETED", "error": "blocked", "error_type": "content_policy"}, "abc"
        )


def test_completed_without_an_error_passes():
    raise_if_failed({"status": "COMPLETED", "metrics": {"inference_time": 3.4}}, "abc")


def test_wait_polls_through_queue_and_progress_to_completed():
    c = _client(
        [
            (200, {"status": "IN_QUEUE", "queue_position": 2}),
            (200, {"status": "IN_PROGRESS", "logs": []}),
            (200, {"status": "COMPLETED", "metrics": {"inference_time": 3.4}}),
        ]
    )
    assert c.wait(QUEUED)["status"] == "COMPLETED"


def test_a_timeout_carries_the_request_id():
    """A timed-out request may still have been billed, so it must stay traceable."""
    ticks = iter([0.0, 0.0, 999.0, 999.0])
    c = _client(
        [(200, {"status": "IN_QUEUE", "queue_position": 1})] * 4,
        timeout_s=10.0,
    )
    c.now = lambda: next(ticks)
    with pytest.raises(ProviderTimeout) as excinfo:
        c.wait(QUEUED)
    assert excinfo.value.request_id == "abc"
    assert "reconcile" in str(excinfo.value)


def test_an_unknown_status_stops_rather_than_guessing():
    """ADR 0006 records three states. A fourth means the contract moved."""
    c = _client([(200, {"status": "SOMETHING_NEW"})])
    with pytest.raises(ProviderFailed, match="unrecognised status"):
        c.wait(QUEUED)


def test_an_http_error_surfaces_the_status_and_detail():
    """A non-auth error. 401 and 403 take the dedicated path above, because
    "unauthorized" has two possible causes here and a bare status says neither."""
    c = _client([(500, {"detail": "internal"})])
    with pytest.raises(ProviderFailed, match="500"):
        c.submit(MODEL, {"prompt": "x"})


def test_an_error_with_an_html_body_reports_the_status_and_the_snippet():
    """A gateway page is not JSON, but the status is the useful part and the
    body is the detail. Reporting only "not JSON" buried both."""

    def transport(url, method, body, headers):
        return 502, b"<html>bad gateway</html>"

    c = FalClient(api_key="k", transport=transport)
    with pytest.raises(ProviderFailed, match="502") as excinfo:
        c.submit(MODEL, {"prompt": "x"})
    assert "bad gateway" in str(excinfo.value)


def test_a_success_with_a_non_json_body_still_complains_about_the_body():
    """Here the status says nothing is wrong, so the body is the whole story."""

    def transport(url, method, body, headers):
        return 200, b"not json at all"

    c = FalClient(api_key="k", transport=transport)
    with pytest.raises(ProviderFailed, match="not JSON"):
        c.submit(MODEL, {"prompt": "x"})


def test_submission_without_a_request_id_is_refused():
    c = _client([(200, {"queue_position": 0})])
    with pytest.raises(ProviderFailed, match="no request_id"):
        c.submit(MODEL, {"prompt": "x"})


@pytest.mark.parametrize(
    "payload",
    [
        {"video": {"url": "https://v3.fal.media/x.mp4"}},
        {"videos": [{"url": "https://v3.fal.media/x.mp4"}]},
        {"images": [{"url": "https://v3.fal.media/x.mp4"}]},
        {"url": "https://v3.fal.media/x.mp4"},
        {"outputs": ["https://v3.fal.media/x.mp4"]},
    ],
)
def test_media_url_is_found_across_per_model_output_shapes(payload):
    assert first_media_url(payload) == "https://v3.fal.media/x.mp4"


def test_an_unrecognisable_result_names_its_keys():
    """So the next person knows which model page to go and read."""
    with pytest.raises(ProviderFailed, match="no recognisable media URL"):
        first_media_url({"weird": 1, "other": 2})


def test_generate_runs_submit_wait_result_then_downloads(tmp_path):
    c = _client(
        [
            (200, {"request_id": "abc"}),
            (200, {"status": "COMPLETED", "metrics": {"inference_time": 5.0}}),
            (200, {"video": {"url": "https://v3.fal.media/clip.mp4"}}),
        ]
    )
    downloaded: list[str] = []

    def fake_download(url: str, dest: Path) -> Path:
        downloaded.append(url)
        dest.write_bytes(b"MP4")
        return dest

    provider = FalVideoProvider(
        _cfg(),
        client=c,
        download=fake_download,
        resolve_keyframe=lambda _p: "https://example.com/her.jpg",
    )
    dest = tmp_path / "clip.mp4"
    out = provider.generate(
        VideoRequest(
            keyframe=tmp_path / "her.jpg",
            prompt="a swing",
            duration_s=4.0,
            seed=1,
            ref="t1",
        ),
        dest,
    )
    assert out.read_bytes() == b"MP4"
    assert downloaded == ["https://v3.fal.media/clip.mp4"]
    # The resolved URL is what actually got submitted, not the local path.
    _url, _m, body, _h = c.transport.calls[0]  # type: ignore[attr-defined]
    assert body is not None and body["image_url"] == "https://example.com/her.jpg"
    # And the resolved keyframe URL is what was submitted.
    _url, _m, body, _h = c.transport.calls[0]  # type: ignore[attr-defined]
    assert body["image_url"] == "https://example.com/her.jpg"


def test_the_hosted_url_resolver_refuses_a_local_file(tmp_path):
    """The alternative resolver, for when there is somewhere to host keyframes.

    Not the default: nothing hosts them yet. It exists because it is the better
    route once something does — fal's runner fetches the URL itself, so nothing
    is inlined into the request at all.
    """
    from scripts.spike.fal import _require_hosted_keyframe

    with pytest.raises(ProviderNotConfigured, match="no hosted URL"):
        _require_hosted_keyframe(tmp_path / "local.jpg")


def test_generate_refuses_a_slot_with_no_model_id():
    import dataclasses

    cfg = dataclasses.replace(_cfg(), model=None)
    provider = FalVideoProvider(cfg, client=_client([]), download=lambda u, d: d)
    with pytest.raises(ProviderNotConfigured, match="no model id"):
        provider.generate(
            VideoRequest(
                keyframe=Path("https://x/y.jpg"), prompt="p", duration_s=4, seed=1, ref="t1"
            ),
            Path("out.mp4"),
        )


def test_no_api_key_is_allowed_because_it_may_be_injected_in_front(monkeypatch):
    """Absence of FAL_KEY is not an error: a proxy may add the header.

    Refusing here would break the safer of the two setups, the one where the
    key never enters the process at all.
    """
    monkeypatch.delenv("FAL_KEY", raising=False)
    provider = FalVideoProvider(_cfg())
    assert provider.client is not None
    assert provider.client.api_key is None


def test_without_a_key_no_authorization_header_is_sent(monkeypatch):
    """Sending our own alongside an injected one is two conflicting headers."""
    monkeypatch.delenv("FAL_KEY", raising=False)
    c = FalClient(transport=FakeTransport([(200, {"request_id": "abc"})]))
    c.submit(MODEL, {"prompt": "x"})
    _u, _m, _b, headers = c.transport.calls[0]  # type: ignore[attr-defined]
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"


def test_a_401_explains_both_auth_routes_rather_than_just_failing():
    c = _client([(401, {"detail": "Unauthorized"})])
    with pytest.raises(ProviderNotConfigured) as excinfo:
        c.submit(MODEL, {"prompt": "x"})
    message = str(excinfo.value)
    assert "FAL_KEY" in message
    assert "not both" in message


def test_a_403_leads_with_fals_own_reason_not_our_guess():
    """Regression: fal returns 403 for an exhausted balance too, and the first
    version of this message diagnosed authentication — sending the reader to
    the wrong settings page for a problem that was about money."""
    c = _client([(403, {"detail": "User is locked. Reason: Exhausted balance."})])
    with pytest.raises(ProviderNotConfigured) as excinfo:
        c.submit(MODEL, {"prompt": "x"})
    message = str(excinfo.value)
    assert "Exhausted balance" in message
    assert message.index("Exhausted balance") < message.index("FAL_KEY"), (
        "fal's own reason must come before our authentication guess"
    )


def test_a_refused_call_is_marked_unbillable():
    """It never reached a runner, so it must not consume the run's budget."""
    from scripts.spike.errors import ProviderRefused

    c = _client([(403, {"detail": "nope"})])
    with pytest.raises(ProviderRefused) as excinfo:
        c.submit(MODEL, {"prompt": "x"})
    assert excinfo.value.billable is False


def test_the_adapter_never_retries_a_submission_itself():
    """fal retries internally up to 10 times (ADR 0006). Stacking would multiply spend."""
    c = _client([(500, {"detail": "boom"})])
    with pytest.raises(ProviderFailed):
        c.submit(MODEL, {"prompt": "x"})
    assert len(c.transport.calls) == 1  # type: ignore[attr-defined]


def test_the_fal_backend_is_reachable_through_the_registry(monkeypatch):
    """Registration is lazy to avoid a circular import; prove it still resolves."""
    from scripts.spike.providers import load_provider

    monkeypatch.setenv("FAL_KEY", "k")
    provider = load_provider(_cfg())
    assert provider.name == "fal-video"


def test_an_unregistered_video_backend_lists_what_is_registered():
    import dataclasses

    from scripts.spike.errors import ProviderNotConfigured as PNC
    from scripts.spike.providers import load_provider

    with pytest.raises(PNC, match="fal"):
        load_provider(dataclasses.replace(_cfg(), backend="nope"))


# --- keyframe resolution: the one input fal cannot take as a local file ------


def _jpeg(path: Path, size: tuple[int, int] = (64, 64)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (120, 90, 70)).save(path, quality=90)
    return path


def test_a_keyframe_becomes_a_data_uri_cropped_to_the_ratio_veo_accepts(tmp_path):
    """Not byte-identical any more, on purpose: an off-ratio still is cropped
    here so the provider does not crop it blindly (ADR 0006)."""
    import base64
    import io

    from PIL import Image

    from scripts.spike.fal import data_uri_keyframe

    uri = data_uri_keyframe(_jpeg(tmp_path / "her.jpg", size=(928, 1232)))
    assert uri.startswith("data:image/jpeg;base64,")
    out = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    assert abs(out.width / out.height - 9 / 16) < 1e-3
    assert out.height == 1232, "a full-height slice, not a shrunken image"


def test_a_keyframe_already_at_the_right_ratio_is_sent_untouched(tmp_path):
    """No re-encode when none is needed: re-saving a JPEG loses quality for
    nothing, and the bytes on disk are what the master set was built from."""
    import base64

    from scripts.spike.fal import data_uri_keyframe

    path = _jpeg(tmp_path / "her.jpg", size=(1080, 1920))
    uri = data_uri_keyframe(path)
    assert base64.b64decode(uri.split(",", 1)[1]) == path.read_bytes()


def test_an_oversized_keyframe_is_refused_not_truncated(tmp_path):
    """A silently shortened keyframe would generate a video of something else."""
    from scripts.spike.fal import data_uri_keyframe

    big = _jpeg(tmp_path / "big.jpg", size=(1080, 1920))
    with pytest.raises(ProviderNotConfigured, match="data-URI cap"):
        data_uri_keyframe(big, max_bytes=200)


def test_a_keyframe_of_unknown_type_is_refused(tmp_path):
    from scripts.spike.fal import data_uri_keyframe

    odd = tmp_path / "keyframe.unknownext"
    odd.write_bytes(b"\x00\x01")
    with pytest.raises(ProviderNotConfigured, match="what image type"):
        data_uri_keyframe(odd, aspect=None)  # aspect=None: not a decodable image


def test_a_missing_keyframe_says_so_plainly(tmp_path):
    from scripts.spike.fal import data_uri_keyframe

    with pytest.raises(ProviderNotConfigured, match="does not exist"):
        data_uri_keyframe(tmp_path / "nope.jpg")


def test_generate_inlines_a_local_keyframe_by_default(tmp_path):
    """End to end with the shipped default resolver: no injection, no network."""
    c = _client(
        [
            (200, {"request_id": "abc"}),
            (200, {"status": "COMPLETED", "metrics": {"inference_time": 5.0}}),
            (200, {"video": {"url": "https://v3.fal.media/clip.mp4"}}),
        ]
    )
    provider = FalVideoProvider(
        _cfg(), client=c, download=lambda _u, d: (d.write_bytes(b"MP4"), d)[1]
    )
    provider.generate(
        VideoRequest(
            keyframe=_jpeg(tmp_path / "her.jpg"),
            prompt="a swing",
            duration_s=4.0,
            seed=1,
            ref="t1",
        ),
        tmp_path / "out.mp4",
    )
    _url, _m, body, _h = c.transport.calls[0]  # type: ignore[attr-defined]
    assert body is not None
    assert str(body["image_url"]).startswith("data:image/jpeg;base64,")


# --- who wasted what: refusals on submit are free, later failures are not ----


def test_a_405_with_an_empty_body_is_free_not_billed():
    """Regression from the second live run.

    An empty-bodied 405 was reported as "a body that is not JSON" -- true,
    useless, and charged $2 as though a runner had done the work. The status
    classifies it; the body is only ever extra detail.
    """
    from scripts.spike.errors import ProviderRefused

    def transport(url, method, body, headers):
        return 405, b""

    c = FalClient(transport=transport)
    with pytest.raises(ProviderRefused) as excinfo:
        c.submit(MODEL, {"prompt": "x"})
    assert excinfo.value.billable is False
    assert "405" in str(excinfo.value)
    assert "empty body" in str(excinfo.value)


def test_a_4xx_while_polling_is_billable_because_the_work_may_have_run():
    """The submission already succeeded by then, so a later 4xx says nothing
    about whether compute was spent. Assume it was."""
    c = _client([(404, {"detail": "unknown request"})])
    with pytest.raises(ProviderFailed) as excinfo:
        c.wait(QUEUED)
    assert getattr(excinfo.value, "billable", True) is True


def test_a_5xx_on_submit_is_billable_even_though_submit_refusals_are_free():
    """Free applies to refusals, not to fal breaking. A 500 may mean a runner
    started and then died, so it is charged."""
    c = _client([(500, {"detail": "internal"})])
    with pytest.raises(ProviderFailed) as excinfo:
        c.submit(MODEL, {"prompt": "x"})
    assert getattr(excinfo.value, "billable", True) is True


def test_an_error_body_that_uses_error_instead_of_detail_is_still_surfaced():
    from scripts.spike.errors import ProviderRefused

    c = _client([(403, {"error": {"type": "authorization_error"}})])
    with pytest.raises(ProviderRefused, match="authorization_error"):
        c.submit(MODEL, {"prompt": "x"})


def test_a_422_is_free_even_when_it_surfaces_late():
    """fal validates late: a request missing a required field reaches
    COMPLETED with error: None, and only the result fetch returns 422. Nothing
    ran either way, so it must not be charged."""
    from scripts.spike.errors import ProviderRefused

    c = _client([(422, {"detail": [{"type": "missing", "loc": ["body", "image_url"]}]})])
    with pytest.raises(ProviderRefused) as excinfo:
        c.result(QUEUED)
    assert excinfo.value.billable is False


def test_a_completed_status_with_no_error_does_not_prove_success():
    """It passed raise_if_failed and was still a validation failure. The
    result fetch is the second gate, not a formality."""
    raise_if_failed(
        {"status": "COMPLETED", "error": None, "metrics": {"inference_time": 0.049}}, "a"
    )


# --- follow the provider's links, do not rebuild them ------------------------


def test_polling_uses_the_urls_fal_returned_not_a_rebuilt_pattern():
    """Regression from the third live run, which cost $2 and returned nothing.

    Submitting to fal-ai/veo3.1/image-to-video returns status and response URLs
    under fal-ai/veo3.1/requests/... -- the queue groups by app, not by
    endpoint. The rebuilt URL 405'd with an empty body *after* the job had been
    queued and billed, so the clip was paid for and unreachable.
    """
    submit_res = {
        "request_id": "xyz",
        "status_url": "https://queue.fal.run/fal-ai/veo3.1/requests/xyz/status",
        "response_url": "https://queue.fal.run/fal-ai/veo3.1/requests/xyz",
        "cancel_url": "https://queue.fal.run/fal-ai/veo3.1/requests/xyz/cancel",
    }
    c = _client(
        [
            (200, submit_res),
            (200, {"status": "COMPLETED"}),
            (200, {"video": {"url": "https://v3.fal.media/x.mp4"}}),
        ]
    )
    queued = c.submit("fal-ai/veo3.1/image-to-video", {"prompt": "p"})
    c.wait(queued)
    c.result(queued)

    polled = c.transport.calls[1][0]  # type: ignore[attr-defined]
    fetched = c.transport.calls[2][0]  # type: ignore[attr-defined]
    assert polled == submit_res["status_url"]
    assert fetched == submit_res["response_url"]
    assert "image-to-video" not in polled, "rebuilding the path is what broke this"


def test_a_missing_url_falls_back_rather_than_crashing():
    """Prefer fal's links; degrade to the conventional shape if one is absent."""
    c = _client([(200, {"request_id": "xyz"})])
    queued = c.submit(MODEL, {"prompt": "p"})
    assert queued.status_url.endswith(f"{MODEL}/requests/xyz/status")
    assert queued.cancel_url is None


def test_the_request_id_is_surfaced_the_moment_money_is_committed(tmp_path):
    """If everything after submit fails, the id is the only way to find what
    was paid for. The third live run had no id and the clip was unrecoverable."""
    seen: list[str] = []
    c = _client(
        [
            (
                200,
                {"request_id": "xyz", "status_url": "https://q/s", "response_url": "https://q/r"},
            ),
            (500, {"detail": "boom"}),
        ]
    )
    provider = FalVideoProvider(
        _cfg(),
        client=c,
        download=lambda _u, d: d,
        resolve_keyframe=lambda _p: "https://example.com/k.jpg",
        on_submit=lambda q: seen.append(q.request_id),
    )
    with pytest.raises(ProviderFailed):
        provider.generate(
            VideoRequest(keyframe=tmp_path / "k.jpg", prompt="p", duration_s=4, seed=1, ref="t"),
            tmp_path / "o.mp4",
        )
    assert seen == ["xyz"], "the id must be recorded before anything can go wrong"


# --- per-model argument shape ------------------------------------------------


def test_duration_is_sent_as_the_literal_the_model_accepts():
    from scripts.spike.fal import veo_duration

    assert veo_duration(4) == "4s"
    assert veo_duration(6.0) == "6s"


def test_an_unsupported_duration_is_refused_not_rounded():
    """Snapping 5s to 4s would change both the measurement and the bill, and
    would do it invisibly."""
    from scripts.spike.fal import veo_duration

    with pytest.raises(ProviderNotConfigured) as excinfo:
        veo_duration(5.0)
    assert "4s, 6s, 8s" in str(excinfo.value)


def test_audio_is_off_and_duration_is_a_literal_in_the_submitted_body(tmp_path):
    """Regression: sending duration=5.0 was rejected 422, and generate_audio
    defaults to true on this model, which doubles the per-second rate."""
    c = _client(
        [
            (200, {"request_id": "x", "status_url": "https://q/s", "response_url": "https://q/r"}),
            (200, {"status": "COMPLETED"}),
            (200, {"video": {"url": "https://v3.fal.media/x.mp4"}}),
        ]
    )
    provider = FalVideoProvider(
        _cfg(),
        client=c,
        download=lambda _u, d: d,
        resolve_keyframe=lambda _p: "https://example.com/k.jpg",
    )
    provider.generate(
        VideoRequest(keyframe=tmp_path / "k.jpg", prompt="p", duration_s=4, seed=1, ref="t"),
        tmp_path / "o.mp4",
    )
    _u, _m, body, _h = c.transport.calls[0]  # type: ignore[attr-defined]
    assert body is not None
    assert body["duration"] == "4s"
    assert body["generate_audio"] is False
    assert body["resolution"] == "720p"


def test_extra_arguments_can_override_the_defaults(tmp_path):
    """Every fal model has its own schema; this is the seam for one that wants
    something else."""
    c = _client(
        [
            (200, {"request_id": "x", "status_url": "https://q/s", "response_url": "https://q/r"}),
            (200, {"status": "COMPLETED"}),
            (200, {"video": {"url": "https://v3.fal.media/x.mp4"}}),
        ]
    )
    provider = FalVideoProvider(
        _cfg(),
        client=c,
        download=lambda _u, d: d,
        resolve_keyframe=lambda _p: "https://example.com/k.jpg",
        extra_arguments={"resolution": "1080p"},
    )
    provider.generate(
        VideoRequest(keyframe=tmp_path / "k.jpg", prompt="p", duration_s=4, seed=1, ref="t"),
        tmp_path / "o.mp4",
    )
    _u, _m, body, _h = c.transport.calls[0]  # type: ignore[attr-defined]
    assert body is not None and body["resolution"] == "1080p"


def test_auto_fix_is_always_off(tmp_path):
    """auto_fix rewrites a prompt that trips the content checker and runs the
    rewrite. In a condition matrix the prompt is the variable, so the cell
    recorded would not be the cell that ran."""
    c = _client(
        [
            (200, {"request_id": "x", "status_url": "https://q/s", "response_url": "https://q/r"}),
            (200, {"status": "COMPLETED"}),
            (200, {"video": {"url": "https://v3.fal.media/x.mp4"}}),
        ]
    )
    provider = FalVideoProvider(
        _cfg(),
        client=c,
        download=lambda _u, d: d,
        resolve_keyframe=lambda _p: "https://example.com/k.jpg",
    )
    provider.generate(
        VideoRequest(keyframe=tmp_path / "k.jpg", prompt="p", duration_s=4, seed=1, ref="t"),
        tmp_path / "o.mp4",
    )
    _u, _m, body, _h = c.transport.calls[0]  # type: ignore[attr-defined]
    assert body is not None
    assert body["auto_fix"] is False
    assert body["safety_tolerance"] == "4", "provider default, stated explicitly"


def test_a_locked_balance_is_never_billable_even_while_polling():
    """403 says the account cannot run work, not that work ran.

    ADR 0006 classifies a 4xx by WHEN it arrives: free on submit, billable
    afterwards, because a late 4xx implies a runner had already started. That
    is too coarse for 403. Measured 2026-09-25: three "User is locked. Reason:
    TOP_UP" answers arrived while polling and were charged $1.80 for clips
    that never existed.
    """
    import pytest

    from scripts.spike.errors import ProviderRefused
    from scripts.spike.fal import FalClient, QueuedRequest

    def locked(url, method, payload, headers):
        return 403, b'{"detail": "User is locked. Reason: TOP_UP."}'

    client = FalClient(api_key="k", transport=locked)
    queued = QueuedRequest(
        request_id="r",
        status_url="https://queue.fal.run/m/requests/r/status",
        response_url="https://queue.fal.run/m/requests/r",
        cancel_url="",
    )
    with pytest.raises(ProviderRefused) as exc:
        client.result(queued)
    assert exc.value.billable is False
