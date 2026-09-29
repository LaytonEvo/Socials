"""Task 0.8 — secrets from the environment only.

The acceptance criteria are "no keys in repo" and "`.env.example` documents every
variable". Both are easy to satisfy once and lose quietly, so they are tests rather
than an audit: the first scans every tracked file for key-shaped strings, the second
reads the code to find what it actually consumes and compares the two lists in both
directions.

Both directions matter. Undocumented reads are the failure that costs a deploy — a
variable nobody set because nobody knew about it. Documented-but-unread entries are
the failure that costs trust: a file full of variables that do nothing teaches people
to stop believing it.
"""

from __future__ import annotations

import ast
import functools
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SOURCE_DIRS = ("app", "workers", "scripts")

#: Variables read by a dependency rather than by our own code, so the scanner will
#: never find them. Each needs a reason, because this list is the escape hatch that
#: would otherwise let the completeness check rot.
READ_BY_DEPENDENCIES = {
    "AWS_ACCESS_KEY_ID": "boto3 reads it from the environment itself",
    "AWS_SECRET_ACCESS_KEY": "boto3 reads it from the environment itself",
}

#: Directories allowed to read a provider credential. `app/providers` and
#: `app/storage` are the adapters; a key read anywhere else is a key that cannot be
#: swapped, rotated or faked.
#:
#: `scripts/spike` is the Spike 0 harness, which BUILD_ORDER Section 3 explicitly
#: permits to use vendor SDKs because `app/` did not exist when it was written. It
#: is throwaway and frozen when the spike closes, so it is exempt rather than a
#: violation — but it is named here so the exemption is visible.
CREDENTIAL_READERS = ("app/providers", "app/storage", "scripts/spike")

#: Patterns for credentials that are recognisable on sight. Not exhaustive — no
#: pattern list is — but each of these is a real provider's real format, so a match
#: is a leak rather than a guess.
SECRET_PATTERNS = {
    "Anthropic API key": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "ElevenLabs API key": r"\bsk_[a-f0-9]{32,}\b",
    "AWS access key id": r"\bAKIA[0-9A-Z]{16}\b",
    "GitHub token": r"\bghp_[A-Za-z0-9]{36}\b",
    "GitHub fine-grained token": r"\bgithub_pat_[A-Za-z0-9_]{50,}\b",
    "OpenAI API key": r"\bsk-proj-[A-Za-z0-9_\-]{20,}",
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "fal credential pair": (
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:[0-9a-f]{20,}"
    ),
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9\-]{10,}",
}


#: Extensions skipped by the credential scan. Images, model weights and video are
#: the bulk of this repository by size, and a pasted API key does not live in a PNG.
#: Stated as a limitation rather than left implicit: this scan reads text.
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".mp4",
        ".mov",
        ".mp3",
        ".wav",
        ".dat",
        ".bz2",
        ".gz",
        ".zip",
        ".onnx",
        ".pt",
        ".bin",
        ".pdf",
        ".ico",
    }
)


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    )
    return [REPO / name for name in out.stdout.split("\0") if name]


@functools.cache
def _credential_hits() -> dict[str, list[str]]:
    """Every credential-shaped string in the tracked text files, scanned once.

    Cached and single-pass because the naive version — one pass per pattern — reread
    150 MB of committed images nine times and took 81 seconds.
    """
    compiled = {label: re.compile(pattern) for label, pattern in SECRET_PATTERNS.items()}
    hits: dict[str, list[str]] = {label: [] for label in compiled}
    here = Path(__file__)
    for path in _tracked_files():
        if path == here or path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:  # pragma: no cover
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in compiled.items():
                if pattern.search(line):
                    hits[label].append(f"{path.relative_to(REPO)}:{number}")
    return hits


def _documented_variables() -> set[str]:
    return {
        line.split("=", 1)[0].strip()
        for line in (REPO / ".env.example").read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }


def _source_files() -> list[Path]:
    return [path for directory in SOURCE_DIRS for path in (REPO / directory).rglob("*.py")]


def _environment_reads(path: Path) -> set[str]:
    """Variable names this module reads from the environment.

    Resolves module-level string constants, because every read in this codebase goes
    through one (`REDIS_URL_VAR = "REDIS_URL"`). A scanner that only understood
    literals would report nothing at all and pass, which is worse than not existing.
    """
    tree = ast.parse(path.read_text(), filename=str(path))

    constants: dict[str, str] = {}
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = statement.value.value

    def resolve(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        return None

    found: set[str] = set()
    for node in ast.walk(tree):
        # os.environ["X"]
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "environ"
        ):
            if name := resolve(node.slice):
                found.add(name)
        # os.environ.get("X") and os.getenv("X")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
            func = node.func
            base = func.value
            reads_environ = (isinstance(base, ast.Attribute) and base.attr == "environ") or (
                isinstance(base, ast.Name) and base.id == "os" and func.attr == "getenv"
            )
            if reads_environ and func.attr in {"get", "getenv"} and (name := resolve(node.args[0])):
                found.add(name)
    return found


