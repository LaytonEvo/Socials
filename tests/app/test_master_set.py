"""The master set is irreplaceable, so something should say so in a way that fails.

ADR 0008 records that `spike/data/` being tracked is "load-bearing". Nothing enforced
it. These 105 stills are the persona's canonical reference set: the 0.9609 threshold,
the master centroid, the coverage floor and every measured pass rate are defined
against them, and they **cannot be regenerated identically** — the models are
non-deterministic, measured at 25.42/255 mean per-pixel difference on an identical
seed.

They also live under `spike/`, a directory BUILD_ORDER calls throwaway in four
places. That text is about code, not data, but the name invites the mistake and the
mistake is irreversible. So the count is asserted rather than trusted.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MASTER_SET = REPO / "spike" / "data" / "master_v2"

#: Measured 2026-09-29: 108 images, of which 105 carry exactly one detectable face.
#: The three rejects (b1_11, b2_04, b4_10) have no detectable face and were excluded
#: by the spike's own ingest filter, which is why the usable count is 105.
TOTAL_IMAGES = 108
USABLE_STILLS = 105
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def _images() -> list[Path]:
    return sorted(p for p in MASTER_SET.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def test_the_master_set_still_exists() -> None:
    assert MASTER_SET.is_dir(), (
        f"{MASTER_SET} is gone. This is the persona's canonical reference set and it "
        f"cannot be regenerated identically. Recover it from git history before doing "
        f"anything else."
    )


def test_no_still_has_been_lost() -> None:
    """A deleted still silently changes the centroid the threshold is defined against.

    Nothing downstream would report it: scoring would carry on against a slightly
    different centroid and every number would move a little.
    """
    found = len(_images())
    assert found == TOTAL_IMAGES, (
        f"the master set has {found} images, expected {TOTAL_IMAGES}. If stills were "
        f"added deliberately the threshold must be recalibrated (ADR 0008: her look is "
        f"a hard dependency in the same way the embedder is). If they were removed, "
        f"recover them."
    )


def test_the_count_matches_what_config_claims() -> None:
    """A claim nothing checks is a claim that drifts.

    `reference_stills` is the total the centroid is built from: 105 usable faces plus
    the 16 ingested on 2026-09-29.
    """
    look = yaml.safe_load((REPO / "config" / "persona.yaml").read_text())["persona"]["look"]
    assert look["master_set"] == MASTER_SET.name
    assert look["reference_stills"] == USABLE_STILLS + 16


def test_the_threshold_belongs_to_this_set() -> None:
    """Recorded together, because one without the other means nothing.

    Amendment A3 makes a threshold valid for one embedding model at one version. ADR
    0008 adds that it is equally valid for one *face*: change the master set and the
    centroid, the calibration and every pass rate move with it.
    """
    look = yaml.safe_load((REPO / "config" / "persona.yaml").read_text())["persona"]["look"]
    # Recalibrated 2026-09-29 when the set was widened from 105 to 121. Was 0.9609.
    assert look["identity_threshold"] == 0.9619
    assert look["master_set"] == "master_v2"
    assert look["status"] == "decided"


def test_every_reference_set_config_names_exists() -> None:
    """The centroid spans all four directories, so a missing one silently shrinks it."""
    look = yaml.safe_load((REPO / "config" / "persona.yaml").read_text())["persona"]["look"]
    counts = {}
    for name in look["reference_sets"]:
        directory = REPO / "spike" / "data" / name
        assert directory.is_dir(), f"{directory} is named in config and does not exist"
        counts[name] = len([p for p in directory.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES])
    # master_v2 holds 108 of which 105 carry a usable face; the other three sets were
    # filtered on the way in, so every file in them counts.
    assert counts == {"master_v2": 108, "outfit": 6, "lighting": 7, "body": 3}
    assert sum(counts.values()) - 3 == look["reference_stills"]
