"""Task 0.1 — the scaffold, and the CLAUDE.md boundaries that cannot be conventions.

A scaffold of empty packages is not worth a test on its own. What is worth
testing is that the structure BUILD_PLAN specifies is actually the structure on
disk, that it is all packaged and type-checked, and that the architectural rules
CLAUDE.md states as non-negotiable are enforced by something other than memory.
"""

from __future__ import annotations

import ast
import importlib
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: The layout in BUILD_PLAN Section 3, "Repository layout". `migrations/` is
#: deliberately absent: Alembic generates its own tree and task 0.3 owns it, so
#: an empty directory here would only be something for Alembic to complain about.
APP_PACKAGES = (
    "app",
    "app.analytics",
    "app.api",
    "app.compliance",
    "app.costs",
    "app.identity",
    "app.models",
    "app.pipeline",
    "app.providers",
    "app.publishing",
    "app.ui",
    "workers",
)

#: Model-provider SDKs. CLAUDE.md: "No vendor SDK outside `app/providers/`.
#: Pipeline code uses the adapter protocols only."
#:
#: Storage and database drivers are not on this list. They are infrastructure
#: rather than swappable model vendors, and task 0.4 confines the storage client
#: to its own wrapper. Add a vendor here when an adapter for it is written.
VENDOR_SDKS = frozenset(
    {
        "anthropic",
        "elevenlabs",
        "fal",
        "fal_client",
        "google",
        "heygen",
        "openai",
        "replicate",
        "runwayml",
    }
)

#: The only package allowed to import one.
VENDOR_SDK_HOME = "app.providers"


def _pyproject_list(*path: str) -> list[str]:
    """A list of strings from pyproject.toml, by key path.

    Typed narrowing rather than `# type: ignore` at each call site: tomllib
    returns `Any`-ish nested dicts, and scattering ignores through the
    assertions hides the next real error among them. This one did — a wrong
    error code slipped past an older mypy and was caught by a newer one.
    """
    with (REPO / "pyproject.toml").open("rb") as fh:
        node: object = tomllib.load(fh)
    for key in path:
        assert isinstance(node, dict), f"pyproject.toml: {'.'.join(path)} is not a table"
        node = node[key]
    assert isinstance(node, list) and all(isinstance(item, str) for item in node), (
        f"pyproject.toml: {'.'.join(path)} is not a list of strings"
    )
    return [str(item) for item in node]


def _app_source_files() -> list[Path]:
    return sorted((REPO / "app").rglob("*.py")) + sorted((REPO / "workers").rglob("*.py"))


def _module_of(path: Path) -> str:
    rel = path.relative_to(REPO).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_roots(path: Path) -> set[str]:
    """Top-level module names imported by a file, via the AST.

    Parsed rather than grepped so that a vendor named in a docstring or a comment
    — which several of these packages do, describing what belongs where — is not
    mistaken for an import.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("dotted", APP_PACKAGES)
def test_package_exists_and_imports(dotted: str) -> None:
    """The layout on disk is the layout BUILD_PLAN specifies, and it is importable."""
    init = REPO / Path(dotted.replace(".", "/")) / "__init__.py"
    assert init.is_file(), f"{dotted} is in BUILD_PLAN Section 3 but has no __init__.py"
    assert importlib.import_module(dotted).__doc__, f"{dotted} should say what belongs in it"


@pytest.mark.parametrize("dotted", APP_PACKAGES)
def test_package_is_declared_for_distribution(dotted: str) -> None:
    """A package missing from pyproject imports in the repo and vanishes once installed.

    The failure surfaces as an ImportError in a deployed container and nowhere
    else, which is the worst place to find it.
    """
    declared = _pyproject_list("tool", "setuptools", "packages")
    assert dotted in declared, f"{dotted} exists but is not in [tool.setuptools] packages"


def test_type_checking_covers_the_production_code() -> None:
    """`app` and `workers` are type-checked, not just the spike harness."""
    files = _pyproject_list("tool", "mypy", "files")
    assert "app" in files and "workers" in files


def test_no_vendor_sdk_outside_the_providers_package() -> None:
    """CLAUDE.md: no vendor SDK outside `app/providers/`.

    An adapter is what makes a provider swappable and a call testable. A pipeline
    module that reaches for a vendor client directly defeats both, and the damage
    is only visible when the provider has to change — which, in this project,
    it already has: the video model that renders golf is not the one the spike
    started on.
    """
    offenders: list[str] = []
    for path in _app_source_files():
        module = _module_of(path)
        if module == VENDOR_SDK_HOME or module.startswith(f"{VENDOR_SDK_HOME}."):
            continue
        for vendor in sorted(_imported_roots(path) & VENDOR_SDKS):
            offenders.append(f"{path.relative_to(REPO)} imports {vendor}")
    assert not offenders, (
        "vendor SDKs may only be imported inside app/providers/:\n  " + "\n  ".join(offenders)
    )


def test_every_app_module_is_a_package_member() -> None:
    """No stray module outside a declared package — it would not be installed."""
    declared = set(_pyproject_list("tool", "setuptools", "packages"))
    orphans = [
        str(path.relative_to(REPO))
        for path in _app_source_files()
        if _module_of(path).rsplit(".", 1)[0] not in declared and _module_of(path) not in declared
    ]
    assert not orphans, f"modules in no declared package: {orphans}"


def test_every_credential_is_documented_in_env_example() -> None:
    """CLAUDE.md: "Secrets from environment only. Keep `.env.example` current."

    `.env.example` is the only place someone can find out what the system reads
    without reading the code, which makes it exactly the kind of file that goes
    stale quietly. `config/providers.yaml` names the variables; this asserts the
    two agree.
    """
    import yaml

    providers = yaml.safe_load((REPO / "config" / "providers.yaml").read_text())
    documented = {
        line.split("=", 1)[0].strip()
        for line in (REPO / ".env.example").read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    named = set(providers.get("credentials", {}).values())
    assert named, "providers.yaml should name the environment variables it needs"
    missing = sorted(named - documented)
    assert not missing, f"named in providers.yaml but absent from .env.example: {missing}"
