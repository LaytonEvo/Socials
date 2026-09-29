"""Pydantic models for every file in `config/`.

Two decisions worth stating, because both are deliberate and neither is obvious.

**`extra="forbid"` on machine-read models.** A misspelled key that silently does
nothing is the config bug that costs the most to find: the system behaves as
though the setting were absent and nothing says so. Forbidding extras turns that
into a load error naming the key.

**Free-text blocks stay open.** `persona.backstory`, `tone`, `boundaries` and
`clothing` are prose destined for task 3.3's locked prompt fragments. Pinning
every nested key would make the schema a second copy of the document and would
reject a sentence added to it. They are validated as present and well-formed
mappings, not field by field.

The rules CLAUDE.md calls non-negotiable are enforced here rather than
downstream, so that config cannot express the forbidden state at all.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import DisclosureWeakened, PolicyWeakened, UnverifiedPrice
from .pending import Pendable

#: Machine-read config: unknown keys are typos and fail at load.
STRICT = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)
#: Prose config: shape is checked, contents are not enumerated.
OPEN = ConfigDict(extra="allow", arbitrary_types_allowed=True, frozen=True)

Fraction = Annotated[float, Field(ge=0.0, le=1.0)]


# --------------------------------------------------------------- providers --
class ProviderSlot(BaseModel):
    """One provider slot. `backend is None` means the slot is a placeholder.

    Every price field is optional because the unit differs by capability — video
    bills per second, images per image, speech per 1000 characters, an LLM per
    1000 tokens in each direction. Exactly one unit is expected to be present,
    and `require_usable` is what insists on it.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)

    backend: str | None = None
    model: str | None = None
    endpoint: str | None = None
    verified_on: dt.date | None = None

    price_usd_per_second: Decimal | None = None
    price_usd_per_image: Decimal | None = None
    price_usd_per_1000_characters: Decimal | None = None
    price_usd_per_1000_input_tokens: Decimal | None = None
    price_usd_per_1000_output_tokens: Decimal | None = None

    capabilities: dict[str, Any] = Field(default_factory=dict)
    request: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)

    #: Task 3.6 requires a designed synthetic voice, never one cloned from a real
    #: person without a contract. Null means nobody has checked.
    provenance_verified_on: dt.date | None = None

    @property
    def is_fake(self) -> bool:
        return self.backend == "fake"

    @property
    def is_placeholder(self) -> bool:
        return self.backend is None

    def prices(self) -> dict[str, Decimal]:
        return {
            name: value
            for name, value in (
                ("second", self.price_usd_per_second),
                ("image", self.price_usd_per_image),
                ("1000_characters", self.price_usd_per_1000_characters),
                ("1000_input_tokens", self.price_usd_per_1000_input_tokens),
                ("1000_output_tokens", self.price_usd_per_1000_output_tokens),
            )
            if value is not None
        }

    def require_usable(self, where: str, today: dt.date, max_age_days: int) -> None:
        """Raise unless this slot may be billed against right now.

        Carried over from the spike's loader, which learned each of these the
        expensive way. A fake slot skips the staleness check only: its price is
        zero and its date is 1970 by construction.
        """
        if self.is_placeholder:
            raise UnverifiedPrice(
                f"{where} is still a placeholder. Verify the provider against its "
                f"current official documentation, fill in model and price with a "
                f"verified_on date, and record what you found in docs/decisions/ "
                f"(CLAUDE.md non-negotiable rule 1)."
            )
        if not self.prices():
            raise UnverifiedPrice(f"{where}: no price set, so the cost guard cannot reserve.")
        if self.verified_on is None:
            raise UnverifiedPrice(
                f"{where}: price has no verified_on date. An undated price cannot be "
                f"known to be current, and the guard will not spend against one."
            )
        if self.is_fake:
            return
        age = (today - self.verified_on).days
        if age > max_age_days:
            raise UnverifiedPrice(
                f"{where}: price was verified {age} days ago "
                f"({self.verified_on.isoformat()}), limit is {max_age_days}. "
                f"Re-check the provider's current pricing before spending."
            )


class EmbedderSettings(BaseModel):
    """The identity scorer. Its version is part of the data model (amendment A3)."""

    model_config = STRICT

    backend: str | None = None
    model: str | None = None
    #: The SHA-256 of the weights. dlib's models carry no semantic version, and a
    #: hash is the strongest pin available: it changes if a single byte does.
    version: str | None = Field(default=None, max_length=64)
    dim: int | None = None
    recognition_model: str | None = None
    shape_predictor: str | None = None
    shape_predictor_sha256: str | None = Field(default=None, max_length=64)
    frame_sample_fps: float = 2.0
    threshold: float | None = None
    threshold_calibrated_on: dt.date | None = None
    licence: str | None = None
    licence_verified_on: dt.date | None = None
    #: The dlib ResNet's public-domain statement carries a FaceScrub
    #: training-data caveat (ADR 0004). It blocks publication, not measurement,
    #: which is why this is a separate flag from the licence itself.
    licence_cleared_for_publication: bool = False


