"""The read-only view.

It is read-only by design, so the tests that matter are about what it CANNOT do: change
state, serve a file outside the reference sets, or report a missing ledger as zero.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as c:
        yield c


def test_the_overview_renders(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Mollie" in response.text


def test_health_reports_what_distinguishes_a_working_deployment(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["persona"] == "Mollie"
    assert body["identity_threshold"] == 0.9619
    assert body["budget_mode"] == "observe"


def test_a_reference_still_is_served(client: TestClient) -> None:
    response = client.get("/reference/outfit/outfit-01-b7_00.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


@pytest.mark.parametrize(
    "path",
    [
        "/reference/outfit/../../CLAUDE.md",
        "/reference/outfit/..%2f..%2fCLAUDE.md",
        "/reference/../../etc/passwd",
        "/reference/nonexistent-set/x.png",
        "/reference/outfit/does-not-exist.png",
    ],
)
def test_nothing_outside_the_reference_sets_is_served(client: TestClient, path: str) -> None:
    """Refused rather than sanitised.

    A path rewritten instead of rejected is how a traversal becomes a silent read of
    something else — the same reasoning the storage key builder uses.
    """
    assert client.get(path).status_code in {404, 400}


def test_a_missing_ledger_is_reported_not_shown_as_zero(client: TestClient) -> None:
    """Zero spend and unknown spend are different, and only one of them is reassuring."""
    assert client.get("/api/health").json()["database"] is False
    assert "not reachable" in client.get("/").text


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_view_cannot_change_anything(client: TestClient, method: str) -> None:
    """Read-only by design, so it cannot get publishing or disclosure wrong."""
    assert getattr(client, method)("/").status_code in {404, 405}


# ------------------------------------------------------- the LoRA section --
def test_the_lora_section_survives_the_run_directory_being_absent() -> None:
    """The deployed copy has no spike/runs/, and the section must still render.

    `spike/runs/` is excluded from git and from the deployment build context because it
    holds gigabytes of imagery, so a view that reads its numbers straight from there
    works on a developer checkout and silently loses the whole section once deployed.
    The numbers are bundled at `app/ui/data/lora.json` for exactly this reason.
    """
    from app.api.main import LORA_SUMMARY, _lora_run

    assert LORA_SUMMARY.is_file(), (
        "app/ui/data/lora.json is missing. Run scripts/bundle_lora_summary.py after a "
        "training or evaluation run, or the deployed page loses the LoRA section."
    )
    run = _lora_run()
    assert run is not None
    assert run["artefact"]["steps"] > 0
    assert run["ceiling"] is not None, "without the ceiling the scores cannot be read"
    assert run["runs"], "a LoRA with no evaluation is not something to publish numbers about"


def test_the_bundled_summary_matches_the_run_files() -> None:
    """A stale bundle would show yesterday's numbers as though they were today's."""
    import json

    from app.api.main import LORA_ROOT, LORA_SUMMARY

    if not (LORA_ROOT / "artefact.json").is_file():
        pytest.skip("no local run directory to compare against")
    bundled = json.loads(LORA_SUMMARY.read_text())
    actual = json.loads((LORA_ROOT / "artefact.json").read_text())
    assert bundled["artefact"]["dataset_hash"] == actual["dataset_hash"]
    assert bundled["artefact"]["weights_url"] == actual["weights_url"]
