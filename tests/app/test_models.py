"""Task 0.3 — the constraints, asserted against a real database.

BUILD_PLAN Section 4 is explicit about what "constraints tested" means: a test per
constraint that asserts the bad row is **rejected by the database**. A test that
only exercises the happy path does not satisfy it, and neither does one that
checks the application refuses to write the row — the whole point of putting these
in the schema is that they hold when the application is wrong.

So every test here writes raw SQL. Going through the ORM would test the ORM's
validation, which is not what is being claimed.
"""

from __future__ import annotations

import pytest
import yaml
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import EMBEDDING_DIM

from .conftest import REPO, requires_db

pytestmark = requires_db


def _insert(conn: Connection, sql: str, **params: object) -> str:
    """Insert one row and return its id, as a string."""
    return str(conn.execute(text(sql + " RETURNING id"), params).scalar_one())


def _make_piece(conn: Connection, persona_id: str) -> str:
    return _insert(
        conn,
        "INSERT INTO content_piece (persona_id, brief, format) VALUES (:p, 'b', 'reaction')",
        p=persona_id,
    )


def _make_shot(conn: Connection, persona_id: str) -> str:
    return _insert(
        conn,
        "INSERT INTO shot (content_piece_id, order_index, description, duration_s, shot_type) "
        "VALUES (:c, 1, 'd', 5, 'face')",
        c=_make_piece(conn, persona_id),
    )


def _make_generation(conn: Connection, persona_id: str) -> str:
    return _insert(
        conn,
        "INSERT INTO generation (shot_id, provider, model, prompt, duration_s, cost_usd) "
        "VALUES (:s, 'fal', 'm', 'p', 5, 0.06)",
        s=_make_shot(conn, persona_id),
    )


def _fails(conn: Connection, sql: str, **params: object) -> str:
    """Assert the database rejects a statement, and return the message it gave.

    Wrapped in a savepoint so the rejection does not poison the surrounding
    transaction and the test can carry on inspecting.
    """
    savepoint = conn.begin_nested()
    try:
        conn.execute(text(sql), params)
    except (IntegrityError, DBAPIError) as exc:
        savepoint.rollback()
        return str(exc.orig) if exc.orig else str(exc)
    savepoint.rollback()
    pytest.fail(f"the database ACCEPTED a row it should have refused:\n{sql}")


# ------------------------------------------- [A4] disclosure, in the schema --
def test_a_publication_cannot_reference_an_undisclosed_render(
    conn: Connection, undisclosed_render: str
) -> None:
    """The constraint amendment A4 exists for, and the reason it is a composite FK.

    CLAUDE.md forbids a code path that skips disclosure. This asserts the database
    itself has no such path: the composite foreign key has nothing to resolve
    against when the render's flag is false.
    """
    message = _fails(
        conn,
        "INSERT INTO publication (render_id, disclosure_applied, platform, account, "
        "ai_label_set, approved_by) "
        "VALUES (:r, true, 'youtube', '@test', true, 'Layton')",
        r=undisclosed_render,
    )
    assert "fk_publication_render_disclosed" in message


def test_a_publication_cannot_claim_disclosure_the_render_lacks(
    conn: Connection, undisclosed_render: str
) -> None:
    """The obvious way round it — lie in the publication row — is also refused.

    Setting `disclosure_applied` false to match the render trips the CHECK;
    setting it true trips the foreign key. There is no third option, which is what
    makes the invalid state unrepresentable rather than merely unlikely.
    """
    message = _fails(
        conn,
        "INSERT INTO publication (render_id, disclosure_applied, platform, account, "
        "ai_label_set, approved_by) "
        "VALUES (:r, false, 'youtube', '@test', true, 'Layton')",
        r=undisclosed_render,
    )
    assert "ck_publication_disclosure_applied" in message


def test_a_publication_against_a_disclosed_render_is_accepted(
    conn: Connection, disclosed_render: str
) -> None:
    """The happy path, so the constraint is proved to be discriminating."""
    assert _insert(
        conn,
        "INSERT INTO publication (render_id, disclosure_applied, platform, account, "
        "ai_label_set, approved_by) VALUES (:r, true, 'youtube', '@test', true, 'Layton')",
        r=disclosed_render,
    )


# --------------------------------------- no publishing without a human --
def test_a_publication_requires_the_ai_label(conn: Connection, disclosed_render: str) -> None:
    message = _fails(
        conn,
        "INSERT INTO publication (render_id, disclosure_applied, platform, account, "
        "ai_label_set, approved_by) "
        "VALUES (:r, true, 'youtube', '@test', false, 'Layton')",
        r=disclosed_render,
    )
    assert "ck_publication_ai_label_set" in message


def test_a_publication_requires_a_named_approver(conn: Connection, disclosed_render: str) -> None:
    message = _fails(
        conn,
        "INSERT INTO publication (render_id, disclosure_applied, platform, account, "
        "ai_label_set, approved_by) "
        "VALUES (:r, true, 'youtube', '@test', true, NULL)",
        r=disclosed_render,
    )
    assert "approved_by" in message


