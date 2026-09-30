"""Failures the pipeline raises, named so a caller can tell them apart."""

from __future__ import annotations


class PipelineError(RuntimeError):
    """Base for anything the assembly pipeline refuses to do."""


class FfmpegMissing(PipelineError):
    """ffmpeg or ffprobe is not on PATH. Rendering needs both."""


class DisclosureFailed(PipelineError):
    """The overlay pass did not run, or was asked to produce something invalid.

    Never caught and ignored: a render without the overlay is not a render this system
    is permitted to produce.
    """


class AssemblyFailed(PipelineError):
    """The rough cut could not be built from the edit list."""
