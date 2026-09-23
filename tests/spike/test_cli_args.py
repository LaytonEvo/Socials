"""Argument parsing — the surface CI and humans actually type at."""

from __future__ import annotations

from scripts.spike.cli import build_parser


def test_backend_is_accepted_as_an_alias_for_embedder():
    """bake-off takes --backends, everything else took --embedder.

    A CI step that reached for the wrong spelling died with "unrecognized
    arguments" instead of doing the obvious thing. One concept, either name.
    """
    parser = build_parser()
    assert parser.parse_args(["check-embedder", "--embedder", "dlib"]).embedder == "dlib"
    assert parser.parse_args(["check-embedder", "--backend", "dlib"]).embedder == "dlib"
    assert parser.parse_args(["calibrate", "--backend", "dinov2"]).embedder == "dinov2"
