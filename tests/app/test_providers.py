"""Task 0.6 — adapter protocols and the fakes the pipeline runs on.

The acceptance criterion is "pipeline code runs end to end on fakes", and the test
for it drives `app.pipeline.dry_run` rather than calling providers one at a time.
Calling each adapter in turn would prove each one works and nothing about whether
they compose, which is the only claim 0.6 actually makes.

The rest guards the ways a fake goes wrong: being more permissive than the real
thing, and being unable to reproduce the one failure that costs money.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
import yaml
from sqlalchemy import CheckConstraint

from app.models import Base
from app.pipeline.dry_run import SHOT_LIST_SCHEMA, Providers, dry_run
from app.providers import (
    AudioSupport,
    CapabilityError,
    FakeImageProvider,
    FakeLipSyncProvider,
    FakeLLMProvider,
    FakeVideoProvider,
    FakeVoiceProvider,
    ImageProvider,
    JobStatus,
    LipSyncProvider,
    LLMProvider,
    LLMRequest,
    ProviderError,
    SeedSupport,
    VideoProvider,
    VideoRequest,
    VoiceProvider,
)
from app.storage import MemoryStorage, persona_of

from .test_config import REAL_CONFIG
from .test_storage import PERSONA


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@dataclass
class Fakes:
    """The concrete fakes, kept alongside the protocol bundle handed to the run.

    `Providers` is typed as protocols, which is the point — but a protocol has no
    `jobs` list, and a test that wants to assert a stage really ran needs the
    concrete object. Holding both is honest; casting or ignoring the type would be
    hiding that the test knows more than the pipeline does.
    """

    llm: FakeLLMProvider
    image: FakeImageProvider
    video: FakeVideoProvider
    voice: FakeVoiceProvider
    lipsync: FakeLipSyncProvider

    @property
    def all(
        self,
    ) -> list[
        FakeLLMProvider
        | FakeImageProvider
        | FakeVideoProvider
        | FakeVoiceProvider
        | FakeLipSyncProvider
    ]:
        return [self.llm, self.image, self.video, self.voice, self.lipsync]

    def as_providers(self) -> Providers:
        return Providers(
            llm=self.llm,
            image=self.image,
            video=self.video,
            voice=self.voice,
            lipsync=self.lipsync,
        )


def _fakes(
    storage: MemoryStorage,
    *,
    shots: int = 3,
    video: FakeVideoProvider | None = None,
) -> Fakes:
    return Fakes(
        llm=FakeLLMProvider(storage=storage, shots=shots),
        image=FakeImageProvider(storage=storage),
        video=video or FakeVideoProvider(storage=storage),
        voice=FakeVoiceProvider(storage=storage),
        lipsync=FakeLipSyncProvider(storage=storage),
    )


# ------------------------------------------------- the acceptance criterion --
async def test_the_pipeline_runs_end_to_end_on_fakes(storage: MemoryStorage) -> None:
    """Brief in, artefacts in storage, no network and no spend. Task 0.6."""
    report = await dry_run(
        "A short about why she stopped fighting her slice",
        persona_id=PERSONA,
        providers=_fakes(storage).as_providers(),
        storage=storage,
    )

    assert len(report.shots) == 3
    assert report.total_cost == Decimal("0")
    assert report.billed_failures == 0

    # One keyframe and two takes per shot, plus a voice line and a lip sync for
    # the single shot carrying dialogue.
    assert len(report.artefacts) == 3 * 3 + 2
    for key in report.artefacts:
        assert storage.exists(key)
        assert persona_of(key) == PERSONA


async def test_every_stage_actually_ran(storage: MemoryStorage) -> None:
    """A run that skipped a stage would still look like a success above."""
    fakes = _fakes(storage)
    await dry_run("brief", persona_id=PERSONA, providers=fakes.as_providers(), storage=storage)
    for provider in fakes.all:
        assert provider.jobs, f"{provider.name} was never called"


async def test_only_dialogue_shots_get_a_voice_and_a_lip_sync(storage: MemoryStorage) -> None:
    """B-roll has no dialogue, so paying for speech on it would be waste.

    Task 3.7 says the same: lip sync is applied to face-forward takes where dialogue
    is replaced, and skipped for B-roll.
    """
    report = await dry_run(
        "brief", persona_id=PERSONA, providers=_fakes(storage).as_providers(), storage=storage
    )
    with_dialogue = [shot for shot in report.shots if shot.voice_key]
    assert len(with_dialogue) == 1
    assert with_dialogue[0].shot_type == "face"
    assert all(shot.lipsync_key is None for shot in report.shots if not shot.voice_key)


async def test_the_run_scales_with_takes_per_shot(storage: MemoryStorage) -> None:
    """The yield penalty in content_policy.yaml is expressed as take counts, so the
    pipeline has to honour a per-shot count rather than assume one."""
    report = await dry_run(
        "brief",
        persona_id=PERSONA,
        providers=_fakes(storage, shots=1).as_providers(),
        storage=storage,
        takes_per_shot=4,
    )
    assert len(report.shots[0].take_keys) == 4


# ----------------------------------------- [A2] a call that produced nothing --
async def test_a_take_billed_for_nothing_is_recorded_not_swallowed(
    storage: MemoryStorage,
) -> None:
    """Amendment A2's case, and the one nobody tests by accident.

    A provider that times out after generation started has been paid. Without this
    the cost has nowhere to live, because a `generation` row only exists for a call
    that returned something.
    """
    fakes = _fakes(storage, video=FakeVideoProvider(storage=storage, fail_after_billing=True))
    report = await dry_run(
        "brief",
        persona_id=PERSONA,
        providers=fakes.as_providers(),
        storage=storage,
        takes_per_shot=2,
    )

    assert report.billed_failures == 6, "every take failed after billing and all six count"
    assert all(shot.take_keys == [] for shot in report.shots)
    timed_out = [job for job in report.jobs if job.status is JobStatus.TIMED_OUT]
    assert len(timed_out) == 6
    assert all(job.billed for job in timed_out)
    assert all(job.cost_usd is not None for job in timed_out), (
        "a finished job with no cost is a row the `job` table refuses"
    )


async def test_a_refusal_before_submission_is_free(storage: MemoryStorage) -> None:
    """A 403 costs nothing, and must not be reported as though it did."""
    video = FakeVideoProvider(storage=storage, refuse=True)
    with pytest.raises(ProviderError) as exc:
        await video.generate(VideoRequest(prompt="p", duration_s=5.0), key="k")
    assert exc.value.billed is False
    job = video.jobs[-1]
    assert job.billed is False
    assert job.cost_usd == Decimal("0")


async def test_a_finished_job_always_carries_a_cost(storage: MemoryStorage) -> None:
    """Including zero. A missing price and a genuine zero mean different things."""
    report = await dry_run(
        "brief", persona_id=PERSONA, providers=_fakes(storage).as_providers(), storage=storage
    )
    finished = [job for job in report.jobs if job.status.is_finished]
    assert finished
    assert all(job.cost_usd is not None for job in finished)


# ------------------------------------------------ the fakes are not permissive --
async def test_a_duration_the_model_cannot_do_is_refused(storage: MemoryStorage) -> None:
    """The fake enforces what the real models enforce.

    One accepts 4, 6 or 8 as literals and the other an integer no lower than 5. A
    permissive fake would pass every test and fail the first real call.
    """
    video = FakeVideoProvider(storage=storage)
    with pytest.raises(CapabilityError, match="seconds"):
        await video.generate(VideoRequest(prompt="p", duration_s=7.0), key="k")


async def test_a_capability_refusal_costs_nothing(storage: MemoryStorage) -> None:
    """It is caught before the call, so no job should be billed for it."""
    video = FakeVideoProvider(storage=storage)
    with pytest.raises(CapabilityError) as exc:
        await video.generate(VideoRequest(prompt="p", duration_s=99.0), key="k")
    assert exc.value.billed is False


async def test_an_aspect_the_model_cannot_render_is_refused(storage: MemoryStorage) -> None:
    video = FakeVideoProvider(storage=storage)
    with pytest.raises(CapabilityError, match="4:3"):
        await video.generate(VideoRequest(prompt="p", duration_s=5.0, aspect="4:3"), key="k")


def test_the_fake_does_not_claim_a_seed_is_honoured(storage: MemoryStorage) -> None:
    """Both real video models accept a seed and ignore it.

    The spike sent an identical seed twice and measured a 25.42/255 mean per-pixel
    difference. A fake claiming reproducibility would teach the pipeline something
    false about every take it generates.
    """
    caps = FakeVideoProvider(storage=storage).capabilities()
    assert caps.seed is SeedSupport.ACCEPTED_NOT_HONOURED
    assert caps.audio is AudioSupport.OPTIONAL


async def test_the_fakes_are_deterministic_and_reality_is_not(storage: MemoryStorage) -> None:
    """Pins the known difference, so nothing builds on it.

    Same request, same bytes. No real model tested behaves this way, which is why
    the docstring in fakes.py says so and this test exists to keep it true.
    """
    first = FakeVideoProvider(storage=MemoryStorage())
    second = FakeVideoProvider(storage=MemoryStorage())
    request = VideoRequest(prompt="identical", duration_s=5.0, seed=42)

    await first.generate(request, key=(key := f"persona/{PERSONA}/take/x.mp4"))
    await second.generate(request, key=key)
    assert first.storage.get(key) == second.storage.get(key)


# ------------------------------------------------------------ the protocols --
@pytest.mark.parametrize(
    ("factory", "protocol"),
    [
        (FakeImageProvider, ImageProvider),
        (FakeVideoProvider, VideoProvider),
        (FakeVoiceProvider, VoiceProvider),
        (FakeLipSyncProvider, LipSyncProvider),
        (FakeLLMProvider, LLMProvider),
    ],
)
def test_each_fake_satisfies_its_protocol(
    storage: MemoryStorage, factory: type, protocol: type
) -> None:
    assert isinstance(factory(storage=storage), protocol)


def test_the_llm_request_requires_a_schema() -> None:
    """Task 3.1 needs a schema-validated shot list. A free-text reply that happens
    to look like JSON is the thing that breaks quietly three weeks later."""
    with pytest.raises(TypeError):
        LLMRequest(prompt="write me a shot list")  # type: ignore[call-arg]


async def test_the_shot_list_matches_the_schema_it_was_given(storage: MemoryStorage) -> None:
    """The fake is schema-driven rather than a fixed fixture, so it cannot pass a
    validation the real model would fail."""
    llm = FakeLLMProvider(storage=storage, shots=2)
    job = await llm.generate(LLMRequest(prompt="brief", schema=SHOT_LIST_SCHEMA))
    result = await llm.poll(job)

    required = set(SHOT_LIST_SCHEMA["properties"]["shots"]["items"]["required"])
    assert len(result.data["shots"]) == 2
    for shot in result.data["shots"]:
        assert required <= set(shot)
        assert shot["shot_type"] in {"face", "broll"}


# --------------------------------------------- no second source of truth --
def test_job_status_matches_the_database_vocabulary() -> None:
    """The adapter's statuses and the `job` table's CHECK must be the same set.

    An adapter status the database refuses is a row that cannot be written at the
    exact moment something has just been billed — the worst time to find a typo.
    """
    job_table = Base.metadata.tables["job"]
    check = next(
        constraint
        for constraint in job_table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == "ck_status_vocabulary"
    )
    in_database = set(str(check.sqltext).replace("status IN (", "").rstrip(")").split(", "))
    in_database = {value.strip("'") for value in in_database}
    assert {status.value for status in JobStatus} == in_database


def test_the_configured_fake_slots_cover_every_capability() -> None:
    """Task 0.6 requires the pipeline to run on fakes, so config must offer one for
    each protocol — otherwise the offline path has a hole nothing reports."""
    providers = yaml.safe_load((REAL_CONFIG / "providers.yaml").read_text())["providers"]
    assert set(providers["fake"]) == {"image", "video", "lipsync", "voice", "llm"}
    for slot in providers["fake"].values():
        assert slot["backend"] == "fake"
        assert slot["verified_on"] is not None, (
            "a fake price still needs a date: absent and genuinely zero differ"
        )
