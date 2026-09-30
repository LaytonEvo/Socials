"""Task 3.8 — the edit list and the rough cut.

The type separation is the point: `assemble` returns a `RoughCut`, which nothing
downstream accepts. A caller who wants something publishable has to go through
`apply_disclosure`, and the compiler says so rather than a reviewer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.pipeline.assembler import EditList, RoughCut, assemble, duration_of, edit_list
from app.pipeline.disclosure import FinalRender
from app.pipeline.errors import AssemblyFailed

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


def _clip(dest: Path, seconds: int, colour: str) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={colour}:size=320x240:rate=12:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(dest),
        ],
        capture_output=True,
        check=True,
    )
    return dest


@pytest.fixture
def clips(tmp_path: Path) -> list[Path]:
    return [
        _clip(tmp_path / "a.mp4", 1, "red"),
        _clip(tmp_path / "b.mp4", 2, "green"),
    ]


def test_a_rough_cut_is_not_a_final_render() -> None:
    """Separate types, so one cannot be passed where the other is required."""
    assert not issubclass(RoughCut, FinalRender)
    assert not issubclass(FinalRender, RoughCut)


def test_an_empty_edit_list_is_refused() -> None:
    with pytest.raises(AssemblyFailed, match="at least one cut"):
        edit_list([])


def test_a_missing_source_is_refused(tmp_path: Path) -> None:
    """Better to fail naming the file than to render a short video nobody checks."""
    with pytest.raises(AssemblyFailed, match="cut source is missing"):
        edit_list([(tmp_path / "ghost.mp4", "gen-1", "opening")])


@needs_ffmpeg
def test_durations_are_read_from_the_file_not_assumed(clips: list[Path]) -> None:
    """Config says clips are 5s; what matters is what the file actually contains."""
    assert duration_of(clips[0]) == pytest.approx(1.0, abs=0.3)
    assert duration_of(clips[1]) == pytest.approx(2.0, abs=0.3)


@needs_ffmpeg
def test_the_edit_list_records_offsets_and_provenance(clips: list[Path]) -> None:
    """A render has to be explainable afterwards: which take, from where, at what point."""
    edl = edit_list([(clips[0], "gen-aaa", "opening"), (clips[1], "gen-bbb", "b-roll")])
    payload = edl.to_json()
    assert payload["cuts"][0]["offset_s"] == 0.0
    assert payload["cuts"][1]["offset_s"] == pytest.approx(edl.cuts[0].duration_s, abs=0.01)
    assert [c["source_id"] for c in payload["cuts"]] == ["gen-aaa", "gen-bbb"]
    assert payload["duration_s"] == pytest.approx(edl.duration_s, abs=0.01)


@needs_ffmpeg
def test_assembly_produces_one_video_of_the_combined_length(
    clips: list[Path], tmp_path: Path
) -> None:
    edl = edit_list([(clips[0], "a", "one"), (clips[1], "b", "two")])
    rough = assemble(edl, tmp_path / "rough.mp4")
    assert rough.path.is_file()
    assert duration_of(rough.path) == pytest.approx(edl.duration_s, abs=0.5)


@needs_ffmpeg
def test_the_edit_list_is_written_beside_the_render(clips: list[Path], tmp_path: Path) -> None:
    """`render.edl_json` in the database; a sidecar on disk during the spike."""
    edl = edit_list([(clips[0], "a", "one")])
    rough = assemble(edl, tmp_path / "rough.mp4")
    sidecar = rough.path.with_suffix(".edl.json")
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text())["cuts"][0]["source_id"] == "a"


def test_an_edit_list_totals_its_cuts() -> None:
    from app.pipeline.assembler import Cut

    edl = EditList(cuts=[Cut(Path("a"), "1", 2.5), Cut(Path("b"), "2", 3.25)])
    assert edl.duration_s == pytest.approx(5.75)
