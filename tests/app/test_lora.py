"""Task 1.4's machinery: dataset preparation, training, evaluation.

Everything except the paid run. The fake trainer makes the whole path testable offline,
and the real fal trainer is exercised against a mock transport the same way the image
adapter is.

Two rules get most of the attention here because breaking either is silent:

- **the holdout is excluded from the evaluation centroid.** Score against the full
  reference and you compare generated images to pictures the LoRA trained on, which
  measures memorisation and always flatters.
- **the weights may not run off fal** (ADR 0010). Weights in the wrong place produce
  perfectly good images, and nothing about them says the licence was breached.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import zipfile
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.config import LoraSettings, load_all
from app.identity import (
    MIN_HOLDOUT,
    FakeLoraTrainer,
    FalLoraTrainer,
    HoldoutTooSmall,
    LicenceViolation,
    LoraArtefact,
    LoraTrainer,
    Still,
    TrainingRequest,
    build_archive,
    caption_for,
    collect,
    split,
)
from app.identity.dataset import NO_FACE_STILLS, TRAIN_EDGE_PX
from app.providers.types import JobStatus, ProviderError

REPO = Path(__file__).resolve().parents[2]
ROOTS = {k: REPO / "spike" / "data" / k for k in ("master_v2", "outfit", "lighting", "body")}
CONFIG = load_all(REPO / "config")


@pytest.fixture(scope="module")
def stills() -> list[Still]:
    return collect(ROOTS, exclude=NO_FACE_STILLS)


# ------------------------------------------------------------ dataset prep --
def test_the_reference_set_is_collected_whole(stills: list[Still]) -> None:
    """121 — the figure the threshold is calibrated against."""
    assert len(stills) == 121
    assert {s.kind for s in stills} == {"master_v2", "outfit", "lighting", "body"}


def test_the_no_face_stills_are_excluded(stills: list[Still]) -> None:
    """Training a FACE model on images with no face adds noise for nothing."""
    names = {s.path.name for s in stills}
    assert not names & set(NO_FACE_STILLS)
    assert len(collect(ROOTS)) == len(stills) + 3


def test_the_split_is_deterministic(stills: list[Still]) -> None:
    """A `lora_version` row must be reproducible from its dataset_hash.

    Hashed rather than shuffled with a seeded RNG, because an RNG's sequence is not
    promised stable across Python releases and this has to hold for years.
    """
    first = split(stills, trigger_word="MOLLIE")
    second = split(stills, trigger_word="MOLLIE")
    assert first.dataset_hash() == second.dataset_hash()
    assert [s.path for s in first.holdout] == [s.path for s in second.holdout]


def test_the_split_does_not_depend_on_where_the_repo_is_checked_out(
    stills: list[Still],
) -> None:
    """The same images must split the same way from an absolute or a relative path.

    This failed before the split was keyed on `Still.name`: it hashed
    `path.as_posix()`, so an absolute path and a relative one to the same file ranked
    differently and produced different halves. A holdout that changes with the working
    directory cannot validate anything, and the `dataset_hash` recorded on the artefact
    identified the checkout rather than the data.
    """
    relative = [Still(Path(os.path.relpath(s.path, Path.cwd())), s.kind) for s in stills]
    absolute = [Still(s.path.resolve(), s.kind) for s in stills]

    a = split(relative, trigger_word="mollie")
    b = split(absolute, trigger_word="mollie")

    assert [s.name for s in a.holdout] == [s.name for s in b.holdout]
    assert [s.name for s in a.train] == [s.name for s in b.train]
    assert a.dataset_hash() == b.dataset_hash()


def test_the_dataset_hash_survives_a_move(stills: list[Still]) -> None:
    """Provenance that changes when the directory changes identifies nothing."""
    here = split(stills, trigger_word="mollie")
    moved = split(
        [Still(Path("/somewhere/else") / s.kind / s.path.name, s.kind) for s in stills],
        trigger_word="mollie",
    )
    assert here.dataset_hash() == moved.dataset_hash()


def test_a_different_trigger_word_is_a_different_dataset(stills: list[Still]) -> None:
    assert (
        split(stills, trigger_word="A").dataset_hash()
        != split(stills, trigger_word="B").dataset_hash()
    )


def test_the_split_is_stratified_so_every_kind_survives(stills: list[Still]) -> None:
    """A random 15% of 121 can take all three body references.

    Then the holdout says nothing about wider framing, and the evaluation quietly stops
    covering the kind that was hardest to get.
    """
    result = split(stills, trigger_word="MOLLIE")
    for kind in ("master_v2", "outfit", "lighting", "body"):
        assert result.by_kind(result.holdout).get(kind, 0) >= 1, f"{kind} absent from holdout"
        assert result.by_kind(result.train).get(kind, 0) >= 1, f"{kind} absent from training"


def test_nothing_is_in_both_halves(stills: list[Still]) -> None:
    """The entire method depends on this."""
    result = split(stills, trigger_word="MOLLIE")
    assert not {s.path for s in result.train} & {s.path for s in result.holdout}
    assert result.total == len(stills)


def test_a_kind_of_one_is_not_held_out() -> None:
    """A single still contributes nothing to a holdout and is better spent training."""
    lone = [Still(Path("x/only.png"), "rare")]
    result = split(lone, trigger_word="M")
    assert result.holdout == []
    assert len(result.train) == 1


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.1, 1.5])
def test_a_nonsense_holdout_fraction_is_refused(stills: list[Still], fraction: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        split(stills[:20], trigger_word="M", holdout_fraction=fraction)


def test_the_archive_carries_an_image_and_a_caption_for_each(stills: list[Still]) -> None:
    sample = stills[:6]
    with zipfile.ZipFile(io.BytesIO(build_archive(sample, trigger_word="MOLLIE"))) as archive:
        names = set(archive.namelist())
        assert len(names) == len(sample) * 2
        for still in sample:
            assert f"{still.name}.jpg" in names
            assert f"{still.name}.txt" in names
            assert "MOLLIE" in archive.read(f"{still.name}.txt").decode()


def test_archive_images_are_resized_for_training(stills: list[Still]) -> None:
    """FLUX trains at 1024. Larger costs upload and buys nothing."""
    from PIL import Image

    with zipfile.ZipFile(io.BytesIO(build_archive(stills[:3], trigger_word="M"))) as archive:
        for name in [n for n in archive.namelist() if n.endswith(".jpg")]:
            with Image.open(io.BytesIO(archive.read(name))) as image:
                assert max(image.size) <= TRAIN_EDGE_PX


def test_captions_distinguish_the_kinds() -> None:
    """An outfit still should not read as a statement about her face."""
    assert "golf clothing" in caption_for(Still(Path("a.png"), "outfit"), "M")
    assert "full body" in caption_for(Still(Path("a.png"), "body"), "M")
    assert caption_for(Still(Path("a.png"), "unknown-kind"), "M").startswith("a photo of M")


# ---------------------------------------------------------------- training --
@pytest.fixture
def settings() -> LoraSettings:
    return CONFIG.providers.lora


def test_the_fake_trainer_satisfies_the_protocol(settings: LoraSettings) -> None:
    assert isinstance(FakeLoraTrainer(settings=settings), LoraTrainer)


def test_the_real_trainer_satisfies_the_protocol(settings: LoraSettings) -> None:
    assert isinstance(FalLoraTrainer(settings=settings), LoraTrainer)


async def test_a_fake_run_produces_a_versioned_artefact(settings: LoraSettings) -> None:
    trainer = FakeLoraTrainer(settings=settings)
    request = TrainingRequest(
        archive_url="https://example.invalid/set.zip",
        trigger_word="MOLLIE",
        steps=1000,
        dataset_hash="abc123",
    )
    job = await trainer.train(request)
    artefact = await trainer.collect(job)

    assert job.status is JobStatus.SUCCEEDED
    assert artefact.dataset_hash == "abc123"
    assert artefact.steps == 1000
    assert artefact.base_model == "FLUX.1-dev"
    assert artefact.inference_host == "fal"


def test_cost_is_per_step_not_per_run(settings: LoraSettings) -> None:
    """The finding that blocked this task: $0.024 a step, so 2000 steps is $48."""
    trainer = FakeLoraTrainer(settings=settings)
    request = TrainingRequest(archive_url="u", trigger_word="M", steps=2000, dataset_hash="h")
    assert trainer.estimate_cost(request) == Decimal("48.000")


async def test_a_training_run_billed_for_nothing_is_reported(settings: LoraSettings) -> None:
    """Amendment A2 at a much larger unit: a failed GPU run is tens of dollars."""
    trainer = FakeLoraTrainer(settings=settings, fail_after_billing=True)
    job = await trainer.train(
        TrainingRequest(archive_url="u", trigger_word="M", steps=1000, dataset_hash="h")
    )
    assert job.status is JobStatus.FAILED
    assert job.cost_usd == Decimal("24.000")
    with pytest.raises(ProviderError):
        await trainer.collect(job)


# ------------------------------------------- [ADR 0010] where weights may run --
def _artefact(host: str = "fal") -> LoraArtefact:
    return LoraArtefact(
        weights_url="https://v3b.fal.media/w.safetensors",
        base_model="FLUX.1-dev",
        trainer="fal-ai/flux-lora-portrait-trainer",
        steps=1000,
        dataset_hash="h",
        trained_on=dt.date(2026, 9, 29),
        licence="FLUX.1 [dev] Non-Commercial; commercial via fal",
        inference_host=host,
    )


def test_weights_refuse_a_host_the_licence_does_not_cover() -> None:
    """The failure this prevents is silent.

    Weights run in the wrong place produce perfectly good images, and nothing about the
    output says the licence was breached.
    """
    with pytest.raises(LicenceViolation, match="non-commercial"):
        _artefact().require_inference_host("self-hosted")


def test_weights_accept_the_host_they_are_licensed_for() -> None:
    _artefact().require_inference_host("fal")


def test_config_cannot_enable_self_hosting_without_the_written_grant() -> None:
    """The permission is conditional on WHERE the weights run, so a half-change is the
    mistake worth making unrepresentable."""
    with pytest.raises(ValueError, match="non-commercial licence"):
        LoraSettings(self_hosting_permitted=True, commercial_grant_confirmed_in_writing=False)


def test_the_repository_is_configured_for_fal_only(settings: LoraSettings) -> None:
    assert settings.inference_must_run_on == "fal"
    assert settings.self_hosting_permitted is False
    assert settings.base_model_licence is not None
    assert settings.base_model_licence_verified_on == dt.date(2026, 9, 29)


# ------------------------------------------------- the real trainer, mocked --
TRAINER = "fal-ai/flux-lora-portrait-trainer"
RETURNED = "https://queue.fal.run/fal-ai/flux-lora-portrait-trainer/requests/t-1"


def _transport(payload: dict[str, object] | None = None) -> httpx.MockTransport:
    body = (
        payload
        if payload is not None
        else {
            "diffusers_lora_file": {"url": "https://v3b.fal.media/lora.safetensors"},
            "config_file": {"url": "https://v3b.fal.media/config.json"},
        }
    )

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "request_id": "t-1",
                    "status_url": f"{RETURNED}/status",
                    "response_url": RETURNED,
                },
            )
        if url == f"{RETURNED}/status":
            return httpx.Response(200, json={"status": "COMPLETED"})
        if url == RETURNED:
            return httpx.Response(200, json=body)
        return httpx.Response(405, text="Method Not Allowed")

    return httpx.MockTransport(handle)


async def test_the_real_trainer_sends_the_documented_arguments(
    settings: LoraSettings,
) -> None:
    trainer = FalLoraTrainer(
        settings=settings, client=httpx.Client(transport=_transport()), poll_interval_s=0.0
    )
    job = await trainer.train(
        TrainingRequest(
            archive_url="https://example.invalid/set.zip",
            trigger_word="MOLLIE",
            steps=1000,
            dataset_hash="h",
        )
    )
    artefact = await trainer.collect(job)
    assert artefact.weights_url.endswith("lora.safetensors")
    assert artefact.config_url is not None
    assert job.cost_usd == Decimal("24.000")


async def test_training_that_completes_with_no_weights_is_a_billed_failure(
    settings: LoraSettings,
) -> None:
    """ADR 0006's trap, at $24 a time instead of 8 cents."""
    trainer = FalLoraTrainer(
        settings=settings, client=httpx.Client(transport=_transport({})), poll_interval_s=0.0
    )
    with pytest.raises(ProviderError, match="no weights file"):
        await trainer.train(
            TrainingRequest(archive_url="u", trigger_word="M", steps=1000, dataset_hash="h")
        )
    assert trainer.jobs[-1].billed is True


async def test_an_unpriced_trainer_refuses_before_submitting() -> None:
    """A 2000-step run is not the kind of spend to discover afterwards."""
    trainer = FalLoraTrainer(settings=LoraSettings(trainer=TRAINER))
    with pytest.raises(ProviderError, match="priced per STEP"):
        await trainer.train(
            TrainingRequest(archive_url="u", trigger_word="M", steps=2000, dataset_hash="h")
        )


# -------------------------------------------------------------- evaluation --
def test_too_small_a_holdout_raises_rather_than_reports() -> None:
    """A mean over three images reads exactly like a mean over thirty."""
    from app.identity import TrainingSet

    tiny = TrainingSet(trigger_word="M")
    tiny.holdout = [Still(Path(f"x/{n}.png"), "face") for n in range(MIN_HOLDOUT - 1)]
    with pytest.raises(HoldoutTooSmall, match="under the"):
        from app.identity import holdout_reference

        holdout_reference(tiny, None)  # type: ignore[arg-type]
