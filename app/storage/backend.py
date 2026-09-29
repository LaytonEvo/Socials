"""The storage protocol.

Two implementations: `S3Storage` for real buckets and `MemoryStorage` for tests
and offline pipeline runs. Same contract, so nothing above this layer knows which
it has — the pattern task 0.6 applies to providers, applied here first.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .errors import StorageError

#: S3 signature v4 refuses a presigned URL valid for longer than seven days.
#: Asking for more is a mistake worth catching locally rather than at the API.
MAX_PRESIGN_SECONDS = 7 * 24 * 60 * 60

#: Short by default. A presigned URL is a bearer token: anyone holding it can read
#: the object. A provider needs it for the length of one generation, not a week.
DEFAULT_PRESIGN_SECONDS = 15 * 60


@runtime_checkable
class StorageBackend(Protocol):
    """Upload, download, presign, and the operations erasure needs."""

    name: str

    def put(self, key: str, data: bytes, *, content_type: str, overwrite: bool = False) -> str:
        """Store bytes and return the key. Refuses an existing key unless told."""
        ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def list_prefix(self, prefix: str) -> list[str]: ...

    def presign_get(self, key: str, *, expires_in: int = DEFAULT_PRESIGN_SECONDS) -> str:
        """A time-limited URL a third party can read the object from.

        This is how a provider is given a keyframe. The spike passed images as
        data URIs and hit a 4 MB cap that made a 2K still unusable as a keyframe
        (docs/reports/wardrobe-keyframes-2026-09-28.md); a presigned URL has no
        such limit, which is the production answer to that failure.
        """
        ...


def check_expiry(expires_in: int) -> None:
    """Refuse an expiry S3 would refuse, before spending a round trip on it.

    Both backends call this, so the fake cannot accept a value the real bucket
    would reject — which is the failure mode that makes a fake worse than no fake.
    """
    if expires_in <= 0:
        raise StorageError(f"expires_in must be positive, got {expires_in}")
    if expires_in > MAX_PRESIGN_SECONDS:
        raise StorageError(
            f"expires_in {expires_in}s exceeds the {MAX_PRESIGN_SECONDS}s signature-v4 "
            f"maximum. A presigned URL is a bearer token; a long one is a leak with a "
            f"long tail."
        )
