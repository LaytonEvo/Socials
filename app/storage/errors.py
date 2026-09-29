"""Storage errors."""

from __future__ import annotations


class StorageError(Exception):
    """Base for every storage failure."""


class StorageNotConfigured(StorageError):
    """The bucket or its credentials are missing from the environment."""


class InvalidStorageKey(StorageError):
    """A key that would escape its persona's namespace, or is otherwise malformed."""


class ObjectNotFound(StorageError):
    """No object at that key."""


class WouldOverwrite(StorageError):
    """The key already holds an object and the caller did not ask to replace it.

    Media is write-once by default. Every `render`, `generation` and
    `reference_asset` row names a storage key, and BUILD_PLAN Section 4 requires
    each artefact be traceable to the exact prompt, model and seed that produced
    it. Silently replacing the bytes under a key keeps the row and destroys the
    provenance, and nothing downstream can tell.
    """
