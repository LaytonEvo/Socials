"""Smoke test for a configured embedder.

Answers the question you want answered before spending money: does the chosen
identity scorer actually load and produce sensible numbers on this machine?

It is deliberately not a calibration. Calibration needs a real master set and a
real control set, and its output is evidence for Gate A. This is a plumbing
check, and it says so in its own verdict -- a self-check that let itself be
mistaken for evidence would be worse than no self-check.

What it proves:
  - the dependencies import
  - the model downloads and loads
  - embeddings come back at the dimension config claims
  - the same image twice gives the same vector
  - variations of one synthetic identity score closer together than two
    different ones, i.e. the vectors carry *some* signal
  - how long an embedding takes, which decides whether a real run is hours or
    minutes

What it does NOT prove: that the scorer separates real faces well enough to
gate takes on. Only calibration against a real master set answers that.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .embed import NO_FACE, Embedder, cosine
from .errors import SpikeError
from .providers import render_fake_face

#: Synthetic identities for the discrimination probe. Coloured shapes, not
#: faces -- enough to show the vectors carry signal, nowhere near enough to
#: say the scorer works on faces.
PROBE_IDENTITIES = ("probe-a", "probe-b", "probe-c")
VARIATIONS_PER_IDENTITY = 3


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        mark = "ok  " if self.ok else "FAIL"
        return f"  [{mark}] {self.name}" + (f"  —  {self.detail}" if self.detail else "")


@dataclass
class CheckResult:
    steps: list[Step] = field(default_factory=list)
    timings_ms: list[float] = field(default_factory=list)
    same_identity: list[float] = field(default_factory=list)
    different_identity: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> Step:
        step = Step(name, ok, detail)
        self.steps.append(step)
        return step

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    @property
    def median_ms(self) -> float:
        return float(np.median(self.timings_ms)) if self.timings_ms else float("nan")


def _write_probe_images(dest: Path) -> dict[str, list[Path]]:
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[Path]] = {}
    for identity in PROBE_IDENTITIES:
        paths = []
        for i in range(VARIATIONS_PER_IDENTITY):
            path = dest / f"{identity}_{i}.png"
            render_fake_face(identity, variation=i).save(path)
            paths.append(path)
        out[identity] = paths
    return out


def _estimate_run_cost(median_ms: float, fps: float, clip_s: float, clips: int) -> str:
    frames = max(1, round(fps * clip_s)) * clips
    seconds = frames * median_ms / 1000.0
    unit = f"{seconds:.0f}s" if seconds < 120 else f"{seconds / 60:.1f} min"
    return f"{frames} embeddings for a {clips}-clip run ≈ {unit}"


def run_check(
    embedder: Embedder,
    workdir: Path,
    expected_dim: int | None,
    sample_images: list[Path] | None = None,
    fps: float = 2.0,
    clip_s: float = 5.0,
    clips: int = 24,
) -> CheckResult:
    result = CheckResult()
    info = embedder.info
    result.add("embedder constructed", True, info.key())
    if info.is_stub:
        result.notes.append(
            "This is the STUB embedder — pixel statistics, not a model. It will pass "
            "everything below and prove nothing about the real scorer."
        )

    probes = _write_probe_images(workdir / "probe")
    first = probes[PROBE_IDENTITIES[0]][0]

    # 1. The model loads at all. For DINOv2 this is where the download happens.
    started = time.perf_counter()
    try:
        embedding = embedder.embed_image(first)
    except Exception as exc:
        result.add("model loads and runs", False, f"{type(exc).__name__}: {exc}")
        return result
    load_s = time.perf_counter() - started
    result.add("model loads and runs", True, f"first call took {load_s:.1f}s incl. any download")

    if embedding.status == NO_FACE:
        result.add(
            "face found in the probe image",
            False,
            "the detector found nothing. Use --detector whole-image to test the model "
            "itself, or pass --images with real photographs.",
        )
        return result
    if embedding.vector is None:
        result.add("embedding returned", False, f"status was {embedding.status}")
        return result

    # 2. Dimension matches what config claims. A mismatch silently invalidates
    #    any threshold calibrated against it (amendment A3).
    actual_dim = int(embedding.vector.shape[0])
    result.add(
        "embedding dimension matches config",
        expected_dim is None or actual_dim == expected_dim,
        f"got {actual_dim}, config says {expected_dim}",
    )

    # 3. Unit length, so cosine similarity behaves.
    norm = float(np.linalg.norm(embedding.vector))
    result.add("embedding is normalised", abs(norm - 1.0) < 1e-4, f"|v| = {norm:.6f}")

    # 4. Determinism. A scorer that drifts between runs cannot support a
    #    provenance record that says why a clip was accepted months ago.
    repeat = embedder.embed_image(first)
    deterministic = repeat.vector is not None and cosine(embedding.vector, repeat.vector) > 0.9999
    result.add("same image twice gives the same vector", deterministic)

    # 5. Timing, and the discrimination probe, in one pass.
    vectors: dict[str, list[np.ndarray]] = {}
    for identity, paths in probes.items():
        vectors[identity] = []
        for path in paths:
            started = time.perf_counter()
            fe = embedder.embed_image(path)
            result.timings_ms.append((time.perf_counter() - started) * 1000)
            if fe.vector is not None:
                vectors[identity].append(fe.vector)

    for vecs in vectors.values():
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                result.same_identity.append(cosine(vecs[i], vecs[j]))
    names = list(vectors)
    for a_i, a in enumerate(names):
        for b in names[a_i + 1 :]:
            for va in vectors[a]:
                for vb in vectors[b]:
                    result.different_identity.append(cosine(va, vb))

    if result.same_identity and result.different_identity:
        same = float(np.mean(result.same_identity))
        diff = float(np.mean(result.different_identity))
        result.add(
            "variations of one identity score closer than two identities",
            same > diff,
            f"same {same:.4f} vs different {diff:.4f} (margin {same - diff:+.4f})",
        )

    if result.timings_ms:
        result.notes.append(
            f"{result.median_ms:.0f} ms per embedding — "
            + _estimate_run_cost(result.median_ms, fps, clip_s, clips)
        )

    # 6. Optional: the real path, on real photographs, including detection.
    if sample_images:
        found = 0
        for path in sample_images:
            fe = embedder.embed_image(path)
            found += int(fe.usable)
        result.add(
            "faces detected in your sample images",
            found > 0,
            f"{found} of {len(sample_images)} produced a usable embedding",
        )
    else:
        result.notes.append(
            "No --images given, so detection was not exercised on real photographs. "
            "The probe images are coloured shapes."
        )

    return result


def format_result(result: CheckResult, backend: str) -> str:
    lines = [f"\nembedder self-check: {backend}", ""]
    lines += [step.line() for step in result.steps]
    if result.notes:
        lines += [""] + [f"  note: {n}" for n in result.notes]
    lines += [""]
    if result.ok:
        lines += [
            "  PASSED — the scorer loads and produces sensible vectors on this machine.",
            "",
            "  This is a plumbing check, NOT evidence. It says nothing about whether the",
            "  scorer separates real faces well enough to gate takes on. Only calibration",
            "  against a real master set and a real control set answers that.",
        ]
    else:
        lines += ["  FAILED — see the lines marked FAIL above."]
    return "\n".join(lines) + "\n"


def sample_images_from(directory: Path | None) -> list[Path]:
    if directory is None:
        return []
    directory = Path(directory)
    if not directory.is_dir():
        raise SpikeError(f"--images: {directory} is not a directory")
    images = sorted(
        p for p in directory.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    if not images:
        raise SpikeError(f"--images: no images found in {directory}")
    return images
