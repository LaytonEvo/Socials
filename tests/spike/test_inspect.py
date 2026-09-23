"""Per-image inspection of a calibration.

Its job is to answer a question an aggregate cannot: is this separation real,
or an artefact of how the two sets were built? It answers it by finding the
closest call in each direction and telling you to go and look at them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from scripts.spike.embed import NO_FACE, EmbedderInfo, FrameEmbedding, StubEmbedder
from scripts.spike.inspect import ImageScore, SetInspection, format_inspection, inspect_sets
from tests.spike.conftest import make_stills


def _inspection(master: list[float], control: list[float]) -> SetInspection:
    return SetInspection(
        master=[ImageScore(Path(f"m{i}.png"), s, "ok") for i, s in enumerate(master)],
        control=[ImageScore(Path(f"c{i}.png"), s, "ok") for i, s in enumerate(control)],
        embedder_key="test:m:1:d128",
    )


def test_margin_is_the_gap_between_the_two_closest_calls():
    """Not the gap between the means. A separation is only as good as its
    worst case in each direction."""
    ins = _inspection(master=[0.99, 0.91, 0.95], control=[0.40, 0.72, 0.33])
    assert ins.weakest_master is not None and ins.weakest_master.similarity == 0.91
    assert ins.closest_control is not None and ins.closest_control.similarity == 0.72
    assert ins.margin == 0.91 - 0.72


def test_crossing_distributions_are_called_out():
    ins = _inspection(master=[0.99, 0.60], control=[0.40, 0.75])
    assert ins.margin is not None and ins.margin < 0
    assert "THEY CROSS" in format_inspection(ins)


def test_a_narrow_margin_is_distinguished_from_a_clear_one():
    narrow = format_inspection(_inspection([0.95, 0.90], [0.88, 0.40]))
    clear = format_inspection(_inspection([0.95, 0.90], [0.40, 0.30]))
    assert "Narrow" in narrow
    assert "Clear gap" in clear
    assert "check you agree" in clear


def test_the_two_decisive_images_are_named():
    """The whole point is that you go and open these two files."""
    text = format_inspection(_inspection([0.99, 0.91], [0.72, 0.40]))
    assert "her weakest" in text
    assert "closest other" in text
    assert "m1.png" in text  # the 0.91
    assert "c0.png" in text  # the 0.72


def test_unembeddable_images_are_listed_not_dropped():
    ins = SetInspection(
        master=[ImageScore(Path("a.png"), 0.9, "ok"), ImageScore(Path("b.png"), None, NO_FACE)],
        control=[ImageScore(Path("c.png"), 0.3, "ok")],
        embedder_key="k",
    )
    text = format_inspection(ins)
    assert "produced no embedding" in text
    assert "b.png" in text


def test_inspect_sets_scores_against_the_master_centroid(tmp_path):
    master = make_stills(tmp_path / "m", "look-a", 6, "m")
    control = make_stills(tmp_path / "c", "look-b", 4, "c")
    ins = inspect_sets(StubEmbedder(), master, control)

    assert len(ins.scored_master) == 6
    assert len(ins.scored_control) == 4
    # Her images must sit closer to her own centroid than a different look does.
    assert np.mean([s.similarity for s in ins.scored_master]) > np.mean(
        [s.similarity for s in ins.scored_control]
    )


def test_empty_master_is_refused(tmp_path):
    import pytest

    class Blind:
        info = EmbedderInfo("blind", "m", "1", 128)

        def embed_image(self, path: Path) -> FrameEmbedding:
            return FrameEmbedding(0, 0.0, NO_FACE, faces=0, source=str(path))

    master = make_stills(tmp_path / "m", "look-a", 3, "m")
    with pytest.raises(ValueError, match="no usable embeddings"):
        inspect_sets(Blind(), master, master)
