"""Fetching the model weights the ADR 0002 candidates need.

This is a setup step you run once, by hand, on purpose. The harness itself
never downloads anything at runtime -- pulling in weights is a licence
decision, not a cache miss.

What this does NOT do is fill in the ``licence`` and ``licence_verified_on``
fields in config. It prints where to read each licence and leaves those blank,
because the whole point of the gate in ``EmbedderConfig.require_usable`` is that
somebody read the text. A fetcher that filled them in would defeat it.
"""

from __future__ import annotations

import bz2
import hashlib
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .errors import SpikeError

USER_AGENT = "persona-studio-spike/0 (model fetch)"
#: Anything smaller than this is almost certainly an error page, not a model.
MIN_PLAUSIBLE_BYTES = 10_000


@dataclass(frozen=True)
class ModelFile:
    key: str
    backend: str
    url: str
    filename: str
    config_key: str
    licence_where: str
    licence_note: str
    compressed: bool = False
    #: sha256 of the file as downloaded (before any decompression). Pinned
    #: where it is known, so a silently-changed or truncated file is caught
    #: before it becomes a calibration you cannot reproduce.
    sha256: str | None = None
    #: True for a file that is an ALTERNATIVE to another one filling the same
    #: config slot, rather than an addition. Skipped unless asked for by name,
    #: because fetching two candidates for one slot leaves you having to guess
    #: which the config means.
    optional: bool = False

    @property
    def final_name(self) -> str:
        return self.filename[:-4] if self.compressed else self.filename