def _all_environment_reads() -> dict[str, list[str]]:
    reads: dict[str, list[str]] = {}
    for path in _source_files():
        for name in _environment_reads(path):
            reads.setdefault(name, []).append(str(path.relative_to(REPO)))
    return reads


# ------------------------------------------------------------- no keys in repo --
@pytest.mark.parametrize("label", sorted(SECRET_PATTERNS))
def test_no_tracked_file_contains_a_credential(label: str) -> None:
    """Scans every tracked file for a recognisable credential format.

    A one-off audit finds today's leak. This finds tomorrow's, in CI, before it is
    pushed anywhere it cannot be taken back from.
    """
    hits = _credential_hits()[label]
    assert not hits, f"{label} found in tracked files: {hits}"


def test_the_local_env_file_is_ignored() -> None:
    """`.env` holds real values. If it is not ignored, one push publishes them."""
    result = subprocess.run(
        ["git", "check-ignore", "-v", ".env"], cwd=REPO, capture_output=True, text=True
    )
    assert result.returncode == 0, ".env is not gitignored"


def test_no_secret_is_committed_in_a_config_file() -> None:
    """Config names variables; it never holds their values.

    `providers.yaml` maps a service to the variable to read. A value here would be a
    secret in the repository even though it looked like configuration.
    """
    providers = yaml.safe_load((REPO / "config" / "providers.yaml").read_text())
    for service, variable in providers["credentials"].items():
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", variable), (
            f"credentials.{service} should be an environment variable NAME, got {variable!r}"
        )
        for label, pattern in SECRET_PATTERNS.items():
            assert not re.search(pattern, variable), f"credentials.{service} looks like a {label}"


# ------------------------------------------- .env.example documents every variable --
def test_every_variable_the_code_reads_is_documented() -> None:
    """The failure this catches costs a deploy: a variable nobody set, because
    nobody knew it existed."""
    documented = _documented_variables()
    undocumented = {
        name: paths for name, paths in _all_environment_reads().items() if name not in documented
    }
    assert not undocumented, (
        "read from the environment but absent from .env.example:\n  "
        + "\n  ".join(
            f"{name} — {', '.join(paths)}" for name, paths in sorted(undocumented.items())
        )
    )


def test_every_documented_variable_is_actually_used() -> None:
    """The failure this catches costs trust.

    A file listing variables that do nothing teaches people to stop believing it,
    and then the one that matters gets skipped too. Anything read by a dependency
    rather than by us is allowed, with a reason.
    """
    reads = set(_all_environment_reads())
    # A credential named in providers.yaml is legitimately documented before its
    # adapter exists: config declares the variable, and the scaffold test requires
    # .env.example to list it. ANTHROPIC_API_KEY is exactly this today — named for
    # the shot-list generator, which is task 3.1.
    declared = set(
        yaml.safe_load((REPO / "config" / "providers.yaml").read_text())["credentials"].values()
    )
    stale = sorted(_documented_variables() - reads - set(READ_BY_DEPENDENCIES) - declared)
    assert not stale, (
        f"documented in .env.example but never read: {stale}. Either the code that "
        f"read them is gone, or they belong in READ_BY_DEPENDENCIES with a reason."
    )


def test_the_dependency_allowlist_is_still_needed() -> None:
    """If our own code starts reading one of these, it should leave the allowlist.

    An allowlist nobody prunes is how the check above stops meaning anything.
    """
    reads = set(_all_environment_reads())
    redundant = sorted(set(READ_BY_DEPENDENCIES) & reads)
    assert not redundant, (
        f"{redundant} are now read by our own code, so they no longer need an exemption"
    )


def test_the_scanner_finds_the_variables_we_know_about() -> None:
    """Guards the scanner itself.

    Every read in this codebase goes through a module-level constant, so a scanner
    that only understood literals would find nothing and pass — a green test proving
    the opposite of what it claims. These five are known to exist.
    """
    reads = set(_all_environment_reads())
    assert {"DATABASE_URL", "REDIS_URL", "S3_BUCKET", "S3_ENDPOINT_URL", "S3_REGION"} <= reads


def test_no_code_reads_a_credential_directly() -> None:
    """Provider keys are read inside app/providers/ and app/storage/, nowhere else.

    The same confinement the vendor-SDK guard applies: a key read in pipeline code is
    a key that cannot be swapped, rotated or faked.
    """
    credentials = set(
        yaml.safe_load((REPO / "config" / "providers.yaml").read_text())["credentials"].values()
    )
    offenders = [
        f"{path.relative_to(REPO)} reads {name}"
        for path in _source_files()
        for name in _environment_reads(path) & credentials
        if not str(path.relative_to(REPO)).startswith(CREDENTIAL_READERS)
    ]
    assert not offenders, offenders
