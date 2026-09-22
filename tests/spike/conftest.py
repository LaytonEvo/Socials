from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.spike.config import ProviderConfig, load_config
from scripts.spike.embed import StubEmbedder, embed_images
from scripts.spike.ledger import CostLedger
from scripts.spike.providers import render_fake_face
from scripts.spike.runlog import RunLog

TODAY = dt.date(2026, 9, 22)


@pytest.fixture
def cfg():
    return load_config(Path("config/spike.yaml"))


@pytest.fixture
def run_log(tmp_path: Path) -> RunLog:
    return RunLog(tmp_path / "20260922T000000Z-test")


@pytest.fixture
def ledger(run_log: RunLog) -> CostLedger:
    return CostLedger(budget_usd=Decimal("10.00"), log=run_log, today=TODAY)


@pytest.fixture
def priced() -> ProviderConfig:
    """A real (non-fake) provider slot with a fresh, verified price."""
    return ProviderConfig(
        slot="flagship",
        kind="video",
        backend="fake",
        model="test-model",
        endpoint=None,
        price=Decimal("0.40").__float__(),
        price_unit="second",
        verified_on=TODAY,
    )


@pytest.fixture
def embedder() -> StubEmbedder:
    return StubEmbedder()


def make_stills(dest: Path, identity: str, count: int, prefix: str = "s") -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(count):
        p = dest / f"{prefix}_{i:02d}.png"
        render_fake_face(identity, variation=i).save(p)
        out.append(p)
    return out


@pytest.fixture
def master(tmp_path: Path, embedder: StubEmbedder):
    stills = make_stills(tmp_path / "master", "look-a", 8, "m")
    return embed_images(embedder, stills, label="master")