def test_an_approver_cannot_be_whitespace(conn: Connection, disclosed_render: str) -> None:
    """NOT NULL alone would accept ''. A blank approver is not a named human."""
    message = _fails(
        conn,
        "INSERT INTO publication (render_id, disclosure_applied, platform, account, "
        "ai_label_set, approved_by) "
        "VALUES (:r, true, 'youtube', '@test', true, '   ')",
        r=disclosed_render,
    )
    assert "ck_publication_approver_named" in message


def test_a_manifest_cannot_exist_without_disclosure(conn: Connection, persona_id: str) -> None:
    """Signing happens after the overlay pass, so the reverse order is impossible."""
    piece = _make_piece(conn, persona_id)
    message = _fails(
        conn,
        "INSERT INTO render (content_piece_id, aspect, disclosure_applied, c2pa_manifest_key) "
        "VALUES (:c, '9:16', false, 'manifests/x.c2pa')",
        c=piece,
    )
    assert "ck_render_manifest_requires_disclosure" in message


# ------------------------------------------------ [A3] embedding provenance --
def test_an_embedding_cannot_be_stored_without_its_model(conn: Connection, persona_id: str) -> None:
    """A vector with no model is a number with no meaning.

    This is what makes re-calibration enforceable instead of remembered: a stored
    vector always says which scorer and which version produced it, so a change to
    either is detectable rather than silent.
    """
    vector = "[" + ",".join(["0.1"] * EMBEDDING_DIM) + "]"
    message = _fails(
        conn,
        "INSERT INTO reference_asset (persona_id, kind, storage_key, embedding) "
        "VALUES (:p, 'face', 'k', CAST(:v AS vector))",
        p=persona_id,
        v=vector,
    )
    assert "ck_reference_asset_embedding_has_provenance" in message


def test_an_embedding_with_provenance_is_accepted(conn: Connection, persona_id: str) -> None:
    vector = "[" + ",".join(["0.1"] * EMBEDDING_DIM) + "]"
    assert _insert(
        conn,
        "INSERT INTO reference_asset (persona_id, kind, storage_key, embedding, "
        "embedding_model, embedding_model_version) "
        "VALUES (:p, 'face', 'k', CAST(:v AS vector), 'dlib_resnet', 'v1')",
        p=persona_id,
        v=vector,
    )


def test_a_wrong_length_vector_is_refused(conn: Connection, persona_id: str) -> None:
    """The dimension is pinned by the migration, so a different scorer cannot write."""
    wrong = "[" + ",".join(["0.1"] * (EMBEDDING_DIM + 1)) + "]"
    message = _fails(
        conn,
        "INSERT INTO reference_asset (persona_id, kind, storage_key, embedding, "
        "embedding_model, embedding_model_version) "
        "VALUES (:p, 'face', 'k', CAST(:v AS vector), 'other', 'v1')",
        p=persona_id,
        v=wrong,
    )
    assert "dimensions" in message.lower() or "expected" in message.lower()


def test_the_pinned_dimension_matches_the_configured_scorer() -> None:
    """Amendment A3 pins the dimension to the chosen model. This stops them drifting.

    Changing the scorer is meant to be a migration, not a config edit, and this is
    the test that makes a config-only change fail loudly.
    """
    providers = yaml.safe_load((REPO / "config" / "providers.yaml").read_text())
    assert providers["embedder"]["dim"] == EMBEDDING_DIM


# --------------------------------------------- [A2] a failed call still costs --
def test_a_job_can_exist_with_no_generation(conn: Connection) -> None:
    """The case that was unrepresentable before amendment A2.

    A call that timed out after billing produced no `generation` row, so its cost
    had nowhere to live and the ledger was quietly incomplete.
    """
    assert _insert(
        conn,
        "INSERT INTO job (provider, status, cost_usd, error, completed_at) "
        "VALUES ('fal', 'timed_out', 0.075, 'no response after 300s', now())",
    )


def test_a_finished_job_must_state_its_cost(conn: Connection) -> None:
    """ "We do not know what it cost" is not a state the schema offers."""
    message = _fails(
        conn,
        "INSERT INTO job (provider, status, completed_at) VALUES ('fal', 'failed', now())",
    )
    assert "ck_job_finished_has_cost" in message


def test_an_in_flight_job_need_not_state_a_cost(conn: Connection) -> None:
    """Because it is not known yet, which is different from not being recorded."""
    assert _insert(conn, "INSERT INTO job (provider, status) VALUES ('fal', 'running')")


def test_a_job_cannot_complete_before_it_was_submitted(conn: Connection) -> None:
    message = _fails(
        conn,
        "INSERT INTO job (provider, status, submitted_at, completed_at, cost_usd) "
        "VALUES ('fal', 'succeeded', now(), now() - interval '1 hour', 0)",
    )
    assert "ck_job_completed_after_submitted" in message


