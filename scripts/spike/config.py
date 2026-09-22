"""Loading and validation for config/spike.yaml.

The validation here is the point of the module. A placeholder that silently
reads as "no cost" or "no licence" would let the spike spend money or produce
unusable evidence, so every unfilled slot raises at the moment it is *used*
rather than at load time -- the config is allowed to be half-filled while the
blockers are being worked through.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import (
    ConfigError,
    EmbedderNotConfigured,
    ProviderNotConfigured,
    UnverifiedPriceError,
)

DEFAULT_CONFIG_PATH = Path("config/spike.yaml")


def _as_date(value: Any, field: str) -> dt.date:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError(f"{field}: {value!r} is not an ISO date (YYYY-MM-DD)") from exc
    raise ConfigError(f"{field}: expected a YYYY-MM-DD date, got {value!r}")


@dataclass(frozen=True)
class ProviderConfig:
    """One provider slot. `backend is None` means the slot is a placeholder."""

    slot: str
    kind: str  # image | video | lipsync
    backend: str | None
    model: str | None
    endpoint: str | None
    price: float | None
    price_unit: str  # "image" or "second"
    verified_on: dt.date | None

    @property
    def is_fake(self) -> bool:
        return self.backend == "fake"

    def require_usable(self, today: dt.date, max_age_days: int) -> None:
        """Raise unless this slot may be used for a real call right now."""
        where = f"providers.{self.kind}.{self.slot}"
        if self.backend is None:
            raise ProviderNotConfigured(
                f"{where} is still a placeholder. Verify the provider against its "
                f"current official documentation, fill in model/endpoint/price with a "
                f"verified_on date, and record what you found in docs/decisions/ "
                f"(CLAUDE.md non-negotiable rule 1)."
            )
        if self.price is None:
            raise UnverifiedPriceError(f"{where}: no price_usd_per_{self.price_unit} set.")
        if self.verified_on is None:
            raise UnverifiedPriceError(
                f"{where}: price has no verified_on date. Prices go stale within two "
                f"quarters; the harness will not spend against an undated price."
            )
        if self.is_fake:
            return
        age = (today - self.verified_on).days
        if age > max_age_days:
            raise UnverifiedPriceError(
                f"{where}: price was verified {age} days ago "
                f"({self.verified_on.isoformat()}), limit is {max_age_days}. "
                f"Re-check the provider's current pricing before spending."
            )


@dataclass(frozen=True)
class EmbedderConfig:
    backend: str | None
    model: str | None
    version: str | None
    dim: int | None
    licence: str | None
    licence_verified_on: dt.date | None
    frame_sample_fps: float
    threshold: float | None
    threshold_calibrated_on: dt.date | None
    #: Backend-specific settings, merged from ``embedder.backends.<name>``.
    #: Model file paths live here, never in code.
    options: dict[str, Any] = field(default_factory=dict)

    def require_usable(self) -> None:
        if self.backend is None:
            raise EmbedderNotConfigured(
                "embedder.backend is not set. The identity scorer is the measuring "
                "instrument for the whole spike and is blocked on "
                "docs/decisions/0002-face-embedding-model-licence.md. Choosing it "
                "provisionally is not an option: changing the scorer later invalidates "
                "every stored vector and the calibrated threshold with them."
            )
        missing = [
            name
            for name, value in (
                ("model", self.model),
                ("version", self.version),
                ("dim", self.dim),
            )
            if value is None
        ]
        if missing:
            raise EmbedderNotConfigured(
                f"embedder.{', embedder.'.join(missing)} not set. The model, its exact "
                f"version and the embedding dimension must all be pinned, because a "
                f"calibrated threshold is valid for exactly one of them "
                f"(BUILD_ORDER amendment A3)."
            )
        if self.backend != "stub" and (self.licence is None or self.licence_verified_on is None):
            raise EmbedderNotConfigured(
                "embedder.licence and embedder.licence_verified_on must both be set. "
                "CLAUDE.md requires that model weights permit commercial use and that "
                "the licence is recorded. Read the actual current licence text, not a "
                "summary of it."
            )


@dataclass(frozen=True)
class SpikeConfig:
    run_root: Path
    price_max_age_days: int
    embedder: EmbedderConfig
    providers: dict[str, dict[str, ProviderConfig]]
    lora: dict[str, Any]
    generation: dict[str, Any]
    source_path: Path
    _embedder_backends: dict[str, dict[str, Any]] = field(default_factory=dict)

    def embedder_for(self, backend: str | None = None) -> EmbedderConfig:
        """Embedder config for one backend, with its own options merged in.

        Each backend declares its own dimension, licence and model paths under
        ``embedder.backends.<name>``, because a bake-off runs several and they
        do not share any of those. The top-level block still holds what is
        common: sampling rate, and the calibrated threshold.
        """
        name = backend or self.embedder.backend
        if name is None:
            return self.embedder
        opts = dict(self._embedder_backends.get(name, {}))
        licence_date = opts.pop("licence_verified_on", None)
        return dataclasses.replace(
            self.embedder,
            backend=name,
            model=opts.pop("model", None) or opts.get("hf_model") or name,
            version=str(opts.pop("version", "0")),
            dim=int(opts.pop("dim")) if opts.get("dim") is not None else None,
            licence=opts.pop("licence", None),
            licence_verified_on=(
                _as_date(licence_date, f"embedder.backends.{name}.licence_verified_on")
                if licence_date
                else None
            ),
            options=opts,
        )

    def provider(self, kind: str, slot: str) -> ProviderConfig:
        try:
            return self.providers[kind][slot]
        except KeyError:
            known = ", ".join(sorted(self.providers.get(kind, {}))) or "(none)"
            raise ConfigError(
                f"No provider slot providers.{kind}.{slot} in {self.source_path}. "
                f"Known {kind} slots: {known}"
            ) from None


_PRICE_UNITS = {"image": "image", "video": "second", "lipsync": "second"}


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> SpikeConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"No spike config at {path}")
    raw = yaml.safe_load(path.read_text()) or {}

    emb = raw.get("embedder") or {}
    licence_date = emb.get("licence_verified_on")
    thr_date = emb.get("threshold_calibrated_on")
    embedder = EmbedderConfig(
        backend=emb.get("backend"),
        model=emb.get("model"),
        version=str(emb["version"]) if emb.get("version") is not None else None,
        dim=int(emb["dim"]) if emb.get("dim") is not None else None,
        licence=emb.get("licence"),
        licence_verified_on=(
            _as_date(licence_date, "embedder.licence_verified_on") if licence_date else None
        ),
        frame_sample_fps=float(emb.get("frame_sample_fps", 2.0)),
        threshold=float(emb["threshold"]) if emb.get("threshold") is not None else None,
        threshold_calibrated_on=(
            _as_date(thr_date, "embedder.threshold_calibrated_on") if thr_date else None
        ),
    )

    providers: dict[str, dict[str, ProviderConfig]] = {}
    for kind, slots in (raw.get("providers") or {}).items():
        unit = _PRICE_UNITS.get(kind)
        if unit is None:
            raise ConfigError(f"Unknown provider kind {kind!r} in {path}")
        providers[kind] = {}
        for slot, cfg in (slots or {}).items():
            cfg = cfg or {}
            verified = cfg.get("verified_on")
            price = cfg.get(f"price_usd_per_{unit}")
            providers[kind][slot] = ProviderConfig(
                slot=slot,
                kind=kind,
                backend=cfg.get("backend"),
                model=cfg.get("model"),
                endpoint=cfg.get("endpoint"),
                price=float(price) if price is not None else None,
                price_unit=unit,
                verified_on=(
                    _as_date(verified, f"providers.{kind}.{slot}.verified_on") if verified else None
                ),
            )

    return SpikeConfig(
        run_root=Path(raw.get("run_root", "spike/runs")),
        price_max_age_days=int(raw.get("price_max_age_days", 90)),
        embedder=embedder,
        providers=providers,
        lora=raw.get("lora") or {},
        generation=raw.get("generation") or {},
        source_path=path,
        _embedder_backends=emb.get("backends") or {},
    )


def write_threshold(path: Path | str, threshold: float, calibrated_on: dt.date) -> None:
    """Persist a calibrated threshold back into the config.

    Written by `cli.py calibrate` so the number that gates takes is the number
    the calibration produced, rather than one typed in by hand.
    """
    path = Path(path)
    text = path.read_text()
    out = []
    for line in text.splitlines():
        if line.startswith("  threshold:"):
            out.append(f"  threshold: {threshold:.6f}")
        elif line.startswith("  threshold_calibrated_on:"):
            out.append(f"  threshold_calibrated_on: {calibrated_on.isoformat()}")
        else:
            out.append(line)
    path.write_text("\n".join(out) + "\n")
