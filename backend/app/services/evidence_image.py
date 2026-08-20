"""Compresses evidence image uploads before they reach disk.

Mobile camera photos routinely arrive as several MB; evidence only needs to
show a reviewer what happened, not be a high-resolution archival copy. Every
accepted image is downscaled and re-encoded as JPEG - the one format that
actually compresses a photo well - so what `task_progress.py` /
`project_gate_submission.py` checksum, size-check, and write to disk is
always the compressed result, not the original upload. PDFs pass through
untouched; compressing a document format is out of scope here.
"""

from __future__ import annotations

from io import BytesIO

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_DIMENSION_PX = 1600
JPEG_QUALITY = 75
COMPRESSED_CONTENT_TYPE = "image/jpeg"

_COMPRESSIBLE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def compress_evidence_image(data: bytes, content_type: str) -> tuple[bytes, str]:
    """Returns (bytes, content_type). Anything not in
    `_COMPRESSIBLE_MIME_TYPES` (a PDF) is returned unchanged."""
    if content_type not in _COMPRESSIBLE_MIME_TYPES:
        return data, content_type

    try:
        image = Image.open(BytesIO(data))
        image.load()
    except UnidentifiedImageError as exc:
        raise HTTPException(422, "Evidence image could not be read.") from exc

    # Mobile cameras store pixels in sensor orientation and rely on an EXIF
    # tag to say how to rotate them for display. A re-encode that drops
    # that tag (as ours does - JPEG output below carries no EXIF) would
    # silently turn a right-way-up photo sideways, so the rotation is baked
    # into the pixels here, before the tag is lost.
    image = ImageOps.exif_transpose(image) or image

    if image.mode != "RGB":
        image = image.convert("RGB")

    image.thumbnail((MAX_DIMENSION_PX, MAX_DIMENSION_PX), Image.LANCZOS)

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    compressed = buffer.getvalue()

    # A rare already-tiny/pre-optimized image can come back larger after
    # re-encoding - never let "compression" make the stored file bigger.
    if content_type == COMPRESSED_CONTENT_TYPE and len(compressed) >= len(data):
        return data, content_type
    return compressed, COMPRESSED_CONTENT_TYPE