# ------------------------------------------------------------ vocabularies --
@pytest.mark.parametrize(
    ("sql", "constraint"),
    [
        (
            "INSERT INTO persona (name, status) VALUES ('x', 'lapsed')",
            "ck_status_vocabulary",
        ),
        (
            "INSERT INTO job (provider, status, cost_usd) VALUES ('fal', 'exploded', 0)",
            "ck_status_vocabulary",
        ),
        (
            "INSERT INTO cost_ledger (ref_table, ref_id, provider, units, unit_price, total_usd) "
            "VALUES ('invoice', gen_random_uuid(), 'fal', 1, 1, 1)",
            "ck_ref_table_vocabulary",
        ),
    ],
)
def test_an_unknown_vocabulary_value_is_refused(
    conn: Connection, sql: str, constraint: str
) -> None:
    assert constraint in _fails(conn, sql)


def test_an_unknown_aspect_is_refused(conn: Connection, persona_id: str) -> None:
    """Platform cuts are 9:16, 16:9 and 1:1 (task 3.12). Nothing else ships."""
    piece = _make_piece(conn, persona_id)
    assert "ck_aspect_vocabulary" in _fails(
        conn,
        "INSERT INTO render (content_piece_id, aspect) VALUES (:c, '4:3')",
        c=piece,
    )


# ------------------------------------------------------- scores and ratings --
def test_a_similarity_above_one_is_refused(conn: Connection, persona_id: str) -> None:
    """A cosine similarity outside 0..1 means the scorer changed or the vector
    was not normalised, and both are worth catching at write time."""
    piece = _make_piece(conn, persona_id)
    assert "unit_range" in _fails(
        conn,
        "INSERT INTO render (content_piece_id, aspect, identity_score_mean) "
        "VALUES (:c, '9:16', 1.4)",
        c=piece,
    )


def test_a_minimum_score_above_the_mean_is_refused(conn: Connection, persona_id: str) -> None:
    shot = _make_shot(conn, persona_id)
    assert "ck_generation_min_not_above_mean" in _fails(
        conn,
        "INSERT INTO generation (shot_id, provider, model, prompt, duration_s, cost_usd, "
        "identity_score_min, identity_score_mean) "
        "VALUES (:s, 'fal', 'm', 'p', 5, 0.06, 0.99, 0.80)",
        s=shot,
    )


def test_a_rating_outside_one_to_five_is_refused(conn: Connection, persona_id: str) -> None:
    generation = _make_generation(conn, persona_id)
    assert "ck_review_rating_range" in _fails(
        conn,
        "INSERT INTO review (generation_id, reviewer, decision, rating) "
        "VALUES (:g, 'Layton', 'reject', 0)",
        g=generation,
    )


def test_operator_time_cannot_be_negative(conn: Connection, persona_id: str) -> None:
    """[A1] The measurement Section 9 says decides viability."""
    generation = _make_generation(conn, persona_id)
    assert "ck_review_time_not_negative" in _fails(
        conn,
        "INSERT INTO review (generation_id, reviewer, decision, time_spent_s) "
        "VALUES (:g, 'Layton', 'accept', -60)",
        g=generation,
    )


def test_a_negative_cost_is_refused(conn: Connection, persona_id: str) -> None:
    shot = _make_shot(conn, persona_id)
    assert "ck_generation_cost_not_negative" in _fails(
        conn,
        "INSERT INTO generation (shot_id, provider, model, prompt, duration_s, cost_usd) "
        "VALUES (:s, 'fal', 'm', 'p', 5, -1)",
        s=shot,
    )


# --------------------------------------------------------------- structure --
def test_two_shots_cannot_share_an_order(conn: Connection, persona_id: str) -> None:
    """An ambiguous shot order is an ambiguous edit."""
    piece = _make_piece(conn, persona_id)
    for _ in range(1):
        conn.execute(
            text(
                "INSERT INTO shot (content_piece_id, order_index, description, duration_s, "
                "shot_type) VALUES (:c, 1, 'd', 5, 'face')"
            ),
            {"c": piece},
        )
    assert "uq_shot_order" in _fails(
        conn,
        "INSERT INTO shot (content_piece_id, order_index, description, duration_s, shot_type) "
        "VALUES (:c, 1, 'other', 5, 'broll')",
        c=piece,
    )


def test_a_lora_version_cannot_exist_without_a_licence(conn: Connection, persona_id: str) -> None:
    """CLAUDE.md requires the licence be checked and recorded for any weights."""
    message = _fails(
        conn,
        "INSERT INTO lora_version (persona_id, base_model, dataset_hash, storage_key) "
        "VALUES (:p, 'flux-dev', 'abc', 'k')",
        p=persona_id,
    )
    assert "base_model_licence" in message


def test_a_persona_name_is_unique(conn: Connection, persona_id: str) -> None:
    assert "persona_name_key" in _fails(conn, "INSERT INTO persona (name) VALUES ('Test Persona')")
