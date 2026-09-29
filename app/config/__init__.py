"""Config loading with schema validation — task 0.2.

The acceptance criterion is that invalid config fails fast with a clear error, and
"invalid" has two meanings that must not be conflated:

- **Malformed** — a missing file, a typo'd key, a float where a date belongs, a
  rule CLAUDE.md forbids weakening. A bug. It raises at load, which is the
  "fails fast" the task asks for.
- **Undecided** — a `PENDING_*` placeholder standing in for one of BUILD_PLAN
  Section 1's eight human decisions. Not a bug. It loads, and raises only where a
  value is actually needed, because the build has to proceed while D1's name and
  D8's ceilings are outstanding.

Pydantic gives the first for free. The second is `app.config.pending`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from .errors import (
    ConfigError,
    ConfigFileError,
    DecisionPending,
    DisclosureWeakened,
    PolicyWeakened,
    UnverifiedPrice,
)
from .pending import Pending, is_pending, require
from .schema import (
    BudgetConfig,
    ContentPolicyConfig,
    KillCriteriaConfig,
    PersonaConfig,
    ProvidersConfig,
    ProviderSlot,
)

__all__ = [
    "BudgetConfig",
    "Config",
    "ConfigError",
    "ConfigFileError",
    "ContentPolicyConfig",
    "DecisionPending",
    "DisclosureWeakened",
    "KillCriteriaConfig",
    "Pending",
    "PersonaConfig",
    "PolicyWeakened",
    "ProviderSlot",
    "ProvidersConfig",
    "UnverifiedPrice",
    "is_pending",
    "load_all",
    "load_file",
    "require",
]

DEFAULT_CONFIG_DIR = Path("config")

#: Which model validates which file. One place, so a new config file cannot be
#: added without deciding what validates it.
FILES: dict[str, type[BaseModel]] = {
    "persona.yaml": PersonaConfig,
    "providers.yaml": ProvidersConfig,
    "content_policy.yaml": ContentPolicyConfig,
    "budget.yaml": BudgetConfig,
    "kill_criteria.yaml": KillCriteriaConfig,
}

M = TypeVar("M", bound=BaseModel)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigFileError(
            f"{path} does not exist. Every file in `config/` is required; a missing one "
            f"is not an empty one, because an absent setting and a setting deliberately "
            f"left null mean different things here."
        )
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigFileError(f"{path} is not valid YAML: {exc}") from exc
    if raw is None:
        raise ConfigFileError(f"{path} is empty.")
    if not isinstance(raw, dict):
        raise ConfigFileError(
            f"{path}: expected a mapping at the top level, got {type(raw).__name__}."
        )
    return raw


def _explain(path: Path, exc: ValidationError) -> str:
    """Turn a pydantic error into something a person can act on.

    Pydantic's default rendering leads with the model's class name, which is an
    implementation detail nobody editing YAML knows. This leads with the file and
    the key path instead.
    """
    lines = [f"{path} failed validation:"]
    for err in exc.errors():
        where = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  {where}: {err['msg']}")
    return "\n".join(lines)


def load_file(path: Path, model: type[M]) -> M:
    """Load and validate one config file."""
    raw = _read_yaml(path)
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ConfigFileError(_explain(path, exc)) from exc
    # DisclosureWeakened and PolicyWeakened deliberately have no handler here.
    # Pydantic only wraps ValueError subclasses, so a validator raising either of
    # those lets it through untouched — which is what should happen. Rewriting it
    # as a generic file error would bury the reason the file was refused.


class Config(BaseModel):
    """Every config file, validated, loaded once."""

    model_config = {"frozen": True}

    persona: PersonaConfig
    providers: ProvidersConfig
    content_policy: ContentPolicyConfig
    budget: BudgetConfig
    kill_criteria: KillCriteriaConfig

    @property
    def persona_name(self) -> str:
        """Her name, or an error naming D1 as the reason there isn't one."""
        return require(
            self.persona.persona.name,
            "persona.name",
            because="Spec v1 §2 sets the rules; the candidates are the owner's to check.",
        )


def load_all(config_dir: Path | None = None) -> Config:
    """Load and validate every config file, failing on the first malformed one.

    Placeholders for undecided values survive this; see `app.config.pending`.
    """
    root = config_dir or DEFAULT_CONFIG_DIR
    loaded = {
        name.removesuffix(".yaml"): load_file(root / name, model) for name, model in FILES.items()
    }
    return Config(
        persona=loaded["persona"],  # type: ignore[arg-type]
        providers=loaded["providers"],  # type: ignore[arg-type]
        content_policy=loaded["content_policy"],  # type: ignore[arg-type]
        budget=loaded["budget"],  # type: ignore[arg-type]
        kill_criteria=loaded["kill_criteria"],  # type: ignore[arg-type]
    )
