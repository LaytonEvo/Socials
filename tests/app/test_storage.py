"""Task 0.4 — the object storage wrapper.

The S3 backend is tested with `botocore.stub.Stubber` rather than a hand-written
mock. Stubber validates every call against botocore's own service model, so a
misspelled parameter or a wrong shape fails here instead of passing against a
mock that believes whatever it is told. It needs no new dependency and no network.

`moto` would give a fuller fake bucket, but it is another dependency to pin and
CLAUDE.md says to ask before adding one. Stubber covers what this wrapper actually
does — which is construct the right calls — so the extra dependency is not earned.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import boto3
import pytest
from botocore.config import Config
from botocore.stub import Stubber

from app.storage import (
    DEFAULT_PRESIGN_SECONDS,
    KINDS,
    InvalidStorageKey,
    MemoryStorage,
    ObjectNotFound,
    S3Storage,
    StorageBackend,
    StorageError,
    StorageNotConfigured,
    WouldOverwrite,
    from_env,
    key_for,
    persona_of,
    persona_prefix,
)

PERSONA = "550e8400-e29b-41d4-a716-446655440000"
OTHER_PERSONA = "11111111-2222-3333-4444-555555555555"


# ------------------------------------------------------- namespacing by persona --
def test_a_key_lives_under_its_persona() -> None:
    key = key_for(PERSONA, "keyframe", "shot01.png")
    assert key == f"persona/{PERSONA}/keyframe/shot01.png"
    assert key.startswith(persona_prefix(PERSONA) + "/")


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../etc/passwd",
        "..",
        "a/b",
        "/absolute",
        ".hidden",
        "",
        "x" * 300,
        "name with spaces",
        "semi;colon",
        "back\\slash",
    ],
)
def test_no_name_can_escape_the_namespace(hostile: str) -> None:
    """Names reach this code from provider filenames and shot descriptions.

    So the prefix has to be a guarantee, not a convention. Nothing is sanitised
    into a different key either: a silent rewrite means the key in the database and
    the key in the bucket differ, and the row becomes a dangling pointer.
    """
    with pytest.raises(InvalidStorageKey):
        key_for(PERSONA, "render", hostile)


def test_a_persona_id_must_be_a_uuid() -> None:
    """The prefix has to be a value nobody can choose, or it is not a boundary."""
    with pytest.raises(InvalidStorageKey, match="not a UUID"):
        key_for("../other", "render", "x.mp4")


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(InvalidStorageKey, match="unknown kind"):
        key_for(PERSONA, "invoices", "x.pdf")


def test_every_kind_maps_to_something_that_stores_a_key() -> None:
    """Each kind corresponds to a table column naming a storage key."""
    assert {"reference", "keyframe", "take", "voice", "render", "manifest", "export"} == KINDS


def test_two_personas_cannot_collide() -> None:
    a = key_for(PERSONA, "render", "final.mp4")
    b = key_for(OTHER_PERSONA, "render", "final.mp4")
    assert a != b
    assert persona_of(a) != persona_of(b)


def test_a_key_that_is_not_namespaced_is_rejected() -> None:
    with pytest.raises(InvalidStorageKey, match="not persona-namespaced"):
        persona_of("uploads/whatever.mp4")


def test_the_prefix_is_the_unit_of_erasure() -> None:
    """ADR 0002 Finding 4: reference imagery is Article 9 biometric data.

    Deleting one persona has to be a prefix operation rather than a search, so
    every key that persona owns must sit under exactly this string.
    """
    prefix = persona_prefix(PERSONA)
    for kind in sorted(KINDS):
        assert key_for(PERSONA, kind, "object.bin").startswith(prefix + "/")


# ------------------------------------------------------------- the memory backend --
@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def test_the_memory_backend_satisfies_the_protocol(storage: MemoryStorage) -> None:
    assert isinstance(storage, StorageBackend)


def test_upload_then_download_round_trips(storage: MemoryStorage) -> None:
    key = key_for(PERSONA, "take", "shot01-take1.mp4")
    assert storage.put(key, b"video bytes", content_type="video/mp4") == key
    assert storage.get(key) == b"video bytes"
    assert storage.exists(key)


def test_downloading_a_missing_object_raises(storage: MemoryStorage) -> None:
    with pytest.raises(ObjectNotFound):
        storage.get(key_for(PERSONA, "take", "never-written.mp4"))


def test_media_is_write_once_by_default(storage: MemoryStorage) -> None:
    """A row keeps its provenance while the bytes change underneath it.

    Every render, generation and reference_asset row names a key, and Section 4
    requires each artefact trace to the exact prompt, model and seed that produced
    it. Replacing the bytes silently breaks that and nothing downstream can tell.
    """
    key = key_for(PERSONA, "render", "final.mp4")
    storage.put(key, b"first", content_type="video/mp4")
    with pytest.raises(WouldOverwrite, match="write-once"):
        storage.put(key, b"second", content_type="video/mp4")
    assert storage.get(key) == b"first"


def test_overwrite_is_possible_when_asked_for(storage: MemoryStorage) -> None:
    key = key_for(PERSONA, "render", "final.mp4")
    storage.put(key, b"first", content_type="video/mp4")
    storage.put(key, b"second", content_type="video/mp4", overwrite=True)
    assert storage.get(key) == b"second"


def test_a_backend_refuses_a_key_outside_a_persona(storage: MemoryStorage) -> None:
    """Belt and braces: the check is in the key builder AND at the write."""
    with pytest.raises(InvalidStorageKey):
        storage.put("loose/object.mp4", b"x", content_type="video/mp4")


def test_listing_a_prefix_finds_one_personas_objects(storage: MemoryStorage) -> None:
    mine = [key_for(PERSONA, "take", f"take{n}.mp4") for n in range(3)]
    theirs = key_for(OTHER_PERSONA, "take", "take0.mp4")
    for key in [*mine, theirs]:
        storage.put(key, b"x", content_type="video/mp4")

    listed = storage.list_prefix(persona_prefix(PERSONA))
    assert sorted(listed) == sorted(mine)
    assert theirs not in listed


def test_deleting_is_idempotent(storage: MemoryStorage) -> None:
    key = key_for(PERSONA, "take", "x.mp4")
    storage.put(key, b"x", content_type="video/mp4")
    storage.delete(key)
    storage.delete(key)
    assert not storage.exists(key)


# ------------------------------------------------------------------- presigning --
def test_presigning_a_missing_object_raises(storage: MemoryStorage) -> None:
    with pytest.raises(ObjectNotFound):
        storage.presign_get(key_for(PERSONA, "keyframe", "absent.png"))


def test_the_default_expiry_is_short(storage: MemoryStorage) -> None:
    """A presigned URL is a bearer token. A provider needs one generation, not a week."""
    assert DEFAULT_PRESIGN_SECONDS == 15 * 60


@pytest.mark.parametrize("expires_in", [0, -1, 8 * 24 * 60 * 60])
def test_an_impossible_expiry_is_refused_by_both_backends(
    storage: MemoryStorage, expires_in: int
) -> None:
    """The fake must not accept what the real bucket would reject.

    A permissive fake lets the bug reach the one environment that charges for it.
    """
    key = key_for(PERSONA, "keyframe", "x.png")
    storage.put(key, b"x", content_type="image/png")
    with pytest.raises(StorageError):
        storage.presign_get(key, expires_in=expires_in)

    with pytest.raises(StorageError):
        _stubbed().presign_get(key, expires_in=expires_in)


# -------------------------------------------------------------- the S3 backend --
def _stubbed() -> S3Storage:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(signature_version="s3v4"),
    )
    return S3Storage("test-bucket", client=client)


@pytest.fixture
def s3() -> Iterator[tuple[S3Storage, Stubber]]:
    backend = _stubbed()
    with Stubber(backend._client) as stubber:
        yield backend, stubber
        stubber.assert_no_pending_responses()


def test_put_sends_the_bucket_key_and_content_type(s3: tuple[S3Storage, Stubber]) -> None:
    backend, stubber = s3
    key = key_for(PERSONA, "keyframe", "shot01.png")
    stubber.add_client_error("head_object", service_error_code="404")
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "test-bucket", "Key": key, "Body": b"png", "ContentType": "image/png"},
    )
    assert backend.put(key, b"png", content_type="image/png") == key


def test_put_checks_for_an_existing_object_first(s3: tuple[S3Storage, Stubber]) -> None:
    backend, stubber = s3
    key = key_for(PERSONA, "render", "final.mp4")
    stubber.add_response("head_object", {"ContentLength": 9}, {"Bucket": "test-bucket", "Key": key})
    with pytest.raises(WouldOverwrite):
        backend.put(key, b"new", content_type="video/mp4")


def test_a_missing_key_reads_as_not_found_not_as_an_aws_error(
    s3: tuple[S3Storage, Stubber],
) -> None:
    backend, stubber = s3
    key = key_for(PERSONA, "take", "gone.mp4")
    stubber.add_client_error("get_object", service_error_code="NoSuchKey")
    with pytest.raises(ObjectNotFound):
        backend.get(key)


def test_exists_is_false_for_a_missing_key(s3: tuple[S3Storage, Stubber]) -> None:
    backend, stubber = s3
    stubber.add_client_error("head_object", service_error_code="404")
    assert backend.exists(key_for(PERSONA, "take", "gone.mp4")) is False


def test_an_unexpected_aws_error_is_not_swallowed(s3: tuple[S3Storage, Stubber]) -> None:
    """Access denied is not "no object here", and must not be reported as one."""
    from botocore.exceptions import ClientError

    backend, stubber = s3
    stubber.add_client_error("head_object", service_error_code="AccessDenied")
    with pytest.raises(ClientError):
        backend.exists(key_for(PERSONA, "take", "x.mp4"))


def test_listing_follows_pagination(s3: tuple[S3Storage, Stubber]) -> None:
    """list_objects_v2 caps at 1000 keys.

    Code that ignores the continuation token works perfectly until a persona has
    1001 objects — and this is the erasure path, where a silent truncation means
    data left behind.
    """
    backend, stubber = s3
    prefix = persona_prefix(PERSONA)
    stubber.add_response(
        "list_objects_v2",
        {
            "Contents": [{"Key": f"{prefix}/take/a.mp4"}],
            "IsTruncated": True,
            "NextContinuationToken": "page2",
        },
        {"Bucket": "test-bucket", "Prefix": prefix},
    )
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": f"{prefix}/take/b.mp4"}], "IsTruncated": False},
        {"Bucket": "test-bucket", "Prefix": prefix, "ContinuationToken": "page2"},
    )
    assert backend.list_prefix(prefix) == [f"{prefix}/take/a.mp4", f"{prefix}/take/b.mp4"]


def test_a_presigned_url_carries_an_expiry_and_a_v4_signature() -> None:
    backend = _stubbed()
    url = backend.presign_get(key_for(PERSONA, "keyframe", "x.png"), expires_in=300)
    assert "X-Amz-Expires=300" in url
    assert "X-Amz-Signature=" in url
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url
    assert PERSONA in url


# --------------------------------------------------------------- configuration --
def test_no_bucket_means_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("S3_BUCKET", raising=False)
    with pytest.raises(StorageNotConfigured, match="no default"):
        from_env()


def test_the_memory_backend_can_be_selected_by_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """So an offline pipeline run needs no cloud and no special code path."""
    monkeypatch.setenv("S3_BUCKET", "memory")
    assert from_env().name == "memory"


def test_a_real_bucket_name_selects_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "persona-studio-media")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    backend = from_env()
    assert backend.name == "s3"


def test_keys_are_stable_for_the_same_inputs() -> None:
    """The database stores the key, so the builder cannot be time- or random-dependent."""
    first = key_for(PERSONA, "take", "shot01", "take2.mp4")
    second = key_for(uuid.UUID(PERSONA), "take", "shot01", "take2.mp4")
    assert first == second
