"""An in-memory bucket, for tests and for running the pipeline with no cloud.

Task 0.6 requires the pipeline to run end to end on fakes before a paid call
exists. Storage is part of that path, so it needs a fake too — and one that
enforces the same rules, or the fake passes where the real one would refuse.
"""

from __future__ import annotations

from .backend import DEFAULT_PRESIGN_SECONDS, check_expiry
from .errors import ObjectNotFound, WouldOverwrite
from .keys import persona_of


class MemoryStorage:
    """Holds objects in a dict. Not durable, and not pretending to be."""

    name = "memory"

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, *, content_type: str, overwrite: bool = False) -> str:
        persona_of(key)  # refuse a key that is not persona-namespaced
        if not overwrite and key in self._objects:
            raise WouldOverwrite(
                f"{key} already holds an object. Media is write-once: a row naming this "
                f"key would keep its provenance while the bytes changed underneath it. "
                f"Pass overwrite=True if that is genuinely what you mean."
            )
        self._objects[key] = (data, content_type)
        return key

    def get(self, key: str) -> bytes:
        try:
            return self._objects[key][0]
        except KeyError as exc:
            raise ObjectNotFound(key) from exc

    def exists(self, key: str) -> bool:
        return key in self._objects

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def list_prefix(self, prefix: str) -> list[str]:
        return sorted(key for key in self._objects if key.startswith(prefix))

    def presign_get(self, key: str, *, expires_in: int = DEFAULT_PRESIGN_SECONDS) -> str:
        """A fake URL, validated the same way the real one is.

        It is not fetchable, and it is deliberately not silently permissive: a
        fake that accepts an expiry S3 would reject lets a bug reach the one
        environment that charges for it.
        """
        if key not in self._objects:
            raise ObjectNotFound(key)
        check_expiry(expires_in)
        return f"memory://{key}?expires_in={expires_in}"
