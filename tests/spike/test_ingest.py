"""Validating candidate stills before they become a calibration set.

The failure this prevents is not a crash but something worse: a confident
threshold computed from three usable images, arriving in a Gate A report
looking like a finding about the persona rather than a problem with the input.
"""

from __future__ import annotations

from pathlib import Path

from scripts.spike.embed import MULTI_FACE, NO_FACE, StubEmbedder
from scripts.spike.ingest import (
    MIN_EDGE_PX,
    RECOMMENDED_MASTER,
    find_images,
    format_report,
    ingest,
    inspect,
)
from scripts.spike.providers import render_fake_face


def _make(dest: Path, name: str, identity: str = "look-a", size: int = 256) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / name
    render_fake_face(identity).resize((size, size)).save(path)
    return path


def test_a_good_image_is_accepted(tmp_path):
    c = inspect(_make(tmp_path, "a.png"), StubEmbedder())
    assert c.usable
    assert "256x256" in c.detail


def test_an_image_with_no_face_is_rejected(tmp_path):
    c = inspect(_make(tmp_path, "b__noface.png"), StubEmbedder())
    assert c.status == "no_face"
    assert not c.usable


def test_an_image_with_several_faces_is_rejected(tmp_path):
    """Two people in a still makes it ambiguous which one the persona is."""
    c = inspect(_make(tmp_path, "c__multiface.png"), StubEmbedder())
    assert c.status == "multi_face"


def test_a_small_image_is_rejected(tmp_path):
    c = inspect(_make(tmp_path, "d.png", size=MIN_EDGE_PX - 1), StubEmbedder())
    assert c.status == "too_small"


def test_a_corrupt_file_is_reported_not_raised(tmp_path):
    """A junk file in the folder must not take the whole command down."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    bad = tmp_path / "e.png"
    bad.write_bytes(b"not an image")
    c = inspect(bad, StubEmbedder())
    assert c.status == "unreadable"
    assert "UnidentifiedImageError" in c.detail


def test_only_usable_images_are_copied(tmp_path):
    src = tmp_path / "src"
    for i in range(3):
        _make(src, f"ok_{i}.png")
    _make(src, "bad__noface.png")
    _make(src, "small.png", size=64)

    report = ingest(src, tmp_path / "run" / "master", "master", StubEmbedder())
    assert len(report.usable) == 3
    assert len(report.copied) == 3
    assert sorted(p.name for p in report.copied) == [
        "master_000.png",
        "master_001.png",
        "master_002.png",
    ]


def test_dry_run_copies_nothing(tmp_path):
    src = tmp_path / "src"
    _make(src, "ok.png")
    dest = tmp_path / "run" / "master"
    report = ingest(src, dest, "master", StubEmbedder(), copy=False)
    assert report.usable
    assert report.copied == []
    assert not dest.exists()


def test_non_images_are_ignored_entirely(tmp_path):
    src = tmp_path / "src"
    _make(src, "ok.png")
    (src / "notes.txt").write_text("hello")
    (src / ".DS_Store").write_bytes(b"\x00")
    assert [p.name for p in find_images(src)] == ["ok.png"]


def test_a_thin_set_is_called_out(tmp_path):
    src = tmp_path / "src"
    for i in range(3):
        _make(src, f"ok_{i}.png")
    report = ingest(src, tmp_path / "d", "master", StubEmbedder(), copy=False)
    assert not report.enough
    text = format_report(report, tmp_path / "d")
    assert "THIN" in text
    assert str(RECOMMENDED_MASTER) in text


def test_a_full_set_reads_as_ready(tmp_path):
    src = tmp_path / "src"
    for i in range(RECOMMENDED_MASTER):
        _make(src, f"ok_{i}.png")
    report = ingest(src, tmp_path / "d", "master", StubEmbedder(), copy=False)
    assert report.enough
    assert "READY" in format_report(report, tmp_path / "d")


def test_nothing_usable_says_what_to_check(tmp_path):
    src = tmp_path / "src"
    for i in range(4):
        _make(src, f"x_{i}__noface.png")
    report = ingest(src, tmp_path / "d", "master", StubEmbedder(), copy=False)
    text = format_report(report, tmp_path / "d")
    assert "NOTHING USABLE" in text
    assert "detector_model" in text  # the likeliest cause, named


def test_report_counts_every_rejection_reason(tmp_path):
    src = tmp_path / "src"
    _make(src, "ok.png")
    _make(src, "a__noface.png")
    _make(src, "b__multiface.png")
    _make(src, "c.png", size=32)
    report = ingest(src, tmp_path / "d", "master", StubEmbedder(), copy=False)
    assert report.count(NO_FACE) == 1
    assert report.count(MULTI_FACE) == 1
    assert report.count("too_small") == 1
    text = format_report(report, tmp_path / "d")
    for reason in ("no face detected", "more than one face", "too small"):
        assert reason in text