class LoraSettings(BaseModel):
    """The identity layer's base model and the licence constraint on where it runs.

    ADR 0010: commercial use of a FLUX.1 [dev] LoRA is fal's licence, not ours, and it
    covers work trained and run on their platform. Taking the weights elsewhere falls
    back under Black Forest Labs' non-commercial terms.
    """

    model_config = STRICT

    base_model: str | None = None
    trainer: str | None = None
    price_usd_per_step: Decimal | None = None
    price_verified_on: dt.date | None = None
    base_model_licence: str | None = None
    base_model_licence_verified_on: dt.date | None = None
    base_model_licence_verified_by: str | None = None
    #: Where inference is licensed to run. Not a preference.
    inference_must_run_on: str | None = None
    self_hosting_permitted: bool = False
    commercial_grant_confirmed_in_writing: bool = False
    max_training_runs: int = 3

    @model_validator(mode="after")
    def _self_hosting_needs_its_own_licence(self) -> LoraSettings:
        """Config cannot quietly authorise running the weights off-platform.

        CLAUDE.md requires model weights permit commercial use and that the licence be
        recorded. Here the permission is conditional on WHERE the weights run, so
        flipping one flag without the other is the mistake worth making unrepresentable.
        """
        if self.self_hosting_permitted and not self.commercial_grant_confirmed_in_writing:
            raise ValueError(
                "lora.self_hosting_permitted is true while "
                "commercial_grant_confirmed_in_writing is false. Running the weights off "
                "fal falls under Black Forest Labs' non-commercial licence (ADR 0010). "
                "Get it in writing, or buy a BFL licence, before setting this."
            )
        return self


class ProvidersConfig(BaseModel):
    model_config = STRICT

    price_max_age_days: int = Field(gt=0)
    price_convention: str
    credentials: dict[str, str]
    providers: dict[str, dict[str, ProviderSlot]]
    embedder: EmbedderSettings
    lora: LoraSettings

    def slot(self, group: str, name: str) -> ProviderSlot:
        try:
            return self.providers[group][name]
        except KeyError as exc:
            available = sorted(self.providers.get(group, {}))
            raise KeyError(
                f"no provider slot {group}.{name}; {group} has {available or 'nothing'}"
            ) from exc

    def require_usable(self, group: str, name: str, today: dt.date | None = None) -> ProviderSlot:
        chosen = self.slot(group, name)
        chosen.require_usable(
            f"providers.{group}.{name}", today or dt.date.today(), self.price_max_age_days
        )
        return chosen


# ------------------------------------------------------------------ budget --
class BudgetSettings(BaseModel):
    """D8. A null ceiling is "not set", which is not the same as zero.

    `mode: observe` is the owner's answer of 2026-09-29: price, guard and record
    every call, but do not refuse on a monthly or per-piece ceiling until there is a
    month of real spend to set one from. CLAUDE.md still requires every paid call to
    go through the guard and write a ledger row, and that part is not optional — so
    observe mode changes what the guard *does*, never whether it runs.
    """

    model_config = STRICT

    mode: Literal["observe", "enforce"] = "enforce"
    monthly_usd: Decimal | None = None
    per_piece_usd: Decimal | None = None
    warn_at_fraction: Fraction = 0.8
    #: Amendment A7, and NOT part of what was deferred. This is what actually
    #: bounds spend in observe mode: a per-run budget the caller states explicitly.
    require_explicit_budget_per_run: bool = True
    review_after: str | None = None

    @model_validator(mode="after")
    def _enforce_mode_needs_a_ceiling(self) -> BudgetSettings:
        """`enforce` with nothing to enforce is a guard that quietly permits everything.

        Observe mode is the honest way to say "no ceiling yet". Claiming to enforce
        against a null ceiling is the failure this catches.
        """
        if self.mode == "enforce" and self.monthly_usd is None and self.per_piece_usd is None:
            raise ValueError(
                "budget.mode is 'enforce' but neither monthly_usd nor per_piece_usd is "
                "set, so there is nothing to enforce. Set a ceiling, or say "
                "mode: observe — which still prices, guards and records every call."
            )
        return self

    @property
    def observing(self) -> bool:
        return self.mode == "observe"


class BudgetConfig(BaseModel):
    model_config = STRICT

    budget: BudgetSettings


# ---------------------------------------------------------- content policy --
class BlockedTopic(BaseModel):
    model_config = STRICT

    id: str
    rule: Literal["permanent"]
    covers: list[str] = Field(min_length=1)


class FormatRule(BaseModel):
    model_config = STRICT

    id: str
    group: Literal["face_forward", "club_and_ball"]
    #: [usable, rated] from the blind owner rating, kept so nobody reads a
    #: two-clip result as a measurement.
    usable: tuple[int, int]
    takes: int = Field(ge=1)
    review: str | None = None
    requires: str | None = None

    @model_validator(mode="after")
    def _usable_cannot_exceed_rated(self) -> FormatRule:
        got, rated = self.usable
        if got > rated:
            raise ValueError(f"format {self.id}: {got} usable of {rated} rated is impossible")
        return self


