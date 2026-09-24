"""Provider seam for the spike.

This is NOT the adapter contract from BUILD_PLAN Section 5. It is a deliberately
thinner thing: enough shape to keep vendor calls in one place and to route every
one of them through the cost ledger, with no pretence of being the production
abstraction. The real protocols are designed in Phase 0, informed by what this
spike learns about polling, failure modes and cost reporting.

Implementing a real backend means first verifying the provider's current API,
auth and parameters against its official documentation and recording the result
in docs/decisions/ -- CLAUDE.md non-negotiable rule 1. A stub that guessed at an
endpoint would violate exactly the rule the project cares most about.

fal.ai is implemented on that basis in `fal.py`, against the contract recorded
in docs/decisions/0006-fal-api-contract.md. Every other backend is still
unimplemented on purpose.

The fake backends generate offline fixture media so the whole pipeline can be
run and validated before a penny is spent.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image, ImageDraw

from .config import ProviderConfig
from .errors import ProviderNotConfigured


@dataclass
class ImageRequest:
    prompt: str
    seed: int
    ref: str
    lora_version: str | None = None


@dataclass
class VideoRequest:
    keyframe: Path
    prompt: str
    duration_s: float
    seed: int
    ref: str
    #: Optional second still pinning the LAST frame. Supplying it asks the
    #: provider for first/last-frame conditioning: the model interpolates
    #: between two known states instead of inventing the end of the motion.
    #: That is the fix for the one reproducible Veo failure measured so far --
    #: a face that leaves frame and returns comes back reconstructed rather
    #: than continued (docs/reports/occlusion-return-failure-2026-09-24.md).
    #: Which model id can accept it is a config question, not a code one; a
    #: model that cannot returns a free 422 saying so.
    last_keyframe: Path | None = None


@dataclass
class LipSyncRequest:
    clip: Path
    audio: Path | None
    ref: str


class ImageProvider(Protocol):
    name: str

    def generate(self, req: ImageRequest, dest: Path) -> Path: ...


class VideoProvider(Protocol):
    name: str

    def generate(self, req: VideoRequest, dest: Path) -> Path: ...


class LipSyncProvider(Protocol):
    name: str

    def apply(self, req: LipSyncRequest, dest: Path) -> Path: ...


_REGISTRY: dict[tuple[str, str], Callable[[ProviderConfig], Any]] = {}


def register_provider(kind: str, backend: str, factory: Callable[[ProviderConfig], Any]) -> None:
    _REGISTRY[(kind, backend)] = factory


def load_provider(cfg: ProviderConfig) -> Any:
    if cfg.backend is None:
        raise ProviderNotConfigured(
            f"providers.{cfg.kind}.{cfg.slot} has no backend. Verify the provider "
            f"against its current official documentation, record the findings in "
            f"docs/decisions/, then implement it and register_provider() it here."
        )
    try:
        factory = _REGISTRY[(cfg.kind, cfg.backend)]
    except KeyError:
        known = ", ".join(sorted(b for k, b in _REGISTRY if k == cfg.kind)) or "(none)"
        raise ProviderNotConfigured(
            f"No {cfg.kind} backend registered under {cfg.backend!r}. Registered: {known}."
        ) from None
    return factory(cfg)


# --------------------------------------------------------------------------
# Fake backends: offline fixture media
# --------------------------------------------------------------------------

_SIZE = (256, 256)


def _identity_palette(identity: str) -> tuple[tuple[int, int, int], ...]:
    """Stable, well-separated colours per identity string."""
    digest = hashlib.sha256(identity.encode()).digest()
    return tuple(
        (digest[i] | 0x40, digest[i + 1] | 0x40, digest[i + 2] | 0x40) for i in (0, 3, 6, 9)
    )


def render_fake_face(
    identity: str,
    variation: int = 0,
    drift_to: str | None = None,
    drift: float = 0.0,
    size: tuple[int, int] = _SIZE,
) -> Image.Image:
    """A synthetic 'face': stable geometry tinted by identity.

    Not remotely a face. It exists so the stub embedder produces similarity
    structure that behaves like the real thing -- same identity clusters,
    different identities separate, and ``drift`` moves one towards another so
    the scorer's ability to catch drift can itself be tested.
    """
    palette = _identity_palette(identity)
    if drift_to is not None and drift > 0:
        other = _identity_palette(drift_to)
        palette = tuple(
            (
                round(p[0] * (1 - drift) + q[0] * drift),
                round(p[1] * (1 - drift) + q[1] * drift),
                round(p[2] * (1 - drift) + q[2] * drift),
            )
            for p, q in zip(palette, other, strict=True)
        )
    img = Image.new("RGB", size, palette[0])  # type: ignore[arg-type]
    d = ImageDraw.Draw(img)
    w, h = size
    jitter = (variation % 5) - 2
    d.ellipse([w * 0.2 + jitter, h * 0.12, w * 0.8 + jitter, h * 0.92], fill=palette[1])  # type: ignore[arg-type]
    d.ellipse([w * 0.33, h * 0.38, w * 0.44, h * 0.47], fill=palette[2])  # type: ignore[arg-type]
    d.ellipse([w * 0.56, h * 0.38, w * 0.67, h * 0.47], fill=palette[2])  # type: ignore[arg-type]
    d.ellipse([w * 0.44, h * 0.52, w * 0.56, h * 0.64], fill=palette[3])  # type: ignore[arg-type]
    d.arc([w * 0.36, h * 0.60, w * 0.64, h * 0.80], 20, 160, fill=palette[3], width=4)  # type: ignore[arg-type]
    return img


@dataclass
class FakeImageProvider:
    """Emits a single still. Free, offline, marked as fake in the ledger."""

    cfg: ProviderConfig
    identity: str = "throwaway-look-a"
    name: str = field(default="fake-image", init=False)

    def generate(self, req: ImageRequest, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        render_fake_face(self.identity, variation=req.seed % 7).save(dest)
        return dest


@dataclass
class FakeVideoProvider:
    """Emits a clip as a directory of stills, with configurable identity drift.

    ``drift_per_second`` is the whole point: it simulates the failure mode the
    spike exists to measure (the face wandering during animation) so the
    scoring and reporting path can be validated against a known answer before
    it is pointed at real, expensive, ambiguous output.
    """

    cfg: ProviderConfig
    identity: str = "throwaway-look-a"
    drift_identity: str = "other-face-b"
    #: None means "vary deterministically by seed", which is what the demo and
    #: the tests want: a run where every clip passes proves only that the
    #: harness runs, not that the scorer can tell a drifted take from a good
    #: one. Set a float to pin the drift rate for a specific test.
    drift_per_second: float | None = None
    max_drift_per_second: float = 0.22
    native_fps: float = 8.0
    #: Frames where the fake "loses" the face entirely. None means derive from
    #: the seed, so some clips exercise the face-presence rule.
    no_face_frames: tuple[int, ...] | None = None
    name: str = field(default="fake-video", init=False)

    def _drift_for(self, seed: int) -> float:
        if self.drift_per_second is not None:
            return self.drift_per_second
        # Five bands from clean to badly drifted, spread across seeds.
        return (seed % 5) / 4.0 * self.max_drift_per_second

    def _no_face_for(self, seed: int, total: int) -> tuple[int, ...]:
        if self.no_face_frames is not None:
            return self.no_face_frames
        if seed % 7 != 0:  # most clips keep the face throughout
            return ()
        start = total // 3
        return tuple(range(start, min(total, start + max(1, total // 5))))

    def generate(self, req: VideoRequest, dest: Path) -> Path:
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        total = max(1, round(req.duration_s * self.native_fps))
        drift_rate = self._drift_for(req.seed)
        lost = self._no_face_for(req.seed, total)
        for i in range(total):
            t = i / self.native_fps
            drift = min(1.0, drift_rate * t)
            marker = "__noface" if i in lost else ""
            render_fake_face(
                self.identity,
                variation=(req.seed + i) % 7,
                drift_to=self.drift_identity,
                drift=drift,
            ).save(dest / f"frame_{i:05d}{marker}.png")
        return dest


@dataclass
class FakeLipSyncProvider:
    """Re-emits a clip with the jaw opened and the mouth reshaped.

    Enough to make task S0.8's question -- does lip sync move the identity
    score, and by how much -- answerable end to end offline.
    """

    cfg: ProviderConfig
    mouth_drift: float = 0.18
    jaw_stretch: float = 0.12
    name: str = field(default="fake-lipsync", init=False)

    def apply(self, req: LipSyncRequest, dest: Path) -> Path:
        src, dest = Path(req.clip), Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        for frame in sorted(src.glob("*.png")):
            with Image.open(frame) as img:
                out = self.reshape(img.convert("RGB"))
            out.save(dest / frame.name)
        return dest

    def reshape(self, img: Image.Image) -> Image.Image:
        """Open the jaw: stretch the lower face, then blend the mouth.

        GEOMETRIC, not a tint. An earlier version blended the whole frame
        towards a colour and produced a delta of exactly zero, because the stub
        embedder subtracts the mean before normalising -- so a uniform
        contraction towards a constant is invisible to it. That is a real
        property of an instrument worth knowing: an embedder can be completely
        blind to a class of change a human sees immediately. Real lip sync
        moves pixels, so the fixture moves pixels.
        """
        w, h = img.size
        top = int(h * 0.55)
        lower = img.crop((0, top, w, h))
        stretched = lower.resize(
            (w, int((h - top) * (1.0 + self.jaw_stretch))), Image.Resampling.BILINEAR
        )
        out = img.copy()
        out.paste(stretched.crop((0, 0, w, h - top)), (0, top))

        arr = np.asarray(out, dtype=np.float32)
        mouth = (slice(int(h * 0.60), int(h * 0.85)), slice(int(w * 0.32), int(w * 0.68)))
        target = np.array([210.0, 180.0, 180.0], dtype=np.float32)
        arr[mouth] = np.clip(
            arr[mouth] * (1.0 - self.mouth_drift) + target * self.mouth_drift, 0, 255
        )
        return Image.fromarray(arr.astype(np.uint8))


def _fal_video(cfg: ProviderConfig) -> Any:
    """Built on demand so this module imports no backend.

    fal.py imports the request types defined above, so importing it at module
    level here would be circular. Deferring to call time removes the cycle
    entirely rather than relying on import ordering, which is the kind of thing
    that works until someone moves a line.
    """
    from .fal import FalVideoProvider

    return FalVideoProvider(cfg, extra_arguments=cfg.options or None)


register_provider("video", "fal", _fal_video)
register_provider("image", "fake", lambda cfg: FakeImageProvider(cfg))
register_provider("video", "fake", lambda cfg: FakeVideoProvider(cfg))
register_provider("lipsync", "fake", lambda cfg: FakeLipSyncProvider(cfg))
