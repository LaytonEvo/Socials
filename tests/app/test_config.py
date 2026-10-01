"""Task 0.2 — config loading and validation.

The most valuable test here is the first one: the repository's own config files
load and validate. Everything else checks that the failures fail usefully.

Fixtures copy the real `config/` directory and mutate a copy, rather than
building minimal YAML by hand. A synthetic fixture drifts from the real files and
then tests a schema nothing uses; a copy of the real thing cannot.
"""

from __future__ import annotations

import datetime as dt
import shutil
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.config import (
    Config,
    ConfigFileError,
    DecisionPending,
    DisclosureWeakened,
    Pending,
    PolicyWeakened,
    UnverifiedPrice,
    is_pending,
    load_all,
    require,
)
from app.config.schema import PersonaDisclosure, PersonaLook, ProviderSlot

REPO = Path(__file__).resolve().parents[2]
REAL_CONFIG = REPO / "config"


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A writable copy of the real config directory."""
    target = tmp_path / "config"
    shutil.copytree(REAL_CONFIG, target)
    return target


def _edit(config_dir: Path, name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    path = config_dir / name
    data = yaml.safe_load(path.read_text())
    mutate(data)
    path.write_text(yaml.safe_dump(data))


# ------------------------------------------------------------ the real thing --
def test_the_repositorys_own_config_is_valid() -> None:
    """If this fails, the repo is shipping config the app cannot load."""
    cfg = load_all(REAL_CONFIG)
    assert isinstance(cfg, Config)


def test_settled_decisions_are_readable() -> None:
    cfg = load_all(REAL_CONFIG)
    # ADR 0008: the look is decided and the threshold belongs to that master set.
    # Recalibrated 2026-09-29 when the reference set widened from 105 to 121 stills.
    assert cfg.persona.persona.look.identity_threshold == pytest.approx(0.9619)
    assert cfg.persona.persona.production_mode == "synthetic"
    assert cfg.content_policy.blocked_formats == []
    assert len(cfg.content_policy.allowed_formats) == 13


def test_the_decisions_the_owner_has_made_are_recorded() -> None:
    """Updated 2026-10-01, when D8 was answered with a number.

    This pins the owner's answers so a later change is deliberate rather than drift,
    and it has now caught that twice. D8 was first answered "no ceiling yet, observe
    first" on the understanding that generation was cheap. ADR 0013 showed the video
    slot was priced at the 480p discount rate while sending 768P, which makes a take
    20 cents rather than 6 and a finished piece about $20, and the owner set $100 a
    month against those numbers.
    """
    cfg = load_all(REAL_CONFIG)
    assert cfg.persona.persona.name == "Mollie"
    # D8, answered 2026-10-01: $100/month, enforced rather than observed, because a
    # ceiling that only reports is not a budget.
    assert cfg.budget.budget.mode == "enforce"
    assert cfg.budget.budget.monthly_usd == Decimal("100")
    # Deliberately still null: no piece has a measured cost yet, so a per-piece
    # ceiling would be inventing the number it is meant to bound.
    assert cfg.budget.budget.per_piece_usd is None


def test_outstanding_decisions_load_but_are_not_values() -> None:
    """D5's thresholds are still unmade, and the config still loads.

    This is what the Pending machinery is for, exercised against a real file rather
    than a synthetic value: the build proceeds while the decision waits, and asking
    for the value raises instead of returning a placeholder string.
    """
    cfg = load_all(REAL_CONFIG)
    criteria = cfg.kill_criteria.kill_criteria
    assert is_pending(criteria.economics.max_operator_minutes_per_piece)
    assert is_pending(criteria.audience.min_retention_pct)
    with pytest.raises(DecisionPending, match="D5"):
        require(
            criteria.quality.max_owner_reject_rate_pct,
            "kill_criteria.quality.max_owner_reject_rate_pct",
        )


# ----------------------------------------------------- malformed fails fast --
def test_missing_file_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileError, match="does not exist"):
        load_all(tmp_path)


def test_unknown_key_is_rejected_and_named(config_dir: Path) -> None:
    """A typo'd key that silently does nothing is the costliest config bug."""

    def mutate(data: dict[str, Any]) -> None:
        data["budget"]["monthy_usd"] = 100  # note the typo

    _edit(config_dir, "budget.yaml", mutate)
    with pytest.raises(ConfigFileError) as exc:
        load_all(config_dir)
    assert "monthy_usd" in str(exc.value)
    assert "budget.yaml" in str(exc.value)


