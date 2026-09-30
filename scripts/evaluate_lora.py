"""Evaluate a trained LoRA against the held-out reference stills — task 1.4's last half.

The holdout rule is the point of this script. Generated images are scored against a
centroid built from the HELD-OUT stills only, never the full reference set: score against
images the LoRA trained on and you measure memorisation, which always flatters.
`app.identity.evaluation.evaluate` takes the split rather than a centroid so the wrong
reference cannot be passed by accident.

Read the numbers against the sanity check, not against the threshold. `--sanity` scores
her own training stills against the same holdout centroid, which is the ceiling this
scorer and this split can produce. A LoRA near that ceiling is doing well; one merely
above the threshold is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from app.config import load_all
from app.costs.guard import BudgetGuard
from app.identity.dataset import NO_FACE_STILLS, collect, split
from app.identity.embedder import DlibEmbedder
from app.identity.evaluation import evaluate, sanity_check
from app.providers.fal import QUEUE_ROOT, api_key

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ROOT = ROOT / "spike" / "data"
GROUP, SLOT = "image", "lora_inference"

#: Prompts spread across the conditions the reference set covers, so the evaluation says
#: something about range rather than about one pose repeated. Deliberately plain: this
#: measures whether the face survives, not whether the prompt is interesting.
PROMPTS = [
    "a photo of {w}, a young woman, head and shoulders portrait, neutral expression",
    "a photo of {w}, a young woman, three-quarter view, natural daylight",
    "a photo of {w}, a young woman, profile view, soft indoor light",
    "a photo of {w}, a young woman smiling, outdoors, overcast",
    "a photo of {w}, a young woman wearing golf clothing, on a golf course",
    "a photo of {w}, a young woman, golden hour light, outdoors",
    "a photo of {w}, a young woman, medium shot, standing, plain background",
    "a photo of {w}, a young woman, close-up, looking at the camera",
]


def generate(
    client: httpx.Client,
    model: str,
    prompt: str,
    weights_url: str,
    scale: float,
    base: dict[str, Any],
) -> str:
    """One image, returning its URL. Raises on anything that is not a usable result."""
    payload: dict[str, Any] = {
        "prompt": prompt,
        "loras": [{"path": weights_url, "scale": scale}],
        **base,
    }
    r = client.post(f"{QUEUE_ROOT}/{model}", json=payload)
    r.raise_for_status()
    sub = r.json()
    status_url, response_url = sub["status_url"], sub["response_url"]
    for _ in range(120):
        s = client.get(status_url)
        if s.json().get("status") in {"COMPLETED", "FAILED", "ERROR"}:
            break
        import time

        time.sleep(5)
    resp = client.get(response_url)
    if resp.status_code >= 400:
        raise RuntimeError(f"generation failed {resp.status_code}: {resp.text[:400]}")
    images = resp.json().get("images") or []
    if not images or not images[0].get("url"):
        raise RuntimeError(f"COMPLETED with no image: {resp.text[:400]}")
    return str(images[0]["url"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artefact", type=Path, default=ROOT / "spike" / "runs" / "lora" / "artefact.json"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "spike" / "runs" / "lora" / "eval")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--count", type=int, default=len(PROMPTS))
    parser.add_argument("--budget", type=Decimal, default=None)
    parser.add_argument("--sanity", action="store_true", help="only the free control")
    args = parser.parse_args()

    config = load_all(ROOT / "config")
    configured = config.persona.persona.look.identity_threshold
    if configured is None:
        raise SystemExit("persona.look.identity_threshold is not set; nothing to score against")
    threshold = float(configured)
    roots = {k: REFERENCE_ROOT / k for k in ("master_v2", "outfit", "lighting", "body")}
    dataset = split(collect(roots, exclude=NO_FACE_STILLS), trigger_word="mollie")
    embedder = DlibEmbedder(config.providers)

    print(f"threshold     {threshold}")
    print(f"holdout       {len(dataset.holdout)} stills, centroid built from these ONLY")

    control = sanity_check(dataset, embedder, threshold)
    print("\n-- sanity check (free): her own training stills vs the holdout centroid --")
    print(f"  scored      {control.generated}")
    print(f"  pass rate   {control.pass_rate:.4f}")
    print(f"  mean        {control.mean:.5f}   min {control.minimum:.5f}")
    print("  ^ this is the CEILING. Judge the LoRA against it, not against the threshold.")
    if args.sanity:
        return 0

    artefact = json.loads(args.artefact.read_text())
    weights_url = artefact["weights_url"]
    if artefact.get("inference_host") != "fal":
        raise SystemExit(f"artefact says it runs on {artefact.get('inference_host')}, not fal")

    guard = BudgetGuard(config.budget, config.providers)
    slot, unit_price, unit = guard.price(GROUP, SLOT)
    estimate = guard.estimate(GROUP, SLOT, Decimal(args.count))
    print(f"\nmodel         {slot.model}")
    print(f"price         ${unit_price} per {unit} x {args.count} = ${estimate}")
    run_budget = guard.require_run_budget(args.budget)
    if estimate > run_budget:
        raise SystemExit(f"estimate ${estimate} exceeds run budget ${run_budget}; refusing")

    args.out.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Key {api_key()}"} if api_key() else {}
    client = httpx.Client(timeout=180.0, headers=headers)
    request = getattr(slot, "request", None)
    base: dict[str, Any] = dict(getattr(request, "base", None) or {})

    generated: list[Path] = []
    for i, template in enumerate(PROMPTS[: args.count]):
        prompt = template.format(w=artefact["trigger_word"])
        print(f"\n[{i + 1}/{args.count}] {prompt}")
        assert slot.model is not None
        url = generate(client, slot.model, prompt, weights_url, args.scale, base)
        dest = args.out / f"gen_{i:02d}.png"
        dest.write_bytes(client.get(url, timeout=180.0).content)
        generated.append(dest)
        print(f"  -> {dest.name}")

    result = evaluate(generated, split=dataset, embedder=embedder, threshold=threshold)
    print("\n-- LoRA vs the holdout centroid --")
    print(f"  generated   {result.generated}")
    print(f"  passed      {result.passed} at {threshold}")
    print(f"  pass rate   {result.pass_rate:.4f}")
    if result.mean is not None:
        print(f"  mean        {result.mean:.5f}   (ceiling {control.mean:.5f})")
        print(f"  min         {result.minimum:.5f}")
    for name, why in result.unusable:
        print(f"  UNUSABLE    {name}: {why}")

    summary = {
        "threshold": threshold,
        "holdout_size": result.holdout_size,
        "sanity": {
            "mean": control.mean,
            "pass_rate": control.pass_rate,
            "scored": control.generated,
        },
        "lora": {
            "generated": result.generated,
            "passed": result.passed,
            "pass_rate": result.pass_rate,
            "mean": result.mean,
            "min": result.minimum,
            "scores": result.scores,
            "unusable": result.unusable,
        },
        "weights_url": weights_url,
        "lora_scale": args.scale,
        "estimated_cost_usd": str(estimate),
    }
    (args.out / "evaluation.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nrecorded      {(args.out / 'evaluation.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
