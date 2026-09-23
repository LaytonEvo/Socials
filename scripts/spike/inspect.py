"""Per-image view of a calibration, for checking a headline against your eye.

`calibrate` reports distributions. A distribution cannot tell you whether a
clean separation is real or an artefact of how the sets were built — for that
you need to see which images sit where, and look at the ones near the boundary.

dlib reported overlap 0.000 on 28 master images against 16 controls. That is
either a genuinely strong scorer or a sign the two sets differ in some way that
has nothing to do with identity. The way to tell them apart is to find the
closest call in each direction and look at it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .embed import Embedder, EmbeddingSet, cosine, embed_images


@dataclass
class ImageScore:
    path: Path
    similarity: float | None
    status: str

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class SetInspection:
    master: list[ImageScore]
    control: list[ImageScore]
    embedder_key: str

    @property
    def scored_master(self) -> list[ImageScore]:
        return [s for s in self.master if s.similarity is not None]

    @property
    def scored_control(self) -> list[ImageScore]:
        return [s for s in self.control if s.similarity is not None]

    @property
    def weakest_master(self) -> ImageScore | None:
        """Her own image that looks least like her. The one to eyeball."""
        scored = self.scored_master
        return min(scored, key=lambda s: s.similarity or 0.0) if scored else None

    @property
    def closest_control(self) -> ImageScore | None:
        """The stranger who looks most like her. The other one to eyeball."""
        scored = self.scored_control
        return max(scored, key=lambda s: s.similarity or 0.0) if scored else None

    @property
    def margin(self) -> float | None:
        """Gap between the weakest master and the closest control.

        Negative means they cross: at least one of her images scores lower than
        at least one stranger, and no threshold separates them cleanly.
        """
        weakest, closest = self.weakest_master, self.closest_control
        if weakest is None or closest is None:
            return None
        assert weakest.similarity is not None and closest.similarity is not None
        return weakest.similarity - closest.similarity


def inspect_sets(
    embedder: Embedder, master_paths: list[Path], control_paths: list[Path]
) -> SetInspection:
    master: EmbeddingSet = embed_images(embedder, master_paths, label="master")
    centroid = master.centroid()
    if centroid is None:
        raise ValueError("master set produced no usable embeddings")

    def score(es: EmbeddingSet) -> list[ImageScore]:
        out: list[ImageScore] = []
        for frame in es.frames:
            source = Path(frame.source) if frame.source else Path("?")
            if frame.vector is None:
                out.append(ImageScore(source, None, frame.status))
            else:
                out.append(ImageScore(source, cosine(frame.vector, centroid), frame.status))
        return out

    control: EmbeddingSet = embed_images(embedder, control_paths, label="control")
    return SetInspection(score(master), score(control), embedder.info.key())


def format_inspection(ins: SetInspection, show: int = 8) -> str:
    lines = [f"\nper-image similarity to the master centroid — {ins.embedder_key}", ""]

    m = sorted(ins.scored_master, key=lambda s: s.similarity or 0.0)
    c = sorted(ins.scored_control, key=lambda s: -(s.similarity or 0.0))

    lines.append(f"  MASTER, weakest first ({len(m)} scored):")
    for s in m[:show]:
        lines.append(f"    {s.similarity:.4f}  {s.name}")
    if len(m) > show:
        lines.append(f"    ...  ({len(m) - show} more, up to {m[-1].similarity:.4f})")

    lines += ["", f"  CONTROL, closest first ({len(c)} scored):"]
    for s in c[:show]:
        lines.append(f"    {s.similarity:.4f}  {s.name}")
    if len(c) > show:
        lines.append(f"    ...  ({len(c) - show} more, down to {c[-1].similarity:.4f})")

    unusable = [s for s in ins.master + ins.control if s.similarity is None]
    if unusable:
        lines += ["", f"  {len(unusable)} image(s) produced no embedding:"]
        lines += [f"    {s.status:<12} {s.name}" for s in unusable]

    margin = ins.margin
    weakest, closest = ins.weakest_master, ins.closest_control
    lines += ["", "  The two images that decide whether the separation is real:"]
    if weakest and closest and margin is not None:
        lines += [
            f"    her weakest    {weakest.similarity:.4f}  {weakest.name}",
            f"    closest other  {closest.similarity:.4f}  {closest.name}",
            f"    margin         {margin:+.4f}",
            "",
        ]
        if margin <= 0:
            lines.append(
                "  THEY CROSS. At least one of her images scores below at least one\n"
                "  stranger, so no threshold separates the sets cleanly."
            )
        elif margin < 0.05:
            lines.append(
                "  Narrow. The separation holds but only just; a slightly harder\n"
                "  control or a more varied master set would likely close it."
            )
        else:
            lines.append(
                "  Clear gap. Open both images above and check you agree: the first\n"
                "  should obviously be her, the second obviously not. If the second\n"
                "  looks like her to you, the scorer is wrong and the statistics are\n"
                "  measuring something else."
            )
    return "\n".join(lines) + "\n"
