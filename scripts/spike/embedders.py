"""Real embedder backends for the ADR 0002 bake-off.

Two candidates, both free and self-hosted, chosen because they are the only
routes that are commercially usable today without buying a licence:

* ``dlib`` -- a genuine face recognition model. Two variants ship in
  dlib-models and they are NOT interchangeable, on either axis that matters:

  - ``dlib_face_recognition_resnet_model_v1`` (128-d, 99.38% LFW). Covered by
    the repository's public-domain statement, which is scoped to "trained
    models created by me (Davis King)". Residual risk upstream: part of the
    training data (FaceScrub) is non-commercial.
  - ``face_recognition_densenet_model_v1`` (96.1% LFW). A third-party
    contribution from the BAREL project, so that public-domain statement does
    NOT reach it -- it covers its author's own models. BAREL licenses it MIT,
    an explicit grant from the actual author rather than an informal note, but
    its recognition training set is not documented.

  Set ``dim`` to match whichever file is configured. The embedder checks the
  descriptor it gets back and refuses on a mismatch.
* ``dinov2`` -- a general visual embedder under Apache 2.0, applied to a
  cropped face. Not a face recognition model, which is the point. Face
  recognisers are *trained to be invariant* to pose, lighting, expression, age,
  hairstyle and makeup -- precisely the drift a persona QA scorer needs to
  catch. A general embedder has no such invariance baked in. The cost is the
  mirror image: it also responds to background, clothing and framing, which is
  why the face is cropped before embedding.

Which one wins is an empirical question about *our* data, so both are wired up
and `cli.py bake-off` calibrates them side by side.

Detection is a SEPARATE licence question from recognition, and an easy one to
miss: the popular detectors ship with the same non-commercial packages as the
recognisers. Both detectors here avoid that.

No model file is ever downloaded automatically. Every path is explicit in
config, so pulling in weights stays a deliberate act with a licence attached to
it (CLAUDE.md: "Check licences for any model weights you pull in").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from .config import EmbedderConfig
from .embed import (
    MULTI_FACE,
    NO_FACE,
    OK,
    EmbedderInfo,
    FrameEmbedding,
    l2_normalise,
    register_embedder,
)
from .errors import EmbedderNotConfigured


def _require(module: str, install: str, why: str) -> Any:
    """Import a heavy optional dependency, or explain how to get it."""
    try:
        return __import__(module)
    except ImportError as exc:
        raise EmbedderNotConfigured(
            f"{why} needs the '{module}' package, which is not installed. "
            f"Install it with: {install}"
        ) from exc


def _require_path(options: dict[str, Any], key: str, backend: str, what: str) -> Path:
    value = options.get(key)
    if not value:
        raise EmbedderNotConfigured(
            f"embedder.backends.{backend}.{key} is not set. {what} "
            f"Download it yourself, record its licence in "
            f"docs/decisions/0002-face-embedding-model-licence.md, and put the local "
            f"path in config/spike.yaml. The harness never downloads weights on your "
            f"behalf: pulling in a model is a licence decision, not a cache miss."
        )
    path = Path(value)
    if not path.exists():
        raise EmbedderNotConfigured(f"embedder.backends.{backend}.{key}: no file at {path}")
    return path


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FaceBox:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class FaceDetector(Protocol):
    name: str
    licence: str

    def detect(self, image: Image.Image) -> list[FaceBox]: ...


def crop_with_margin(image: Image.Image, box: FaceBox, margin: float) -> Image.Image:
    """Crop to a face box, expanded by ``margin``, clamped to the image.

    Margin matters more than it looks. Too tight and the crop loses the jaw and
    hairline, which is where a lot of drift shows. Too loose and background
    starts driving the embedding -- the specific failure mode a general visual
    embedder is prone to, and the reason this function exists at all.
    """
    pad_x = int(box.width * margin)
    pad_y = int(box.height * margin)
    left = max(0, box.left - pad_x)
    top = max(0, box.top - pad_y)
    right = min(image.width, box.right + pad_x)
    bottom = min(image.height, box.bottom + pad_y)
    if right <= left or bottom <= top:
        return image
    return image.crop((left, top, right, bottom))


@dataclass
class YuNetDetector:
    """OpenCV's YuNet, via ``cv2.FaceDetectorYN``.

    Apache 2.0 in the OpenCV Zoo. The model file is not bundled with the pip
    package and must be fetched explicitly.
    """

    model_path: Path
    score_threshold: float = 0.7
    nms_threshold: float = 0.3
    name: str = field(default="yunet", init=False)
    licence: str = field(default="Apache-2.0 (OpenCV Zoo)", init=False)

    def detect(self, image: Image.Image) -> list[FaceBox]:
        cv2 = _require("cv2", "pip install opencv-python-headless", "The YuNet detector")
        arr = np.asarray(image.convert("RGB"))[:, :, ::-1]  # RGB -> BGR
        h, w = arr.shape[:2]
        detector = cv2.FaceDetectorYN.create(
            str(self.model_path), "", (w, h), self.score_threshold, self.nms_threshold
        )
        detector.setInputSize((w, h))
        _, faces = detector.detect(arr)
        if faces is None:
            return []
        out = []
        for face in faces:
            x, y, fw, fh = (int(v) for v in face[:4])
            out.append(FaceBox(x, y, x + fw, y + fh))
        return out


@dataclass
class DlibHogDetector:
    """dlib's classical HOG detector.

    Boost Software License, and no learned weights from a scraped dataset --
    which is why it sidesteps the provenance question that dogs the deep
    detectors.
    """

    upsample: int = 1
    name: str = field(default="dlib-hog", init=False)
    licence: str = field(default="Boost Software License 1.0 (dlib)", init=False)

    def detect(self, image: Image.Image) -> list[FaceBox]:
        dlib = _require("dlib", "pip install dlib", "The dlib HOG detector")
        arr = np.asarray(image.convert("RGB"))
        rects = dlib.get_frontal_face_detector()(arr, self.upsample)
        return [FaceBox(r.left(), r.top(), r.right(), r.bottom()) for r in rects]


@dataclass
class WholeImageDetector:
    """Treats the whole image as one face. No detection, no licence question.

    Two honest uses: stills that are already cropped to a face, and the
    embedder self-check, which needs to exercise the model without dragging
    detection into the same test. Everything else should detect properly --
    feeding DINOv2 an uncropped frame lets background and clothing drive the
    embedding, which is the failure mode ``crop_with_margin`` exists to avoid.
    """

    name: str = field(default="whole-image", init=False)
    licence: str = field(default="n/a (no model)", init=False)

    def detect(self, image: Image.Image) -> list[FaceBox]:
        return [FaceBox(0, 0, image.width, image.height)]


DETECTORS: dict[str, Any] = {
    "yunet": YuNetDetector,
    "dlib-hog": DlibHogDetector,
    "whole-image": WholeImageDetector,
}


def build_detector(options: dict[str, Any], backend: str) -> FaceDetector:
    name = options.get("detector", "yunet")
    if name not in DETECTORS:
        raise EmbedderNotConfigured(
            f"Unknown detector {name!r}. Available: {', '.join(sorted(DETECTORS))}."
        )
    if name == "whole-image":
        return WholeImageDetector()
    if name == "yunet":
        path = _require_path(
            options,
            "detector_model",
            backend,
            "YuNet's ONNX file is not bundled with the opencv pip package.",
        )
        return YuNetDetector(model_path=path)
    return DlibHogDetector()


# --------------------------------------------------------------------------
# Shared detection bookkeeping
# --------------------------------------------------------------------------


def detection_outcome(boxes: list[FaceBox], source: Path) -> FrameEmbedding | None:
    """Map a detection count to the no-face / multi-face contract.

    Returns a terminal :class:`FrameEmbedding` for 0 or >1 faces, or ``None``
    when there is exactly one and the caller should go on to embed it. Shared so
    both backends handle the exceptional cases identically -- the counts feed
    the face-presence rule in ``score.py``, and a backend that quietly picked
    the largest face out of two would break it.
    """
    if not boxes:
        return FrameEmbedding(0, 0.0, NO_FACE, faces=0, source=str(source))
    if len(boxes) > 1:
        return FrameEmbedding(0, 0.0, MULTI_FACE, faces=len(boxes), source=str(source))
    return None


# --------------------------------------------------------------------------
# dlib: a real face recognition model
# --------------------------------------------------------------------------


@dataclass
class DlibEmbedder:
    """dlib's ResNet face descriptor, 128-d.

    UNVERIFIED IN THIS REPOSITORY: dlib was not installable in the environment
    this was written in (it builds from source and timed out). The wiring and
    the detection contract are tested with a stand-in detector; the dlib calls
    themselves have not been executed. Run the bake-off before trusting it.
    """

    recognition_model: Path
    shape_predictor: Path
    licence: str | None
    jitter: int = 1
    #: NOT hardcoded. dlib-models ships more than one face descriptor and they
    #: are different networks -- the original ResNet is 128-d, the
    #: community-contributed DenseNet (BAREL) is something else. Pinning 128
    #: here would mis-shape the other one silently.
    dim: int = 128
    info: EmbedderInfo = field(init=False)

    def __post_init__(self) -> None:
        self.info = EmbedderInfo(
            backend="dlib",
            model=self.recognition_model.name,
            version="v1",
            dim=self.dim,
            licence=self.licence,
        )

    def embed_image(self, path: Path) -> FrameEmbedding:
        dlib = _require("dlib", "pip install dlib", "The dlib embedder")
        with Image.open(path) as img:
            image = img.convert("RGB")
        arr = np.asarray(image)
        rects = dlib.get_frontal_face_detector()(arr, 1)
        boxes = [FaceBox(r.left(), r.top(), r.right(), r.bottom()) for r in rects]
        terminal = detection_outcome(boxes, path)
        if terminal is not None:
            return terminal

        shape = dlib.shape_predictor(str(self.shape_predictor))(arr, rects[0])
        descriptor = dlib.face_recognition_model_v1(str(self.recognition_model))
        vector = np.array(
            descriptor.compute_face_descriptor(arr, shape, self.jitter), dtype=np.float32
        )
        if vector.shape[0] != self.dim:
            raise EmbedderNotConfigured(
                f"{self.recognition_model.name} produced a {vector.shape[0]}-d descriptor "
                f"but embedder.backends.dlib.dim says {self.dim}. Pin the real dimension: "
                f"a calibrated threshold is valid for exactly one model at one version "
                f"(amendment A3)."
            )
        return FrameEmbedding(0, 0.0, OK, faces=1, vector=l2_normalise(vector), source=str(path))


# --------------------------------------------------------------------------
# DINOv2: a general visual embedder on a cropped face
# --------------------------------------------------------------------------


@dataclass
class DinoV2Embedder:
    """DINOv2 CLS embedding of a cropped face. Apache 2.0.

    UNVERIFIED IN THIS REPOSITORY: torch and transformers were not installed in
    the environment this was written in. The crop geometry and the detection
    contract are tested; the model call is not.
    """

    hf_model: str
    detector: FaceDetector
    licence: str | None
    crop_margin: float = 0.25
    dim: int = 768
    info: EmbedderInfo = field(init=False)
    _model: Any = field(default=None, init=False, repr=False)
    _processor: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.info = EmbedderInfo(
            backend="dinov2",
            model=self.hf_model,
            version=f"crop{self.crop_margin}-{self.detector.name}",
            dim=self.dim,
            licence=self.licence,
        )

    def _load(self) -> tuple[Any, Any]:
        if self._model is None:
            _require("torch", "pip install torch", "The DINOv2 embedder")
            transformers = _require(
                "transformers", "pip install transformers", "The DINOv2 embedder"
            )
            self._processor = transformers.AutoImageProcessor.from_pretrained(self.hf_model)
            self._model = transformers.AutoModel.from_pretrained(self.hf_model)
            self._model.eval()
        return self._processor, self._model

    def embed_image(self, path: Path) -> FrameEmbedding:
        with Image.open(path) as img:
            image = img.convert("RGB")
        boxes = self.detector.detect(image)
        terminal = detection_outcome(boxes, path)
        if terminal is not None:
            return terminal

        face = crop_with_margin(image, boxes[0], self.crop_margin)
        processor, model = self._load()
        torch = _require("torch", "pip install torch", "The DINOv2 embedder")
        inputs = processor(images=face, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
        vector = outputs.last_hidden_state[0, 0].numpy().astype(np.float32)
        if vector.shape[0] != self.dim:
            raise EmbedderNotConfigured(
                f"{self.hf_model} produced a {vector.shape[0]}-d embedding but "
                f"embedder.backends.dinov2.dim says {self.dim}. Pin the real dimension: "
                f"a calibrated threshold is valid for exactly one model at one version."
            )
        return FrameEmbedding(0, 0.0, OK, faces=1, vector=l2_normalise(vector), source=str(path))


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def _build_dlib(cfg: EmbedderConfig) -> DlibEmbedder:
    return DlibEmbedder(
        recognition_model=_require_path(
            cfg.options, "recognition_model", "dlib", "dlib's face descriptor weights."
        ),
        shape_predictor=_require_path(
            cfg.options, "shape_predictor", "dlib", "dlib's facial landmark predictor."
        ),
        licence=cfg.licence,
        jitter=int(cfg.options.get("jitter", 1)),
        dim=int(cfg.dim or 128),
    )


def _build_dinov2(cfg: EmbedderConfig) -> DinoV2Embedder:
    return DinoV2Embedder(
        hf_model=str(cfg.options.get("hf_model") or cfg.model),
        detector=build_detector(cfg.options, "dinov2"),
        licence=cfg.licence,
        crop_margin=float(cfg.options.get("crop_margin", 0.25)),
        dim=int(cfg.dim or 768),
    )


register_embedder("dlib", _build_dlib)
# Same code path, different weights and licence. Its own backend so the two
# can be calibrated against each other rather than silently swapped.
register_embedder("dlib-densenet", _build_dlib)
register_embedder("dinov2", _build_dinov2)
