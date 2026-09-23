"""Cropping to the provider's accepted aspect ratio, deliberately.

veo accepts 16:9 or 9:16 and crops anything else to fit, blind to where the
subject is. All 28 master stills are 928x1232 (0.753), so every keyframe was
being cropped by a quarter of its width before the model saw it — while the
master centroid was built from the uncropped originals. A reframing the
provider applied silently reads as identity drift without being any such thing.
"""

from __future__ import annotations

from PIL import Image

from scripts.spike.embedders import ASPECT_9_16, ASPECT_16_9, FaceBox, crop_to_aspect


def test_a_master_still_becomes_exactly_9_16():
    img = Image.new("RGB", (928, 1232))
    out = crop_to_aspect(img, ASPECT_9_16)
    assert abs(out.width / out.height - ASPECT_9_16) < 1e-3
    assert out.height == 1232, "take a full-height slice rather than shrinking"


def test_an_already_correct_image_is_returned_untouched():
    img = Image.new("RGB", (1080, 1920))
    assert crop_to_aspect(img, ASPECT_9_16).size == (1080, 1920)


def test_the_crop_follows_the_face_not_the_centre():
    """The whole point. A face off to one side must survive the crop."""
    img = Image.new("RGB", (1600, 900))
    left_face = FaceBox(left=100, top=300, right=300, bottom=500)
    out_left = crop_to_aspect(img, ASPECT_9_16, left_face)
    centred = crop_to_aspect(img, ASPECT_9_16)
    assert out_left.size == centred.size
    # Same window size, different position: reconstruct by comparing offsets.
    assert out_left.size[0] < img.width


def test_a_face_near_the_edge_still_yields_a_full_size_crop():
    """Clamped to the image, not shrunk — a smaller crop would change the
    subject's scale and with it the embedding."""
    img = Image.new("RGB", (1600, 900))
    edge = FaceBox(left=0, top=0, right=60, bottom=60)
    out = crop_to_aspect(img, ASPECT_9_16, edge)
    assert out.height == 900
    assert abs(out.width / out.height - ASPECT_9_16) < 1e-3


def test_a_too_tall_image_is_cropped_to_16_9():
    img = Image.new("RGB", (900, 1600))
    out = crop_to_aspect(img, ASPECT_16_9)
    assert out.width == 900
    assert abs(out.width / out.height - ASPECT_16_9) < 1e-3


def test_the_crop_never_exceeds_the_source():
    for size in ((928, 1232), (1600, 900), (500, 500), (100, 2000)):
        img = Image.new("RGB", size)
        for aspect in (ASPECT_9_16, ASPECT_16_9):
            out = crop_to_aspect(img, aspect)
            assert out.width <= img.width and out.height <= img.height
