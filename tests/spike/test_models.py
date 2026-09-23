"""The model fetcher.

Mostly tests for downloads that look like they worked and did not. Saving an
error page as a .dat and discovering it at calibration time costs a day.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.spike.errors import SpikeError
from scripts.spike.models import (
    MODELS,
    ModelFile,
    _looks_like_a_model,
    config_snippet,
    fetch,
    sha256_of,
)

BIG = b"\x00" * 50_000


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_git_lfs_pointer_is_named_specifically(tmp_path):
    """The real failure this caught: opencv_zoo keeps .onnx files in LFS, so
    raw.githubusercontent.com serves a 131-byte stub that is a valid HTTP 200."""
    pointer = (
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4\n"
        b"size 232589\n"
    )
    complaint = _looks_like_a_model(_write(tmp_path, "m.onnx", pointer))
    assert complaint is not None
    assert "Git LFS pointer" in complaint
    assert "media.githubusercontent.com" in complaint


def test_html_error_page_is_rejected(tmp_path):
    page = b"<!DOCTYPE html>\n<html><body>404 not found</body></html>" + b" " * 50_000
    complaint = _looks_like_a_model(_write(tmp_path, "m.dat", page))
    assert complaint is not None
    assert "web page" in complaint


def test_proxy_denial_body_is_rejected(tmp_path):
    body = b"Host not in allowlist: dlib.net. Add this host to your egress settings."
    assert _looks_like_a_model(_write(tmp_path, "m.dat", body)) is not None


def test_tiny_file_is_rejected(tmp_path):
    complaint = _looks_like_a_model(_write(tmp_path, "m.dat", b"\x00" * 200))
    assert complaint is not None
    assert "error page" in complaint


def test_plausible_binary_is_accepted(tmp_path):
    assert _looks_like_a_model(_write(tmp_path, "m.dat", BIG)) is None


def test_yunet_url_does_not_use_the_lfs_stub_endpoint():
    """Regression: the obvious URL returns a pointer, not the model."""
    yunet = next(m for m in MODELS if m.key == "yunet")
    assert "raw.githubusercontent.com" not in yunet.url
    assert "media.githubusercontent.com/media/" in yunet.url
    assert yunet.sha256, "the LFS pointer gives us the digest; pin it"


def test_every_model_names_where_to_read_its_licence():
    for model in MODELS:
        assert model.licence_where.startswith("http")
        assert model.licence_note


def test_detector_licence_note_warns_it_is_separate():
    yunet = next(m for m in MODELS if m.key == "yunet")
    assert "SEPARATE licence question" in yunet.licence_note


def test_hash_mismatch_refuses_and_deletes(tmp_path, monkeypatch):
    """A changed model means a changed embedding space, so this must not pass."""
    model = ModelFile(
        key="t",
        backend="dlib",
        url="https://example.invalid/m.dat",
        filename="m.dat",
        config_key="recognition_model",
        licence_where="https://example.invalid",
        licence_note="x",
        sha256="0" * 64,
    )

    class _Response:
        def read(self) -> bytes:
            return BIG

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Response())
    with pytest.raises(SpikeError, match="sha256 mismatch"):
        fetch(model, tmp_path)
    assert not (tmp_path / "m.dat").exists()


def test_matching_hash_is_kept(tmp_path, monkeypatch):
    digest = sha256_of(_write(tmp_path, "probe.bin", BIG))
    model = ModelFile(
        key="t",
        backend="dlib",
        url="https://example.invalid/m.dat",
        filename="m.dat",
        config_key="recognition_model",
        licence_where="https://example.invalid",
        licence_note="x",
        sha256=digest,
    )

    class _Response:
        def read(self) -> bytes:
            return BIG

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Response())
    assert fetch(model, tmp_path / "out").exists()


def test_config_snippet_leaves_the_licence_blank():
    """The fetcher must never tick off the gate that exists to force a read."""
    snippet = config_snippet({m.key: Path(f"models/{m.final_name}") for m in MODELS})
    assert "licence: null" in snippet
    assert "licence_verified_on: null" in snippet
    assert "YOU fill this in" in snippet
    assert "recognition_model:" in snippet
    assert "detector_model:" in snippet


def test_densenet_is_an_alternative_not_an_addition():
    """Both dlib descriptors fill the same config slot.

    Fetching both by default would leave you with two files for one setting and
    no way to tell which the config meant.
    """
    densenet = next(m for m in MODELS if m.key == "dlib-densenet")
    resnet = next(m for m in MODELS if m.key == "dlib-recognition")
    assert densenet.config_key == resnet.config_key
    assert densenet.optional is True
    assert resnet.optional is False


def test_densenet_note_records_that_the_public_domain_statement_misses_it():
    """The dlib-models statement is scoped to its author's own models; the
    densenet is a third-party contribution, so it is not covered by it."""
    densenet = next(m for m in MODELS if m.key == "dlib-densenet")
    assert "does NOT cover it" in densenet.licence_note
    assert "BAREL" in densenet.licence_note
    assert densenet.licence_where == "https://github.com/Cydral/BAREL"


def test_clashing_slots_are_flagged_in_the_snippet():
    from scripts.spike.models import clashing_slots

    fetched = {m.key: Path(f"models/{m.final_name}") for m in MODELS}
    assert "dlib.recognition_model" in clashing_slots(fetched)
    snippet = config_snippet(fetched)
    assert "alternatives" in snippet
    assert "delete the other line" in snippet


def test_write_paths_fills_paths_only(tmp_path):
    """The licence gate must survive automation.

    A path is mechanical — it says where a file landed. A licence is a decision
    about whether the terms are acceptable. Writing both from a fetcher would
    quietly tick off the one that matters.
    """
    from scripts.spike.models import write_paths

    cfg = tmp_path / "spike.yaml"
    cfg.write_text(
        "embedder:\n"
        "  backends:\n"
        "    dinov2:\n"
        "      detector_model: null\n"
        "      licence: null\n"
        "      licence_verified_on: null\n"
    )
    written = write_paths(cfg, {"yunet": Path("models/yunet.onnx")})

    text = cfg.read_text()
    assert "detector_model: models/yunet.onnx" in text
    assert "licence: null" in text
    assert "licence_verified_on: null" in text
    assert written == ["detector_model -> models/yunet.onnx"]


def test_write_paths_leaves_an_already_set_path_alone(tmp_path):
    from scripts.spike.models import write_paths

    cfg = tmp_path / "spike.yaml"
    cfg.write_text("      detector_model: models/existing.onnx\n")
    assert write_paths(cfg, {"yunet": Path("models/new.onnx")}) == []
    assert "models/existing.onnx" in cfg.read_text()


def test_write_paths_preserves_indentation(tmp_path):
    from scripts.spike.models import write_paths

    cfg = tmp_path / "spike.yaml"
    cfg.write_text("embedder:\n  backends:\n    dinov2:\n      detector_model: null\n")
    write_paths(cfg, {"yunet": Path("m/y.onnx")})
    assert "      detector_model: m/y.onnx" in cfg.read_text()
