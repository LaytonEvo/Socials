"""Task 3.11 — the signed provenance record.

Most of this needs neither the C2PA library nor a certificate: the manifest shape is pure
data and the two construction guards are type-system work. The one test that really signs
a file is skipped unless the library and `openssl` are both present, because signing is an
optional extra and `make check` must not need a certificate to pass.

Amendment A9 is the frame for all of it: the manifest is provenance for us, not a
disclosure signal the audience sees, and a self-signed chain verifies as *valid* and never
as *trusted*.
"""

from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.compliance.c2pa import (
    TRAINED_ALGORITHMIC_MEDIA,
    SignedRender,
    SigningCredentials,
    SigningFailed,
    build_manifest,
    credentials,
)
from app.config import load_all
from app.pipeline.disclosure import apply_disclosure

REPO = Path(__file__).resolve().parent.parent.parent
OVERLAY = load_all(REPO / "config").persona.persona.disclosure.overlay

needs_signing = pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("c2pa") is None
    or shutil.which("openssl") is None
    or shutil.which("ffmpeg") is None,
    reason="c2pa, openssl or ffmpeg not available",
)


def manifest(**kwargs: object) -> dict:  # type: ignore[type-arg]
    base = {"title": "t", "generator": "persona-studio", "generator_version": "0.1.0"}
    return build_manifest(**{**base, **kwargs})  # type: ignore[arg-type]


# ------------------------------------------------------------------ manifest --
def test_the_manifest_always_declares_ai_generation() -> None:
    """CLAUDE.md forbids a code path that skips the disclosure. A manifest that omitted
    the source type would be exactly that with extra steps, so there is no parameter for
    it and this test is what keeps it that way."""
    actions = manifest()["assertions"][0]["data"]["actions"]
    assert actions[0]["action"] == "c2pa.created"
    assert actions[0]["digitalSourceType"] == TRAINED_ALGORITHMIC_MEDIA
    assert "trainedAlgorithmicMedia" in TRAINED_ALGORITHMIC_MEDIA


def test_training_and_mining_are_refused() -> None:
    """Her likeness is the asset; the same position we take on our own inputs."""
    entries = next(a for a in manifest()["assertions"] if "training-mining" in a["label"])
    assert entries["data"]["entries"]["cawg.ai_generative_training"]["use"] == "notAllowed"
    assert entries["data"]["entries"]["cawg.ai_inference"]["use"] == "notAllowed"


def test_the_creation_time_is_recorded_and_can_be_pinned() -> None:
    when = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)
    actions = manifest(created=when)["assertions"][0]["data"]["actions"]
    assert actions[0]["when"] == when.isoformat()


def test_the_stages_that_made_it_are_named_when_given() -> None:
    work = next(
        a
        for a in manifest(persona_name="Mollie", ingredients=["a-model", "b-model"])["assertions"]
        if "CreativeWork" in a["label"]
    )
    assert work["data"]["character"] == "Mollie"
    assert work["data"]["contributor"] == ["a-model", "b-model"]


def test_no_creative_work_assertion_when_there_is_nothing_to_say() -> None:
    assert not [a for a in manifest()["assertions"] if "CreativeWork" in a["label"]]


# --------------------------------------------------------------- credentials --
def test_missing_credentials_name_both_variables_and_the_way_out() -> None:
    with pytest.raises(SigningFailed, match="C2PA_SIGN_CERT and C2PA_SIGN_KEY"):
        credentials(cert=None, key=None)


def test_pem_text_is_accepted_inline() -> None:
    creds = credentials(
        cert="-----BEGIN CERTIFICATE-----\nx\n", key="-----BEGIN PRIVATE KEY-----\ny\n"
    )
    assert creds.cert_chain_pem.startswith(b"-----BEGIN CERTIFICATE")
    assert creds.is_self_signed is True


def test_a_path_that_is_neither_pem_nor_a_file_is_refused() -> None:
    with pytest.raises(SigningFailed, match="neither PEM text nor a readable file"):
        credentials(cert="/no/such/cert.pem", key="-----BEGIN PRIVATE KEY-----\n")


def test_a_self_signed_chain_never_claims_to_be_trusted() -> None:
    """Valid and trusted are different things, and only one of them is ours today."""
    assert SigningCredentials(b"c", b"k").trusted_chain is False
    assert SigningCredentials(b"c", b"k", trusted_chain=True).is_self_signed is False


# --------------------------------------------------------------- the guards --
def test_a_signed_render_cannot_be_conjured() -> None:
    """Same reason FinalRender cannot: holding one is supposed to be the evidence."""
    with pytest.raises(SigningFailed, match="cannot be constructed directly"):
        SignedRender(path=Path("x.mp4"), manifest={}, trusted_chain=False)


def test_sign_only_accepts_a_disclosed_render() -> None:
    """Not a runtime check — `sign` takes a FinalRender and only `apply_disclosure` can
    make one, so 'disclosure before signing' is a property of the types."""
    import inspect

    from app.compliance.c2pa import sign

    assert inspect.signature(sign).parameters["render"].annotation == "FinalRender"


# -------------------------------------------------------------- end to end --
@needs_signing
def test_a_disclosed_render_signs_and_reads_back_as_valid(tmp_path: Path) -> None:
    from app.compliance.c2pa import read_manifest, sign

    subprocess.run(
        [sys.executable, "-m", "scripts.make_signing_cert", "--out", str(tmp_path / "ca")],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=240x426:rate=12:duration=1",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    render = apply_disclosure(source, tmp_path / "disclosed.mp4", overlay=OVERLAY)
    signed = sign(
        render,
        tmp_path / "signed.mp4",
        creds=credentials(
            cert=str(tmp_path / "ca" / "chain.pem"), key=str(tmp_path / "ca" / "key.pem")
        ),
        title="probe",
    )
    assert signed.trusted_chain is False, "a development chain is not trusted"
    store = read_manifest(signed.path)
    assert store["validation_state"] == "Valid"
    active = store["manifests"][store["active_manifest"]]
    assert active["title"] == "probe"
    sources = [
        action.get("digitalSourceType")
        for assertion in active["assertions"]
        if assertion["label"].startswith("c2pa.actions")
        for action in assertion["data"]["actions"]
    ]
    assert TRAINED_ALGORITHMIC_MEDIA in sources
