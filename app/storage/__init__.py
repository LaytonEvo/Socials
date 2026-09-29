"""Object storage — task 0.4.

The database stores keys, never blobs (BUILD_PLAN Section 3), so this is where
every generated artefact actually lives: master stills, keyframes, takes, voice
lines, renders, C2PA manifests and platform exports.

Keys are namespaced by persona, and that is a guarantee rather than a convention —
see `app.storage.keys`. It is also the unit of erasure, which matters because
ADR 0002 Finding 4 records reference imagery as Article 9 biometric data.
"""

from __future__ import annotations

import os

from .backend import DEFAULT_PRESIGN_SECONDS, MAX_PRESIGN_SECONDS, StorageBackend
from .errors import (
    InvalidStorageKey,
    ObjectNotFound,
    StorageError,
    StorageNotConfigured,
    WouldOverwrite,
)
from .keys import KINDS, key_for, persona_of, persona_prefix
from .memory import MemoryStorage
from .s3 import BUCKET_VAR, S3Storage, bucket_from_env

__all__ = [
    "BUCKET_VAR",
    "DEFAULT_PRESIGN_SECONDS",
    "KINDS",
    "MAX_PRESIGN_SECONDS",
    "InvalidStorageKey",
    "MemoryStorage",
    "ObjectNotFound",
    "S3Storage",
    "StorageBackend",
    "StorageError",
    "StorageNotConfigured",
    "WouldOverwrite",
    "bucket_from_env",
    "from_env",
    "key_for",
    "persona_of",
    "persona_prefix",
]


def from_env() -> StorageBackend:
    """The backend the environment describes.

    `S3_BUCKET=memory` selects the in-memory backend, so an offline pipeline run
    needs no cloud and no special code path. Anything else is a real bucket.
    """
    if os.environ.get(BUCKET_VAR, "").strip() == "memory":
        return MemoryStorage()
    return S3Storage(bucket_from_env())
