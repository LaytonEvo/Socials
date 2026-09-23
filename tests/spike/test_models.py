"""The model fetcher.

Mostly tests for downloads that look like they worked and did not. Saving an
error page as a .dat and discovering it at calibration time costs a day.
"""

from __future__ import annotations

import dataclasses
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


def test_no_two_models_contend_for_one_slot():
    """Every (backend, slot) pair is claimed by exactly one file.

    The dlib variants used to share a backend, which meant fetching both left
    two files for one setting. They are separate backends now, so nothing
    contends — and this asserts that stays true as models are added.
    """
    from scripts.spike.models import clashing_slots

    assert clashing_slots({m.key: Path(m.final_name) for m in MODELS}) == []


def test_densenet_licence_and_provenance_are_recorded_in_config():
    """The densenet is shipped rather than fetched — its URL was inferred and
    404'd — so its licence and origin live in config, not in MODELS."""
    text = Path("config/spike.yaml").read_text()
    block = text[text.index("dlib-densenet:") : text.index("dinov2:")]
    assert "MIT" in block
    assert "BAREL" in block
    assert "NOT on dlib.net" in block
    assert "spike/models/face_recognition_densenet_model_v1.dat" in block


def test_a_contended_slot_would_be_flagged(monkeypatch):
    """The guard must still bite if two files are ever pointed at one slot."""
    import scripts.spike.models as mod

    a, b = MODELS[0], MODELS[1]
    twins = (a, dataclasses.replace(b, key="twin", backend=a.backend, config_key=a.config_key))
    monkeypatch.setattr(mod, "MODELS", twins)
    clashes = mod.clashing_slots({"twin": Path("x"), a.key: Path("y")})
    assert clashes == [f"{a.backend}.{a.config_key}"]
    assert "alternatives" in mod.config_snippet({"twin": Path("x"), a.key: Path("y")})


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
    assert written == ["dinov2.detector_model -> models/yunet.onnx"]


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


def test_the_two_dlib_variants_are_separate_backends():
    """They were one backend with two alternative files, which meant they
    could be swapped but never compared. The ResNet's licence carries a
    training-data caveat the DenseNet's does not, so measuring one against
    the other is the whole point."""
    from scripts.spike.config import load_config

    cfg = load_config()
    resnet = cfg.embedder_for("dlib")
    densenet = cfg.embedder_for("dlib-densenet")
    assert resnet.backend != densenet.backend
    assert resnet.options["recognition_model"] != densenet.options["recognition_model"]
    assert resnet.licence != densenet.licence


def test_write_paths_does_not_cross_backend_blocks(tmp_path):
    """Regression risk introduced by the split: both dlib backends have a
    `recognition_model:` line, and a flat scan would write one path into
    whichever block it reached first."""
    from scripts.spike.models import write_paths

    cfg = tmp_path / "spike.yaml"
    cfg.write_text(
        "embedder:\n"
        "  backends:\n"
        "    dlib:\n"
        "      shape_predictor: null\n"
        "    dlib-densenet:\n"
        "      shape_predictor: null\n"
    )
    write_paths(
        cfg,
        {
            "dlib-landmarks": Path("models/resnet-lm.dat"),
            "dlib-densenet-landmarks": Path("models/densenet-lm.dat"),
        },
    )
    text = cfg.read_text()
    densenet_block = text.index("dlib-densenet:")
    assert text.index("models/resnet-lm.dat") < densenet_block
    assert text.index("models/densenet-lm.dat") > densenet_block


def test_all_three_backends_are_registered():
    import scripts.spike.embedders  # noqa: F401 — importing is what registers them
    from scripts.spike.embed import _REGISTRY

    assert {"dlib", "dlib-densenet", "dinov2"} <= set(_REGISTRY)


def test_backend_choices_are_derived_not_listed():
    """Regression: --backend carried a hardcoded ["dlib", "dinov2"], so adding
    a third backend everywhere else left the CLI refusing it. Anything in
    MODELS must be selectable without a second edit."""
    import argparse
    import contextlib
    import io

    from scripts.spike.cli import build_parser

    parser = build_parser()
    for backend in {m.backend for m in MODELS}:
        args = parser.parse_args(["fetch-models", "--backend", backend])
        assert args.backend == backend

    with contextlib.redirect_stderr(io.StringIO()), pytest.raises(SystemExit):
        parser.parse_args(["fetch-models", "--backend", "not-a-backend"])
    assert argparse  # keep the import meaningful


def test_detector_choices_are_derived_not_listed():
    from scripts.spike.cli import build_parser
    from scripts.spike.embedders import DETECTORS

    parser = build_parser()
    for detector in DETECTORS:
        args = parser.parse_args(["check-embedder", "--detector", detector])
        assert args.detector == detector
