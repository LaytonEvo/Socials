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


def test_dlib_is_blocked_on_its_model_files_not_its_licence(cfg):
    """dlib's licence was recorded 2026-09-23 so the bake-off could run.

    Like DINOv2, it must now fail on the missing weights rather than on the
    licence — if it still failed on the licence, the record did not take.
    """
    import scripts.spike.embedders as mod

    cfg.embedder_for("dlib").require_usable()  # licence gate: passes
    with pytest.raises(EmbedderNotConfigured, match="recognition_model"):
        mod._build_dlib(cfg.embedder_for("dlib"))


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


def test_detectors_are_available_by_name():
    assert set(DETECTORS) == {"yunet", "dlib-hog", "whole-image"}


def test_whole_image_detector_needs_no_model_and_no_licence():
    """It exists so the self-check can exercise the model without dragging
    detection into the same test. No weights, so no licence question."""
    from PIL import Image

    from scripts.spike.embedders import FaceBox, build_detector

    detector = build_detector({"detector": "whole-image"}, "dinov2")
    assert detector.detect(Image.new("RGB", (120, 80))) == [FaceBox(0, 0, 120, 80)]
    assert "no model" in detector.licence


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
    out = capsys.readouterr().out
    assert "dlib" in out and "dinov2" in out
    assert "DID NOT RUN" in out


# --- contact sheet legibility ---------------------------------------------


def _scored(label: str, *, no_face: int = 0, multi_face: int = 0):
    from scripts.spike.score import ClipScore

    return ClipScore(
        ref=label,
        label=label,
        embedder_key="k",
        threshold=0.9,
        min_face_presence=0.9,
        frames_sampled=10,
        frames_usable=10 - no_face,
        no_face_frames=no_face,
        multi_face_frames=multi_face,
        identity_score_min=0.95,
        identity_score_mean=0.97,
        max_similarity_any_master=0.97,
        worst_frame_source=None,
    )


def test_caption_drops_the_prefix_every_tile_shares():
    """Printing `matrix-011-` on every tile spends a third of the caption
    saying nothing, and truncates away the condition, which is the only part
    a reviewer is looking for."""
    from scripts.spike.contactsheet import caption_for

    assert (
        caption_for(_scored("matrix-011-profile-wide-overcast-turning"))
        == "profile-wide-overcast-turning"
    )


def test_caption_leaves_other_labels_alone():
    from scripts.spike.contactsheet import caption_for

    label = "battery-full_swing_impact-flagship-0"
    assert caption_for(_scored(label)) == label


def test_label_and_face_lost_flag_do_not_collide(tmp_path):
    """Regression: a fixed-width label ran into the flag on exactly the clips
    that most needed reading — the ones where the face disappeared."""
    from PIL import Image, ImageDraw

    from scripts.spike.contactsheet import FLAG_W, TILE, _fit, caption_for

    draw = ImageDraw.Draw(Image.new("RGB", (TILE, TILE)))
    score = _scored("matrix-011-profile-wide-overcast-turning", no_face=2)
    room = TILE - 12 - FLAG_W
    fitted = _fit(caption_for(score), room, draw)
    assert draw.textlength(fitted) <= room


def test_long_labels_are_trimmed_with_an_ellipsis(tmp_path):
    from PIL import Image, ImageDraw

    from scripts.spike.contactsheet import _fit

    draw = ImageDraw.Draw(Image.new("RGB", (200, 200)))
    out = _fit("x" * 200, 100, draw)
    assert out.endswith("…")
    assert draw.textlength(out) <= 100


def test_short_labels_are_left_intact():
    from PIL import Image, ImageDraw

    from scripts.spike.contactsheet import _fit

    draw = ImageDraw.Draw(Image.new("RGB", (200, 200)))
    assert _fit("short", 180, draw) == "short"


# --- calibrating on images the detector cannot read ------------------------


