from __future__ import annotations

import unittest
from io import BytesIO

from fastapi import HTTPException
from PIL import Image

from app.services.evidence_image import COMPRESSED_CONTENT_TYPE, compress_evidence_image


def _jpeg_bytes(size=(2400, 1800), color=(200, 50, 50)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG", quality=100)
    return buffer.getvalue()


def _png_bytes(size=(2400, 1800), color=(30, 120, 200)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class EvidenceImageCompressionTests(unittest.TestCase):
    """Mobile evidence photos arrive several MB uncompressed; this is what
    keeps a multi-project evidence store inside a free storage tier."""

    def test_a_large_jpeg_is_shrunk(self):
        original = _jpeg_bytes()
        compressed, content_type = compress_evidence_image(original, "image/jpeg")
        self.assertEqual(content_type, COMPRESSED_CONTENT_TYPE)
        self.assertLess(len(compressed), len(original))

    def test_a_png_is_converted_and_shrunk(self):
        original = _png_bytes()
        compressed, content_type = compress_evidence_image(original, "image/png")
        self.assertEqual(content_type, COMPRESSED_CONTENT_TYPE)
        self.assertLess(len(compressed), len(original))
        image = Image.open(BytesIO(compressed))
        self.assertEqual(image.format, "JPEG")

    def test_dimensions_are_capped(self):
        compressed, _ = compress_evidence_image(_jpeg_bytes(size=(4000, 3000)), "image/jpeg")
        image = Image.open(BytesIO(compressed))
        self.assertLessEqual(max(image.size), 1600)

    def test_aspect_ratio_is_preserved(self):
        compressed, _ = compress_evidence_image(_jpeg_bytes(size=(4000, 2000)), "image/jpeg")
        image = Image.open(BytesIO(compressed))
        self.assertAlmostEqual(image.size[0] / image.size[1], 2.0, places=1)

    def test_a_pdf_passes_through_untouched(self):
        original = b"%PDF-1.4 fake pdf bytes"
        compressed, content_type = compress_evidence_image(original, "application/pdf")
        self.assertEqual(compressed, original)
        self.assertEqual(content_type, "application/pdf")

    def test_an_already_tiny_jpeg_is_never_made_larger(self):
        original = _jpeg_bytes(size=(20, 20))
        compressed, content_type = compress_evidence_image(original, "image/jpeg")
        self.assertEqual(content_type, "image/jpeg")
        self.assertLessEqual(len(compressed), len(original))

    def test_unreadable_bytes_raise_422(self):
        with self.assertRaises(HTTPException) as ctx:
            compress_evidence_image(b"not an image", "image/jpeg")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_exif_rotation_is_baked_in_not_dropped(self):
        # A portrait-shaped source stored with the sensor-orientation EXIF
        # tag Pillow's ImageOps.exif_transpose reads (6 = rotate 90 CCW to
        # display upright) must come out compressed with the DISPLAY
        # orientation, since the JPEG re-encode carries no EXIF forward.
        exif = Image.Exif()
        exif[274] = 6  # Orientation tag: rotate 90 CCW to display upright.
        buffer = BytesIO()
        Image.new("RGB", (3000, 4000), (10, 10, 10)).save(buffer, format="JPEG", exif=exif.tobytes())
        compressed, _ = compress_evidence_image(buffer.getvalue(), "image/jpeg")
        image = Image.open(BytesIO(compressed))
        # Orientation 6 swaps width/height on display.
        self.assertGreater(image.size[0], image.size[1])


if __name__ == "__main__":
    unittest.main()