class FormatEvidence(BaseModel):
    model_config = STRICT

    provider: str
    rated_on: dt.date
    takes_per_format: int = Field(ge=1)
    report: str
    sample_size_caveat: str


class ContentPolicyConfig(BaseModel):
    model_config = STRICT

    blocked_topics: list[BlockedTopic]
    footage_rules: dict[str, Any]
    blocked_formats: list[str]
    format_evidence: FormatEvidence
    allowed_formats: list[FormatRule]
    pending: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _financial_products_stay_blocked(self) -> ContentPolicyConfig:
        """CLAUDE.md: financial products are out of scope permanently.

        Enforced at load so the guard cannot be weakened by editing config —
        removing the topic, or downgrading it from `permanent`, fails here.
        """
        financial = next((t for t in self.blocked_topics if t.id == "financial_products"), None)
        if financial is None:
            raise PolicyWeakened(
                "content_policy.blocked_topics must include `financial_products`. "
                "CLAUDE.md: out of scope permanently, and the guard must not be weakened."
            )
        return self

    @model_validator(mode="after")
    def _allowed_and_blocked_are_disjoint(self) -> ContentPolicyConfig:
        overlap = sorted({f.id for f in self.allowed_formats} & set(self.blocked_formats))
        if overlap:
            raise ValueError(f"formats both allowed and blocked: {overlap}")
        return self


# ----------------------------------------------------------- kill criteria --
class AudienceCriteria(BaseModel):
    model_config = STRICT

    min_retention_pct: Pendable[float]
    min_views_by_piece_n: Pendable[int]
    evaluate_after_pieces: Pendable[int]


class EconomicsCriteria(BaseModel):
    model_config = STRICT

    max_cost_per_finished_piece_usd: Pendable[Decimal]
    #: The threshold BUILD_PLAN Section 9 says decides viability, and the one Spike 0
    #: could not measure. Pending against an unmeasured quantity is worse than pending
    #: against a known one, and the file itself says so.
    max_operator_minutes_per_piece: Pendable[int]


class QualityCriteria(BaseModel):
    model_config = STRICT

    min_identity_pass_rate_pct: Pendable[float]
    max_owner_reject_rate_pct: Pendable[float]


class KillCriteriaSettings(BaseModel):
    model_config = STRICT

    audience: AudienceCriteria
    economics: EconomicsCriteria
    quality: QualityCriteria
    #: Not thresholds, and not the owner's to trade away later.
    absolute: list[str] = Field(min_length=1)


class KillCriteriaConfig(BaseModel):
    model_config = STRICT

    kill_criteria: KillCriteriaSettings


# ----------------------------------------------------------------- persona --
class PersonaLook(BaseModel):
    model_config = OPEN

    status: str
    master_set: str | None = None
    #: A property of one master set scored by one model at one version, never a
    #: constant (amendment A3).
    identity_threshold: float | None = Field(default=None, gt=0.0, le=1.0)


class PersonaVoice(BaseModel):
    model_config = OPEN

    status: str
    provider: str | None = None
    voice_id: str | None = None
    provenance_checked: bool = False


class PersonaDisclosure(BaseModel):
    model_config = OPEN

    openly_ai: bool
    never_claims_to_be_human: bool

    @model_validator(mode="after")
    def _disclosure_cannot_be_turned_off(self) -> PersonaDisclosure:
        """CLAUDE.md: disclosure cannot be disabled.

        A config key that turns it off is exactly the flag that rule forbids, so
        the file is refused rather than trusting later code to ignore the value.
        """
        off = [
            name
            for name, value in (
                ("openly_ai", self.openly_ai),
                ("never_claims_to_be_human", self.never_claims_to_be_human),
            )
            if value is not True
        ]
        if off:
            raise DisclosureWeakened(
                f"persona.disclosure.{' and persona.disclosure.'.join(off)} must be true. "
                f"CLAUDE.md: disclosure cannot be disabled, and no flag, env var or code "
                f"path may skip it."
            )
        return self


class PersonaBoundaries(BaseModel):
    model_config = OPEN

    financial_products: Literal["forbidden"]

    @field_validator("financial_products")
    @classmethod
    def _permanent(cls, value: str) -> str:
        if value != "forbidden":
            raise PolicyWeakened("persona.boundaries.financial_products must be `forbidden` (D4).")
        return value


class PersonaSettings(BaseModel):
    model_config = OPEN

    id: str
    name: Pendable[str]
    look: PersonaLook
    voice: PersonaVoice
    positioning: str
    production_mode: Literal["synthetic", "hybrid"]
    disclosure: PersonaDisclosure
    boundaries: PersonaBoundaries
    #: Spec v1 §2 requires both before publishing, and neither is the build's to do.
    handles_checked: bool = False
    domains_registered: bool = False


class PersonaConfig(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True, frozen=True)

    persona: PersonaSettings
    content: dict[str, Any] = Field(default_factory=dict)
