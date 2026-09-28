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


def test_pin_audio_is_parsed_and_defaults_to_off():
    """Off unless asked: pinning a soundtrack changes what every clip costs."""
    parser = build_parser()
    assert parser.parse_args(["battery", "--budget", "1"]).pin_audio is None
    args = parser.parse_args(["battery", "--budget", "1", "--pin-audio", "one more club"])
    assert args.pin_audio == "one more club"


def test_a_slot_declares_where_its_pinned_audio_goes():
    """The field name is a property of the model, so it lives with the model.

    h3-max calls it target_audio_url. Another model will call it something
    else, and the answer to that is a line of config, not a patch to the
    adapter.
    """
    from scripts.spike.config import load_config

    cfg = load_config("config/spike.yaml")
    assert cfg.provider("video", "alt_h3max_turbo").request["audio_field"] == "target_audio_url"
    # veo3.1 takes no pinned audio, and must not silently pretend to.
    assert "audio_field" not in cfg.provider("video", "fast").request


def test_say_and_pin_audio_are_separate_levers():
    """They do different things and must not be confused.

    --say asks the model to speak the line itself, which its own lip sync
    follows. --pin-audio replaces the soundtrack after generation, which the
    mouth ignores. Answering ADR 0005 needs the first, not the second.
    """
    parser = build_parser()
    args = parser.parse_args(
        ["battery", "--budget", "1", "--say", "one more club", "--pin-audio", "other"]
    )
    assert args.say == "one more club"
    assert args.pin_audio == "other"
    assert parser.parse_args(["battery", "--budget", "1"]).say is None