MODELS: tuple[ModelFile, ...] = (
    ModelFile(
        key="dlib-recognition",
        backend="dlib",
        url="http://dlib.net/files/dlib_face_recognition_resnet_model_v1.dat.bz2",
        filename="dlib_face_recognition_resnet_model_v1.dat.bz2",
        config_key="recognition_model",
        licence_where="https://github.com/davisking/dlib-models/blob/master/README.md",
        licence_note=(
            "Author released the model file into the public domain. Part of the "
            "training data (FaceScrub) is non-commercial -- ADR 0002 Finding 1 "
            "records this as a counsel question. Read the README statement yourself "
            "and record it verbatim."
        ),
        compressed=True,
    ),
    ModelFile(
        key="dlib-densenet",
        backend="dlib",
        url="http://dlib.net/files/face_recognition_densenet_model_v1.dat.bz2",
        filename="face_recognition_densenet_model_v1.dat.bz2",
        config_key="recognition_model",
        licence_where="https://github.com/Cydral/BAREL",
        licence_note=(
            "ALTERNATIVE to dlib-recognition, not an addition -- both fill the same "
            "config slot. Third-party contribution from the BAREL project, so the "
            "dlib-models public-domain statement does NOT cover it: that statement is "
            "scoped to 'trained models created by me (Davis King)'. BAREL licenses it "
            "MIT, which is a cleaner grant (explicit, from the actual author) but its "
            "recognition training set is undocumented. Weaker too: 96.1% LFW against "
            "the ResNet's 99.38%. Set backends.dlib.dim to its real output size."
        ),
        compressed=True,
        optional=True,
    ),
    ModelFile(
        key="dlib-landmarks",
        backend="dlib",
        url="http://dlib.net/files/shape_predictor_5_face_landmarks.dat.bz2",
        filename="shape_predictor_5_face_landmarks.dat.bz2",
        config_key="shape_predictor",
        licence_where="https://github.com/davisking/dlib-models/blob/master/README.md",
        licence_note="Landmark predictor. Same README, check its own licence line (CC0).",
        compressed=True,
    ),
    ModelFile(
        key="yunet",
        backend="dinov2",
        # NOT raw.githubusercontent.com: opencv_zoo keeps .onnx files in Git LFS,
        # so raw/ serves a 131-byte pointer. The media endpoint serves the file.
        url=(
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
            "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
        ),
        filename="face_detection_yunet_2023mar.onnx",
        config_key="detector_model",
        licence_where=(
            "https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet"
        ),
        licence_note=(
            "Apache 2.0 per the model directory. Detection is a SEPARATE licence "
            "question from recognition (ADR 0002) -- do not assume it inherits."
        ),
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_a_model(path: Path) -> str | None:
    """Return a complaint if the download is obviously not a model file.

    Blocked egress, a login wall or a moved URL all return 200 with an HTML
    body. Saving that as a .dat and discovering it at calibration time would
    waste a day, so it is caught here.
    """
    head = path.read_bytes()[:512]
    if head.lstrip().startswith(b"version https://git-lfs.github.com/spec/v1"):
        return (
            "this is a Git LFS pointer, not the model. The repository stores this "
            "file in LFS, so raw.githubusercontent.com serves a stub. Fetch it from "
            "media.githubusercontent.com/media/... instead"
        )
    lowered = head.lstrip()[:64].lower()
    for marker in (b"<!doctype html", b"<html", b"<?xml", b"{", b"host not in allowlist"):
        if lowered.startswith(marker):
            return f"content starts with {lowered[:40]!r} -- looks like a web page or an error"
    # Size check comes last: it is the least specific diagnosis, and running it
    # first masked the LFS-pointer message, which is small AND actionable.
    size = path.stat().st_size
    if size < MIN_PLAUSIBLE_BYTES:
        return f"only {size} bytes -- almost certainly an error page, not a model"
    return None


def fetch(model: ModelFile, dest_dir: Path, force: bool = False) -> Path:
    """Download one model file, verify it is plausible, decompress if needed."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / model.final_name
    if final.exists() and not force:
        return final

    download_to = dest_dir / model.filename
    request = urllib.request.Request(model.url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            download_to.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        raise SpikeError(
            f"{model.key}: HTTP {exc.code} fetching {model.url}\n"
            f"  If this is 403 from a network proxy, the host needs allowing in your "
            f"egress settings. If it is 404, the upstream filename moved -- check "
            f"{model.licence_where} for the current one."
        ) from exc
    except urllib.error.URLError as exc:
        raise SpikeError(f"{model.key}: could not reach {model.url} ({exc.reason})") from exc

    complaint = _looks_like_a_model(download_to)
    if complaint:
        download_to.unlink(missing_ok=True)
        raise SpikeError(f"{model.key}: refusing to keep {model.url} -- {complaint}")

    if model.sha256:
        actual = sha256_of(download_to)
        if actual != model.sha256:
            download_to.unlink(missing_ok=True)
            raise SpikeError(
                f"{model.key}: sha256 mismatch.\n"
                f"  expected {model.sha256}\n"
                f"  got      {actual}\n"
                f"  The file upstream has changed, or the download was corrupted. Check "
                f"{model.licence_where} before updating the pin -- a changed model means "
                f"a changed embedding space, and any threshold calibrated against the old "
                f"one is void (amendment A3)."
            )

    if model.compressed:
        with bz2.open(download_to, "rb") as src, final.open("wb") as out:
            shutil.copyfileobj(src, out)
        download_to.unlink()
    return final


def clashing_slots(fetched: dict[str, Path]) -> list[str]:
    """Config slots that more than one fetched file wants to fill."""
    seen: dict[str, list[str]] = {}
    for model in MODELS:
        if model.key in fetched:
            seen.setdefault(f"{model.backend}.{model.config_key}", []).append(model.key)
    return [slot for slot, keys in seen.items() if len(keys) > 1]


def config_snippet(fetched: dict[str, Path]) -> str:
    """The YAML to paste, with licence fields deliberately left blank."""
    lines = ["embedder:", "  backends:"]
    for slot in clashing_slots(fetched):
        lines.insert(
            0,
            f"# NOTE: you have more than one file for {slot}. They are alternatives, "
            f"not additions -- keep the one you want and delete the other line.",
        )
    for backend in ("dlib", "dinov2"):
        keys = {
            m.config_key: fetched[m.key]
            for m in MODELS
            if m.backend == backend and m.key in fetched
        }
        if not keys:
            continue
        lines.append(f"    {backend}:")
        for key, path in keys.items():
            lines.append(f"      {key}: {path}")
        lines.append("      licence: null            # <- YOU fill this in, verbatim")
        lines.append("      licence_verified_on: null  # <- date you read the text")
    return "\n".join(lines)


def write_paths(config_path: Path, fetched: dict[str, Path]) -> list[str]:
    """Fill the model paths into config, and ONLY the paths.

    `licence` and `licence_verified_on` are left exactly as they are. A file
    path is mechanical — it says where a file landed. A licence is a decision
    about whether the terms are acceptable, and the gate in
    `EmbedderConfig.require_usable` exists so a person makes it. Writing both
    from here would quietly tick off the one that matters.
    """
    config_path = Path(config_path)
    lines = config_path.read_text().splitlines()
    wanted = {m.config_key: fetched[m.key] for m in MODELS if m.key in fetched}
    written: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        for key, path in wanted.items():
            if stripped.startswith(f"{key}:") and "null" in stripped:
                indent = line[: len(line) - len(line.lstrip())]
                lines[i] = f"{indent}{key}: {path}"
                written.append(f"{key} -> {path}")
                break

    config_path.write_text("\n".join(lines) + "\n")
    return written
