"""The ADR 0002 candidate backends.

dlib and torch were not installable in the environment this was written in, so
what is tested here is everything around the model call: the licence and path
gates, the detection contract both backends must honour, the crop geometry, and
the bake-off's refusal to let a stub win. The model calls themselves are
unverified — see docs/decisions/0002.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from scripts.spike.cli import main
from scripts.spike.embed import MULTI_FACE, NO_FACE, load_embedder
from scripts.spike.embedders import (
    DETECTORS,
    FaceBox,
    build_detector,
    crop_with_margin,
    detection_outcome,
)
from scripts.spike.errors import EmbedderNotConfigured


def test_both_candidates_are_registered(cfg):
    """`load_embedder` must reach them, or the bake-off cannot run at all."""
    for backend in ("dlib", "dinov2"):
        with pytest.raises(EmbedderNotConfigured):
            load_embedder(cfg.embedder_for(backend))  # blocked on licence, not on lookup


def test_dlib_is_still_blocked_until_its_licence_is_recorded(cfg):
    """DINOv2 was chosen (ADR 0002); dlib remains the unrecorded fallback."""
    with pytest.raises(EmbedderNotConfigured, match="licence"):
        cfg.embedder_for("dlib").require_usable()


def test_chosen_backend_is_blocked_on_its_model_path_not_its_licence(cfg):
    """The licence question is closed; the remaining gate is a machine to run on.

    DINOv2 must fail on the missing detector file, NOT on the licence -- if it
    still failed on the licence, the decision was not really recorded.
    """
    import scripts.spike.embedders as mod

    cfg.embedder_for("dinov2").require_usable()  # licence gate: passes
    with pytest.raises(EmbedderNotConfigured, match="detector_model"):
        mod._build_dinov2(cfg.embedder_for("dinov2"))


def test_each_candidate_declares_its_own_dimension(cfg):
    """A threshold is valid for one model at one dimension (amendment A3)."""
    assert cfg.embedder_for("dlib").dim == 128
    assert cfg.embedder_for("dinov2").dim == 768


def test_missing_model_path_explains_that_weights_are_a_licence_decision(cfg, monkeypatch):
    import dataclasses

    import scripts.spike.embedders as mod

    usable = dataclasses.replace(
        cfg.embedder_for("dlib"), licence="public domain", licence_verified_on=None
    )
    with pytest.raises(EmbedderNotConfigured, match="never downloads weights"):
        mod._build_dlib(usable)


def test_detector_choice_is_validated(cfg):
    with pytest.raises(EmbedderNotConfigured, match="Unknown detector"):
        build_detector({"detector": "nope"}, "dinov2")


def test_yunet_needs_its_model_file():
    """Detection is its own licence question; the file is not bundled."""
    with pytest.raises(EmbedderNotConfigured, match="detector_model"):
        build_detector({"detector": "yunet"}, "dinov2")


def test_both_detectors_are_available_by_name():
    assert set(DETECTORS) == {"yunet", "dlib-hog"}


# --- the contract both backends share -------------------------------------


def test_no_faces_is_reported_not_skipped():
    fe = detection_outcome([], Path("f.png"))
    assert fe is not None
    assert fe.status == NO_FACE
    assert fe.faces == 0
    assert fe.usable is False


def test_multiple_faces_is_reported_not_resolved():
    """A backend that quietly picked the biggest of two faces would break the
    face-presence rule in score.py, which counts on the exception surfacing."""
    fe = detection_outcome([FaceBox(0, 0, 10, 10), FaceBox(20, 20, 40, 40)], Path("f.png"))
    assert fe is not None
    assert fe.status == MULTI_FACE
    assert fe.faces == 2


def test_exactly_one_face_falls_through_to_embedding():
    assert detection_outcome([FaceBox(0, 0, 10, 10)], Path("f.png")) is None


# --- crop geometry ---------------------------------------------------------


def test_crop_expands_by_margin():
    img = Image.new("RGB", (200, 200))
    out = crop_with_margin(img, FaceBox(50, 50, 150, 150), margin=0.25)
    assert out.size == (150, 150)  # 100px box + 25% each side


def test_crop_clamps_at_the_image_edge():
    img = Image.new("RGB", (100, 100))
    out = crop_with_margin(img, FaceBox(0, 0, 100, 100), margin=0.5)
    assert out.size == (100, 100)


def test_zero_margin_is_the_bare_box():
    img = Image.new("RGB", (200, 200))
    assert crop_with_margin(img, FaceBox(10, 20, 60, 90), margin=0.0).size == (50, 70)


def test_degenerate_box_returns_the_whole_image():
    img = Image.new("RGB", (50, 50))
    assert crop_with_margin(img, FaceBox(30, 30, 10, 10), margin=0.0).size == (50, 50)


# --- bake-off integrity ----------------------------------------------------


def test_bake_off_refuses_to_let_a_stub_win(tmp_path, capsys):
    """The worst failure this command could have.

    A stub posts a perfect score on fixtures it was never going to fail. If it
    could win, someone would read the table and close ADR 0002 on it.
    """
    cfg_path = tmp_path / "spike.yaml"
    cfg_path.write_text(
        Path("config/spike.yaml")
        .read_text()
        .replace("run_root: spike/runs", f"run_root: {tmp_path / 'runs'}")
    )
    assert main(["--config", str(cfg_path), "init-run"]) == 0
    assert main(["--config", str(cfg_path), "make-fixtures"]) == 0

    exit_code = main(["--config", str(cfg_path), "bake-off", "--backends", "stub"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "STUB - not a candidate" in out
    assert "never a candidate" in out
    assert "separates best" not in out


def test_bake_off_reports_unconfigured_candidates_without_crashing(tmp_path, capsys):
    cfg_path = tmp_path / "spike.yaml"
    cfg_path.write_text(
        Path("config/spike.yaml")
        .read_text()
        .replace("run_root: spike/runs", f"run_root: {tmp_path / 'runs'}")
    )
    main(["--config", str(cfg_path), "init-run"])
    main(["--config", str(cfg_path), "make-fixtures"])

    assert main(["--config", str(cfg_path), "bake-off", "--backends", "dlib", "dinov2"]) == 2
    err = capsys.readouterr().err
    assert "dlib" in err and "dinov2" in err
