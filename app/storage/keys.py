"""Storage keys, namespaced by persona.

Task 0.4's acceptance criterion is "keys namespaced by persona", and the reason is
not tidiness. A key is built from a persona id, a kind, and a caller-supplied
name — and the name reaches this code from a provider's filename, a shot
description, or a platform export. So the namespacing has to be a guarantee
rather than a convention: `key_for` cannot return a key outside
`persona/<uuid>/`, whatever it is given.

GDPR is the other reason. ADR 0002's Finding 4 records that reference imagery is
biometric data under Article 9 and that control sets must stay synthetic. A
per-persona prefix is what makes "delete everything belonging to this persona" a
single prefix operation rather than a search.
"""

from __future__ import annotations

import posixpath
import re
import uuid
from typing import Final

from .errors import InvalidStorageKey

ROOT: Final = "persona"

#: What a key may hold. Each maps to the table whose rows reference it, so an
#: orphaned object can be found by comparing a prefix listing against a query.
KINDS: Final = frozenset(
    {
        "reference",  # reference_asset — the master still set
        "keyframe",  # keyframe
        "take",  # generation
        "voice",  # voice_line
        "render",  # render
        "manifest",  # render.c2pa_manifest_key
        "export",  # platform cuts (task 3.12)
    }
)

#: Deliberately strict. Anything outside this set is rejected rather than
#: sanitised: a silent rewrite means the key in the database and the key in the
#: bucket can differ, and the row is then a dangling pointer nobody notices.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


def _require_uuid(persona_id: str | uuid.UUID) -> str:
    try:
        return str(uuid.UUID(str(persona_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidStorageKey(
            f"persona id {persona_id!r} is not a UUID. The namespace prefix has to be "
            f"a value nobody can choose, or it is not a boundary."
        ) from exc


def key_for(persona_id: str | uuid.UUID, kind: str, *parts: str) -> str:
    """Build a key under `persona/<persona_id>/<kind>/`.

    Every part is validated individually, so a separator or a parent reference
    cannot be smuggled through one of them.
    """
    prefix = persona_prefix(persona_id)
    if kind not in KINDS:
        raise InvalidStorageKey(f"unknown kind {kind!r}; expected one of {sorted(KINDS)}")
    if not parts:
        raise InvalidStorageKey("a key needs at least one name part")
    for part in parts:
        if not isinstance(part, str) or not _SAFE_NAME.match(part):
            raise InvalidStorageKey(
                f"key part {part!r} is not allowed. Parts must match "
                f"{_SAFE_NAME.pattern} — no separators, no parent references, no "
                f"leading dot."
            )
    key = posixpath.join(prefix, kind, *parts)

    # Belt and braces. The checks above should make this unreachable, and it is
    # here anyway because the cost of being wrong is one persona's media written
    # into another's namespace, which no later check would catch.
    normalised = posixpath.normpath(key)
    if normalised != key or not normalised.startswith(f"{prefix}/"):
        raise InvalidStorageKey(f"key {key!r} does not stay inside {prefix}/")
    return key


def persona_prefix(persona_id: str | uuid.UUID) -> str:
    """The prefix holding everything belonging to one persona.

    Also the unit of erasure: deleting this prefix deletes that persona's media.
    """
    return f"{ROOT}/{_require_uuid(persona_id)}"


def persona_of(key: str) -> str:
    """Which persona a key belongs to, for checking a key came from where it claims."""
    parts = key.split("/")
    if len(parts) < 3 or parts[0] != ROOT:
        raise InvalidStorageKey(f"key {key!r} is not persona-namespaced")
    return _require_uuid(parts[1])
