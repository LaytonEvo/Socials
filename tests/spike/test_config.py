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


def test_shipped_config_blocks_the_embedder(cfg):
    """The repo's config must not let anyone score with an unchosen model."""
    with pytest.raises(EmbedderNotConfigured, match="0002"):
        cfg.embedder.require_usable()


def test_shipped_config_blocks_real_providers(cfg):
    for kind, slot in (("video", "flagship"), ("video", "budget"), ("image", "primary")):
        with pytest.raises(ProviderNotConfigured):
            cfg.provider(kind, slot).require_usable(TODAY, cfg.price_max_age_days)


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
