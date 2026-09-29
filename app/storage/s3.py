"""The S3-compatible backend. The ONLY module that imports boto3.

BUILD_PLAN Section 3 specifies an S3-compatible bucket, which is what Railway's
own bucket offers and what every alternative offers too, so one client covers all
of them. Confining it here is the same rule CLAUDE.md applies to model vendors:
`tests/app/test_scaffold.py` enforces that boto3 appears nowhere else.
"""

from __future__ import annotations

import os
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .backend import DEFAULT_PRESIGN_SECONDS, check_expiry
from .errors import ObjectNotFound, StorageNotConfigured, WouldOverwrite
from .keys import persona_of

#: boto3 clients are built at runtime and carry no static type. `boto3-stubs[s3]`
#: would type them, and is deliberately not added: the calls in this module are
#: verified in tests by `botocore.stub.Stubber`, which validates each one against
#: botocore's own service model — so a misspelled parameter already fails, and a
#: dependency to satisfy one annotation is not earned.
S3Client = Any

BUCKET_VAR = "S3_BUCKET"
ENDPOINT_VAR = "S3_ENDPOINT_URL"
REGION_VAR = "S3_REGION"

#: Keys that mean "no object here" rather than "something went wrong".
_MISSING = {"404", "NoSuchKey", "NotFound"}


class S3Storage:
    """Upload, download and presign against an S3-compatible bucket."""

    name = "s3"

    def __init__(self, bucket: str, client: S3Client | None = None) -> None:
        self.bucket = bucket
        self._client = client or _make_client()

    def put(self, key: str, data: bytes, *, content_type: str, overwrite: bool = False) -> str:
        persona_of(key)
        if not overwrite and self.exists(key):
            raise WouldOverwrite(
                f"s3://{self.bucket}/{key} already exists. Media is write-once: a row "
                f"naming this key would keep its provenance while the bytes changed "
                f"underneath it. Pass overwrite=True if that is genuinely what you mean."
            )
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                raise ObjectNotFound(f"s3://{self.bucket}/{key}") from exc
            raise
        body: bytes = response["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def list_prefix(self, prefix: str) -> list[str]:
        """Every key under a prefix, following pagination.

        Paginated deliberately: `list_objects_v2` returns at most 1000 keys and
        sets a continuation token, and code that ignores it works perfectly until
        a persona has 1001 objects. This is also the erasure path
        (`persona_prefix`), where a silent truncation means data left behind.
        """
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)

    def presign_get(self, key: str, *, expires_in: int = DEFAULT_PRESIGN_SECONDS) -> str:
        check_expiry(expires_in)
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url


def _is_missing(exc: ClientError) -> bool:
    return str(exc.response.get("Error", {}).get("Code", "")) in _MISSING


def _make_client() -> S3Client:
    """Build a client from the environment. Credentials never come from code.

    `endpoint_url` is optional and set for a non-AWS bucket. The signature version
    is pinned to v4 because presigned URLs under v2 do not expire the way the
    presign code above assumes.
    """
    endpoint = os.environ.get(ENDPOINT_VAR, "").strip() or None
    region = os.environ.get(REGION_VAR, "").strip() or None
    client: S3Client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )
    return client


def bucket_from_env() -> str:
    bucket = os.environ.get(BUCKET_VAR, "").strip()
    if not bucket:
        raise StorageNotConfigured(
            f"{BUCKET_VAR} is not set. There is no default: writing media into whichever "
            f"bucket happened to be configured is not a recoverable mistake. See "
            f".env.example."
        )
    return bucket