def test_wrong_type_is_rejected(config_dir: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["price_max_age_days"] = "ninety"

    _edit(config_dir, "providers.yaml", mutate)
    with pytest.raises(ConfigFileError, match="price_max_age_days"):
        load_all(config_dir)


def test_empty_file_is_rejected(config_dir: Path) -> None:
    (config_dir / "budget.yaml").write_text("")
    with pytest.raises(ConfigFileError, match="is empty"):
        load_all(config_dir)


def test_non_mapping_top_level_is_rejected(config_dir: Path) -> None:
    (config_dir / "budget.yaml").write_text("- one\n- two\n")
    with pytest.raises(ConfigFileError, match="expected a mapping"):
        load_all(config_dir)


def test_malformed_yaml_is_rejected(config_dir: Path) -> None:
    (config_dir / "budget.yaml").write_text("budget:\n  monthly_usd: [unclosed\n")
    with pytest.raises(ConfigFileError, match="not valid YAML"):
        load_all(config_dir)


# ------------------------------------- rules config must not be able to say --
def test_disclosure_cannot_be_turned_off_in_config() -> None:
    with pytest.raises(DisclosureWeakened, match="openly_ai"):
        PersonaDisclosure(openly_ai=False, never_claims_to_be_human=True)


def test_never_claims_to_be_human_cannot_be_turned_off() -> None:
    with pytest.raises(DisclosureWeakened, match="never_claims_to_be_human"):
        PersonaDisclosure(openly_ai=True, never_claims_to_be_human=False)


def test_disclosure_off_refuses_the_whole_file(config_dir: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["persona"]["disclosure"]["openly_ai"] = False

    _edit(config_dir, "persona.yaml", mutate)
    with pytest.raises(DisclosureWeakened):
        load_all(config_dir)


def test_financial_products_cannot_be_removed_from_the_policy(config_dir: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["blocked_topics"] = [
            t for t in data["blocked_topics"] if t["id"] != "financial_products"
        ]

    _edit(config_dir, "content_policy.yaml", mutate)
    with pytest.raises(PolicyWeakened, match="financial_products"):
        load_all(config_dir)


def test_a_permanent_block_cannot_be_downgraded(config_dir: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["blocked_topics"][0]["rule"] = "review_case_by_case"

    _edit(config_dir, "content_policy.yaml", mutate)
    with pytest.raises(ConfigFileError, match="rule"):
        load_all(config_dir)


def test_personas_financial_boundary_cannot_be_weakened(config_dir: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["persona"]["boundaries"]["financial_products"] = "allowed"

    _edit(config_dir, "persona.yaml", mutate)
    with pytest.raises(ConfigFileError, match="financial_products"):
        load_all(config_dir)


def test_a_format_cannot_be_allowed_and_blocked(config_dir: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["blocked_formats"] = ["chip"]

    _edit(config_dir, "content_policy.yaml", mutate)
    with pytest.raises(ConfigFileError, match="both allowed and blocked"):
        load_all(config_dir)


def test_yield_cannot_exceed_the_takes_rated(config_dir: Path) -> None:
    """Guards the figure that sets take counts: 5 usable of 2 rated is a typo."""

    def mutate(data: dict[str, Any]) -> None:
        data["allowed_formats"][0]["usable"] = [5, 2]

    _edit(config_dir, "content_policy.yaml", mutate)
    with pytest.raises(ConfigFileError, match="impossible"):
        load_all(config_dir)


# -------------------------------------------- undecided is not a load error --
def test_require_names_the_decision_not_the_type() -> None:
    with pytest.raises(DecisionPending) as exc:
        require(Pending("PENDING_D8"), "budget.monthly_usd")
    message = str(exc.value)
    assert "D8" in message
    assert "budget.monthly_usd" in message
    assert "must not invent" in message


def test_require_passes_a_decided_value_through() -> None:
    assert require(Decimal("250"), "budget.monthly_usd") == Decimal("250")


def test_pending_is_neither_falsy_nor_a_string() -> None:
    """Both would let a placeholder slip into a prompt unnoticed.

    Falsy and `if cfg.name:` skips it silently. A str subclass and it
    concatenates into generated text as though it were her name.
    """
    pending = Pending("PENDING_D1_NAME")
    assert bool(pending) is True
    assert not isinstance(pending, str)


def test_the_persona_name_is_now_readable() -> None:
    """D1's last field landed on 2026-09-29."""
    assert load_all(REAL_CONFIG).persona_name == "Mollie"


def test_the_name_is_recorded_as_given_not_interpreted() -> None:
    """Spec v1 §2 says the name is the owner's decision, "not generated".

    It asks for two words and one was given, and it lists "Millie Hart" as a
    candidate one letter away. Neither gap is the build's to close, so both are
    recorded as outstanding rather than resolved — and these flags are what stop a
    publish happening before the handles and domains exist.
    """
    persona = load_all(REAL_CONFIG).persona.persona
    assert persona.handles_checked is False
    assert persona.domains_registered is False


# ------------------------------------------------------------------ pricing --
def test_a_placeholder_slot_refuses_to_be_billed() -> None:
    with pytest.raises(UnverifiedPrice, match="still a placeholder"):
        ProviderSlot().require_usable("providers.video.budget", dt.date.today(), 90)


def test_a_price_without_a_date_is_refused() -> None:
    slot = ProviderSlot(backend="fal", model="m", price_usd_per_second=Decimal("0.01"))
    with pytest.raises(UnverifiedPrice, match="no verified_on date"):
        slot.require_usable("providers.video.golf", dt.date.today(), 90)


def test_a_slot_with_no_price_is_refused() -> None:
    slot = ProviderSlot(backend="anthropic", model="m", verified_on=dt.date(2026, 9, 25))
    with pytest.raises(UnverifiedPrice, match="no price set"):
        slot.require_usable("providers.llm.shotlist", dt.date(2026, 9, 29), 90)


def test_a_stale_price_is_refused_with_its_age() -> None:
    slot = ProviderSlot(
        backend="fal",
        model="m",
        price_usd_per_second=Decimal("0.01"),
        verified_on=dt.date(2026, 1, 1),
    )
    with pytest.raises(UnverifiedPrice, match="271 days ago"):
        slot.require_usable("providers.video.golf", dt.date(2026, 9, 29), 90)


def test_a_fresh_price_is_accepted() -> None:
    slot = ProviderSlot(
        backend="fal",
        model="m",
        price_usd_per_second=Decimal("0.0125"),
        verified_on=dt.date(2026, 9, 25),
    )
    slot.require_usable("providers.video.golf", dt.date(2026, 9, 29), 90)


def test_a_fake_slot_is_exempt_from_staleness_only() -> None:
    """Its 1970 date is deliberate; it bills nothing, so age is meaningless."""
    fake = ProviderSlot(
        backend="fake",
        model="fake-video-v0",
        price_usd_per_second=Decimal("0"),
        verified_on=dt.date(1970, 1, 1),
    )
    fake.require_usable("providers.fake.video", dt.date(2026, 9, 29), 90)

    undated = ProviderSlot(backend="fake", model="fake-video-v0", price_usd_per_second=Decimal("0"))
    with pytest.raises(UnverifiedPrice, match="no verified_on date"):
        undated.require_usable("providers.fake.video", dt.date(2026, 9, 29), 90)


def test_every_real_slot_in_the_repo_declares_exactly_one_price_unit() -> None:
    """Two units on one slot means the guard has to guess which one bills."""
    cfg = load_all(REAL_CONFIG)
    for group, slots in cfg.providers.providers.items():
        for name, slot in slots.items():
            if slot.is_placeholder:
                continue
            units = slot.prices()
            # The LLM slot bills input and output separately and is the one
            # legitimate exception; its prices are null until verified anyway.
            if group == "llm" or name == "llm":
                continue
            assert len(units) == 1, f"providers.{group}.{name} declares units {sorted(units)}"


def test_an_unknown_slot_lists_what_is_available() -> None:
    cfg = load_all(REAL_CONFIG)
    with pytest.raises(KeyError, match="golf"):
        cfg.providers.slot("video", "flagship")


def test_credentials_are_names_not_values() -> None:
    """Secrets come from the environment only; config names the variable."""
    cfg = load_all(REAL_CONFIG)
    for service, variable in cfg.providers.credentials.items():
        assert variable.isupper(), f"credentials.{service} should name an env var, got {variable!r}"
        assert len(variable) < 64, f"credentials.{service} looks like a value, not a name"


# ------------------------------------------------- a price is a price FOR something --
def test_a_price_quoted_for_another_request_is_refused() -> None:
    """Found 2026-10-01: the video slot was priced at the 480p rate while sending 768P.

    turbo bills $0.02/second at 768p and $0.04 at 1080p, doubling again when the launch
    discount lapsed, so a bare `price_usd_per_second` says nothing without naming the
    resolution it is for. The guard was understating video by 60%, and by 3.2x once the
    discount expired — on a slot whose comment already claimed the price was verified.
    Hence a validator and not another comment.
    """
    with pytest.raises(ValidationError, match="price_basis says this price is for"):
        ProviderSlot(
            backend="fal",
            model="minimax/h3-max-turbo/image-to-video",
            price_usd_per_second=Decimal("0.04"),
            verified_on=dt.date(2026, 10, 1),
            price_basis={"resolution": "768P"},
            request={"base": {"resolution": "1080P"}},
        )


def test_a_price_matching_its_basis_is_accepted() -> None:
    slot = ProviderSlot(
        backend="fal",
        model="minimax/h3-max-turbo/image-to-video",
        price_usd_per_second=Decimal("0.04"),
        verified_on=dt.date(2026, 10, 1),
        price_basis={"resolution": "768P"},
        request={"base": {"resolution": "768P"}},
    )
    assert slot.price_usd_per_second == Decimal("0.04")


def test_a_slot_with_no_basis_is_left_alone() -> None:
    """Most slots bill one way regardless of the request; they need no basis."""
    slot = ProviderSlot(
        backend="fal",
        model="x",
        price_usd_per_image=Decimal("0.07"),
        verified_on=dt.date(2026, 9, 30),
        request={"base": {"image_size": "square_hd"}},
    )
    assert not slot.price_basis


def test_the_real_video_slot_prices_the_resolution_it_sends() -> None:
    """The regression itself, against the live config rather than a constructed slot."""
    providers = load_all(Path("config")).providers
    slot = providers.slot("video", "golf")
    assert slot.price_basis.get("resolution") == (slot.request.get("base") or {}).get("resolution")


def test_the_keyframe_bar_must_sit_above_the_video_bar() -> None:
    """A keyframe bar at or below the video bar admits keyframes arithmetic condemns.

    Animating costs 0.0165 to 0.0328 off the worst frame, so a keyframe screened at the
    video threshold produces a take below it. That is how five of six runs failed, each
    on a keyframe the stills screen had passed.
    """
    with pytest.raises(ValidationError, match="must be above identity_threshold_video"):
        PersonaLook(
            status="locked",
            identity_threshold_video=0.951,
            identity_threshold_keyframe=0.951,
        )


def test_the_real_keyframe_bar_has_margin_for_the_animation() -> None:
    look = load_all(Path("config")).persona.persona.look
    assert look.identity_threshold_keyframe is not None
    assert look.identity_threshold_video is not None
    margin = look.identity_threshold_keyframe - look.identity_threshold_video
    assert margin >= 0.0165, (
        f"only {margin:.4f} of margin, under the smallest animation drop measured "
        f"(0.0165) — a keyframe clearing this bar can still produce a refused take"
    )
