"""Extend the master set with body, outfit and lighting references — owner option 2.

Editing rather than generating, because editing a master still preserves her face by
construction while a fresh generation only hopes for it: the wardrobe work measured
0.9917 / 0.9926 / 0.9903 against a 0.9609 threshold.

Measures first and commits nothing. Adding stills moves the centroid the threshold is
defined against (ADR 0008), so yield per kind is reported and the decision to ingest is
taken afterwards, with numbers.

    python -m scripts.widen_master_set --budget 10 --per-kind 8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.config import load_all
from app.costs import BudgetGuard
from app.identity import DlibEmbedder, FaceOutcome, centroid, cosine, read_still
from app.providers.fal import FalImageProvider
from app.providers.types import ImageRequest, ProviderError
from app.storage import MemoryStorage, key_for

MASTER_SET = Path("spike/data/master_v2")

#: Prompts per kind. Clothing follows persona.yaml: skorts, fitted polos, a visor, the
#: tennis-to-golf crossover; never cropped or gym-not-golf. The test in the spec is
#: whether a strict members' club would let her on the first tee.
PROMPTS: dict[str, list[str]] = {
    "outfit": [
        (
            "Change her clothing to a fitted navy golf polo and a white pleated skort. Keep "
            "her face, hair and the setting exactly as they are."
        ),
        (
            "Change her clothing to a pale blue sleeveless golf polo and a stone-coloured "
            "skort. Keep her face, hair and the setting exactly as they are."
        ),
        (
            "Change her clothing to a white fitted golf polo, a black skort and a white "
            "visor. Keep her face, hair and the setting exactly as they are."
        ),
        (
            "Change her clothing to a soft pink golf polo and a navy skort. Keep her face, "
            "hair and the setting exactly as they are."
        ),
    ],
    "lighting": [
        (
            "Relight this photograph as late golden-hour sun, low and warm from the side. "
            "Keep her face, clothing and pose exactly as they are."
        ),
        (
            "Relight this photograph as flat overcast daylight, soft and cool with no hard "
            "shadows. Keep her face, clothing and pose exactly as they are."
        ),
        (
            "Relight this photograph as warm interior clubhouse light from windows to one "
            "side. Keep her face, clothing and pose exactly as they are."
        ),
        (
            "Relight this photograph as bright midday sun with crisp shadows. Keep her "
            "face, clothing and pose exactly as they are."
        ),
    ],
    "body": [
        (
            "Widen the framing to a full-length shot showing her whole body standing on a "
            "golf course. Keep her face, clothing and the setting exactly as they are."
        ),
        (
            "Widen the framing to a three-quarter body shot from the knees up. Keep her "
            "face, clothing and the setting exactly as they are."
        ),
        (
            "Widen the framing to show her full body walking on a fairway, seen from a "
            "distance. Keep her face, clothing and the setting exactly as they are."
        ),
        (
            "Widen the framing to a full-length shot of her standing holding a golf club. "
            "Keep her face, clothing and the setting exactly as they are."
        ),
    ],
}


@dataclass
class Outcome:
    kind: str
    source: str
    prompt_index: int
    similarity: float | None
    passed: bool
    note: str = ""


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=Decimal, required=True, help="USD ceiling for this run")
    parser.add_argument("--per-kind", type=int, default=8)
    parser.add_argument("--out", type=Path, default=Path("spike/runs/widen"))
    args = parser.parse_args()

    config = load_all()
    guard = BudgetGuard(config.budget, config.providers)
    run_budget = guard.require_run_budget(args.budget)

    slot, unit_price, unit = guard.price("image", "keyframe")
    assert slot.model is not None
    planned = len(PROMPTS) * args.per_kind
    estimate = unit_price * planned
    print(f"{slot.model} at ${unit_price}/{unit}")
    print(f"planned {planned} edits · estimate ${estimate} · run budget ${run_budget}")
    if estimate > run_budget:
        print(f"REFUSED: ${estimate} exceeds the ${run_budget} run budget", file=sys.stderr)
        return 1

    embedder = DlibEmbedder(config.providers)
    threshold = config.persona.persona.look.identity_threshold
    assert threshold is not None

    # The centroid the threshold is defined against, from the existing set.
    master = [
        r.embedding
        for path in sorted(MASTER_SET.glob("*"))
        if path.is_file()
        for r in [read_still(path, embedder)]
        if r.embedding is not None
    ]
    reference = centroid(master)
    print(f"master centroid from {len(master)} stills · threshold {threshold}\n")

    # Sources spanning the framing bands, so edits are not all from near-identical
    # starting points.
    sources = _spread_of_sources(embedder, args.per_kind)
    print("sources:", ", ".join(p.name for p in sources), "\n")

    storage = MemoryStorage()
    provider = FalImageProvider(
        model=slot.model,
        price_usd_per_image=unit_price,
        price_verified_on=slot.verified_on,
        storage=storage,
        request_shape=slot.request,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    outcomes: list[Outcome] = []
    spent = Decimal("0")

    for kind, prompts in PROMPTS.items():
        print(f"--- {kind} ---")
        for index in range(args.per_kind):
            source = sources[index % len(sources)]
            prompt = prompts[index % len(prompts)]
            name = f"{kind}-{index:02d}-{source.stem}.png"
            key = key_for(
                config.persona.persona.id.replace("persona_", "550e8400-e29b-41d4-a716-4466554400")
                if False
                else _PERSONA,
                "reference",
                name,
            )

            if spent + unit_price > run_budget:
                print(f"  stopping: ${spent + unit_price} would pass the ${run_budget} budget")
                break
            try:
                job = await provider.generate(ImageRequest(prompt=prompt), key=key, source=source)
                spent += provider.cost_of(job)
            except ProviderError as exc:
                spent += provider.cost_of(provider.jobs[-1])
                outcomes.append(Outcome(kind, source.name, index, None, False, f"failed: {exc}"))
                print(f"  {name}: FAILED ({'billed' if exc.billed else 'free'}) {exc}")
                continue

            out_path = args.out / name
            out_path.write_bytes(storage.get(key))
            reading = read_still(out_path, embedder)
            if reading.embedding is None:
                outcomes.append(
                    Outcome(kind, source.name, index, None, False, str(reading.outcome))
                )
                print(f"  {name}: no usable face ({reading.outcome})")
                continue

            score = cosine(reading.embedding, reference)
            passed = score >= threshold
            outcomes.append(Outcome(kind, source.name, index, score, passed))
            print(f"  {name}: {score:.4f} {'PASS' if passed else 'BELOW THRESHOLD'}")

    print(f"\nspent ${spent} of ${run_budget}")
    _summarise(outcomes, threshold)
    (args.out / "outcomes.json").write_text(
        json.dumps([o.__dict__ for o in outcomes], indent=2, default=str)
    )
    print(f"\nimages and outcomes.json in {args.out}")
    return 0


#: A fixed id for this measurement run. Nothing is written to the database here —
#: storage is in-memory and the images land on disk — so this only shapes the key.
#: Ingestion happens afterwards, against her real persona row, once the yield is known.
_PERSONA = "550e8400-e29b-41d4-a716-446655440000"


def _spread_of_sources(embedder: DlibEmbedder, count: int) -> list[Path]:
    """Pick sources across the framing bands rather than the first N on disk."""
    scored: list[tuple[float, Path]] = []
    for path in sorted(MASTER_SET.glob("*")):
        if not path.is_file():
            continue
        reading = read_still(path, embedder)
        if reading.outcome is FaceOutcome.OK and reading.face_area_fraction is not None:
            scored.append((reading.face_area_fraction, path))
    scored.sort()
    if not scored:
        raise SystemExit("no usable source stills")
    step = max(len(scored) // count, 1)
    return [path for _, path in scored[::step]][:count]


def _summarise(outcomes: list[Outcome], threshold: float) -> None:
    print("\nyield by kind:")
    for kind in PROMPTS:
        rows = [o for o in outcomes if o.kind == kind]
        passed = [o for o in rows if o.passed]
        scores = [o.similarity for o in rows if o.similarity is not None]
        detail = f" · scores {min(scores):.4f} to {max(scores):.4f}" if scores else " · no scores"
        print(f"  {kind:9} {len(passed)}/{len(rows)}{detail}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