def test_calibration_refuses_a_master_set_with_no_detectable_faces():
    """Regression, found by CI rather than locally.

    A fully configured DINOv2 pointed at the synthetic fixtures produced zero
    usable embeddings — YuNet correctly finds no face in a coloured shape — and
    the bake-off died on a ValueError traceback from deep inside calibrate(),
    saying nothing about the actual problem. It must say what is wrong with the
    images instead.
    """
    from scripts.spike.cli import _require_usable_embeddings
    from scripts.spike.embed import NO_FACE, EmbedderInfo, EmbeddingSet, FrameEmbedding
    from scripts.spike.errors import SpikeError

    info = EmbedderInfo("dinov2", "m", "1", 768)
    blind = EmbeddingSet([FrameEmbedding(i, 0.0, NO_FACE, faces=0) for i in range(6)], info)

    with pytest.raises(SpikeError) as excinfo:
        _require_usable_embeddings(blind, "master", "dinov2")
    message = str(excinfo.value)
    assert "no usable embeddings from the master set" in message
    assert "6 images, 6 had no face" in message.replace("Of ", "")
    assert "whole-image" in message  # tells you how to test the model anyway


def test_calibration_accepts_a_set_with_usable_embeddings():
    import numpy as np

    from scripts.spike.cli import _require_usable_embeddings
    from scripts.spike.embed import EmbedderInfo, EmbeddingSet, FrameEmbedding, l2_normalise

    info = EmbedderInfo("dinov2", "m", "1", 768)
    vec = l2_normalise(np.ones(768, dtype=np.float32))
    ok = EmbeddingSet([FrameEmbedding(0, 0.0, "ok", faces=1, vector=vec)], info)
    _require_usable_embeddings(ok, "master", "dinov2")  # must not raise


def test_bake_off_reports_failures_in_the_table_not_to_stderr(tmp_path, capsys):
    """A candidate that could not run is a result of the bake-off.

    "dlib-densenet is unusable as configured" is exactly what you came to find
    out, and on a CI runner stderr is buried under pages of unrelated library
    warnings — so the reason has to reach stdout.
    """
    from scripts.spike.cli import main

    cfg_path = tmp_path / "spike.yaml"
    cfg_path.write_text(
        Path("config/spike.yaml")
        .read_text()
        .replace("run_root: spike/runs", f"run_root: {tmp_path / 'runs'}")
    )
    main(["--config", str(cfg_path), "init-run"])
    main(["--config", str(cfg_path), "make-fixtures"])
    capsys.readouterr()

    main(["--config", str(cfg_path), "bake-off", "--backends", "dlib", "stub"])
    out = capsys.readouterr().out
    assert "DID NOT RUN" in out
    assert "Why they did not run" in out
    assert "recognition_model" in out  # the actual reason, on stdout


def test_dlib_errors_name_the_backend_being_configured(cfg):
    """Regression: _build_dlib is registered under two names and hardcoded
    "dlib" in its error messages, so anyone configuring the DenseNet was sent
    to the wrong config block."""
    import scripts.spike.embedders as mod

    for backend, missing in (("dlib", "recognition_model"), ("dlib-densenet", "shape_predictor")):
        with pytest.raises(EmbedderNotConfigured) as excinfo:
            mod._build_dlib(cfg.embedder_for(backend))
        assert f"embedder.backends.{backend}.{missing}" in str(excinfo.value)


def test_one_broken_backend_does_not_cost_the_whole_bake_off(tmp_path, capsys, monkeypatch):
    """Regression: dlib raised a RuntimeError on incompatible weights and took
    the entire bake-off down, destroying the results of candidates that had
    already run. Only SpikeError was caught."""
    import scripts.spike.cli as cli
    from scripts.spike.cli import main

    cfg_path = tmp_path / "spike.yaml"
    cfg_path.write_text(
        Path("config/spike.yaml")
        .read_text()
        .replace("run_root: spike/runs", f"run_root: {tmp_path / 'runs'}")
    )
    main(["--config", str(cfg_path), "init-run"])
    main(["--config", str(cfg_path), "make-fixtures"])

    real = cli._calibrate_with

    def explode(cfg, run_dir, backend, target_fpr):
        if backend == "stub":
            return real(cfg, run_dir, backend, target_fpr)
        raise RuntimeError("Unexpected version found while deserializing")

    monkeypatch.setattr(cli, "_calibrate_with", explode)
    capsys.readouterr()

    main(["--config", str(cfg_path), "bake-off", "--backends", "stub", "dlib"])
    out = capsys.readouterr().out
    assert "stub" in out and "EXCELLENT" in out  # the working one survived
    assert "DID NOT RUN" in out
    assert "RuntimeError" in out  # named, not swallowed
