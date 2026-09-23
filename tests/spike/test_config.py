"""Config validation. Every one of these is a rule from CLAUDE.md."""

from __future__ import annotations

import datetime as dt

import pytest

from scripts.spike.config import ProviderConfig
from scripts.spike.errors import (
    EmbedderNotConfigured,
    ProviderNotConfigured,
    UnverifiedPriceError,
)

TODAY = dt.date(2026, 9, 22)


def _slot(**over) -> ProviderConfig:
    base = dict(
        slot="flagship",
        kind="video",
        backend="acme",
        model="m",
        endpoint="https://example.invalid",
        price=0.4,
        price_unit="second",
        verified_on=TODAY,
    )
    base.update(over)
    return ProviderConfig(**base)  # type: ignore[arg-type]


def test_shipped_config_records_the_chosen_scorer(cfg):
    """dlib, switched 2026-09-23 after the bake-off.

    DINOv2 was chosen on 2026-09-22 and measured MARGINAL against a realistic
    control the next day; dlib measured EXCELLENT on identical data. Changing
    the scorer invalidates every stored vector and the calibrated threshold
    with it, so this assertion exists to make a silent swap loud.
    """
    assert cfg.embedder.backend == "dlib"
    chosen = cfg.embedder_for("dlib")
    chosen.require_usable()
    assert chosen.licence
    assert chosen.licence_verified_on is not None
    assert chosen.dim == 128


def test_the_losing_candidates_stay_configured(cfg):
    """Neither is deleted. DINOv2 may yet earn a place as a drift signal,
    because it notices what a face recogniser ignores; the DenseNet is the
    cleaner-licensed dlib variant and is measured against the ResNet."""
    for backend in ("dinov2", "dlib-densenet"):
        emb = cfg.embedder_for(backend)
        emb.require_usable()
        assert emb.dim


def test_every_configured_backend_has_a_recorded_licence(cfg):
    """Both candidates now carry one: DINOv2 chosen, dlib recorded for the
    bake-off. The gate is satisfied by a human having read the text, so this
    asserts the record exists rather than that the gate is shut."""
    for backend in ("dinov2", "dlib"):
        emb = cfg.embedder_for(backend)
        emb.require_usable()
        assert emb.licence, backend
        assert emb.licence_verified_on is not None, backend


def test_an_unrecorded_backend_would_still_be_blocked(cfg):
    """The gate itself must still bite. Deciding one candidate does not
    wave through a backend nobody has read the terms for."""
    import dataclasses

    unrecorded = dataclasses.replace(
        cfg.embedder_for("dlib"), licence=None, licence_verified_on=None
    )
    with pytest.raises(EmbedderNotConfigured, match="licence"):
        unrecorded.require_usable()


def test_no_shipped_slot_is_half_configured(cfg):
    """Every real slot is either an untouched placeholder or fully verified.

    This used to assert that the shipped config blocked *every* real provider,
    which was really asserting "we have not configured anything yet" -- true
    until fal was, and then the test failed for the wrong reason. The invariant
    worth protecting is narrower and survives slots being filled: a slot must
    never be usable on a half-filled entry, because the dangerous state is a
    backend with a price nobody dated, not a backend that exists.
    """
    for kind, slot in (("video", "flagship"), ("video", "budget"), ("image", "primary")):
        entry = cfg.provider(kind, slot)
        if entry.backend is None:
            with pytest.raises(ProviderNotConfigured):
                entry.require_usable(TODAY, cfg.price_max_age_days)
            continue
        # Configured: then it must carry a price and a fresh verification date.
        entry.require_usable(entry.verified_on or TODAY, cfg.price_max_age_days)
        assert entry.model, f"{kind}.{slot} has a backend but no model id"
        assert entry.price is not None, f"{kind}.{slot} has a backend but no price"
        assert entry.verified_on is not None, f"{kind}.{slot} has a price but no verified_on"


def test_fake_slots_are_usable(cfg):
    cfg.provider("video", "fake").require_usable(TODAY, cfg.price_max_age_days)


def test_price_without_verified_on_is_refused():
    with pytest.raises(UnverifiedPriceError, match="verified_on"):
        _slot(verified_on=None).require_usable(TODAY, 90)


def test_missing_price_is_refused():
    with pytest.raises(UnverifiedPriceError, match="no price"):
        _slot(price=None).require_usable(TODAY, 90)


def test_stale_price_is_refused():
    """'Model names, prices, and APIs will be stale within two quarters.'"""
    with pytest.raises(UnverifiedPriceError, match="verified 120 days ago"):
        _slot(verified_on=TODAY - dt.timedelta(days=120)).require_usable(TODAY, 90)


def test_fresh_price_is_accepted():
    _slot(verified_on=TODAY - dt.timedelta(days=89)).require_usable(TODAY, 90)


def test_fake_slots_are_exempt_from_staleness():
    """Fakes cost nothing, so a 1970 date must not block offline development."""
    _slot(backend="fake", verified_on=dt.date(1970, 1, 1), price=0.0).require_usable(TODAY, 90)


def test_unknown_slot_names_the_known_ones(cfg):
    with pytest.raises(Exception, match="Known video slots"):
        cfg.provider("video", "nonexistent")
