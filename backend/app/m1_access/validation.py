"""Four-stage image validation pipeline.

Conforms to PRD Section 5.2 and Module Interface Contract Section 3.4 / 4.2.
Processes 0.2.1 to 0.2.5:
  1. Streamed size cap & SHA-256 computation
  2. Magic-byte sniffing (JPEG/PNG)
  3. Dimension bounding (min 64px, max pixel bomb limit)
  4. Pillow double-pass integrity verification (verify + load)
"""
import hashlib
import io
from typing import Tuple
from fastapi import UploadFile
from PIL import Image, ImageFile
from app.m1_access.config import (
    MAX_UPLOAD_SIZE_BYTES,
    MIN_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
)
from app.shared.errors import (
    ImgCorruptedException,
    ImgFormatUnsupportedException,
    ImgTooLargeException,
)

# Promote truncated image warnings to hard errors (PRD §5.2.4)
ImageFile.LOAD_TRUNCATED_IMAGES = False
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

# Signatures for magic-byte sniffing
JPEG_SOI = b"\xff\xd8\xff"
JPEG_EOI = b"\xff\xd9"
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


async def validate_and_read_image_stream(
    upload_file: UploadFile,
) -> Tuple[bytes, str, str, int]:
    """Stage 1: Streams file with memory bounding and computes SHA-256 on the fly.

    Returns:
        (image_bytes, content_sha256, detected_format, file_size)
    """
    hasher = hashlib.sha256()
    buffer = io.BytesIO()
    total_bytes = 0
    chunk_size = 64 * 1024  # 64 KB chunks

    while True:
        chunk = await upload_file.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > MAX_UPLOAD_SIZE_BYTES:
            raise ImgTooLargeException(
                f"File size exceeds maximum allowed limit of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB."
            )
        hasher.update(chunk)
        buffer.write(chunk)

    if total_bytes == 0:
        raise ImgCorruptedException("Uploaded file is empty (0 bytes).")

    image_bytes = buffer.getvalue()
    content_sha256 = hasher.hexdigest()

    # Stage 2: Magic-Byte Sniffing (PRD §5.2.2)
    detected_format = sniff_image_format(image_bytes)

    # Stage 3 & 4: Integrity and Dimension Checks (PRD §5.2.3, §5.2.4)
    validate_image_integrity_and_dimensions(image_bytes, detected_format)

    return image_bytes, content_sha256, detected_format, total_bytes


def sniff_image_format(data: bytes) -> str:
    """Sniffs magic bytes to determine actual file format.

    Never trusts user-supplied Content-Type or file extension.
    """
    if data.startswith(JPEG_SOI):
        # Additional check: valid standard JPEG should contain EOI marker
        if not data.endswith(JPEG_EOI) and JPEG_EOI not in data[-10:]:
            # Some JPEGs have trailing padding/exif, but if it lacks EOI completely or is severely broken
            # double pass will catch it. Mark as JPEG here.
            pass
        return "JPEG"
    elif data.startswith(PNG_HEADER):
        return "PNG"
    else:
        raise ImgFormatUnsupportedException(
            "Unsupported file format. Only true JPG, JPEG and PNG images are accepted."
        )


def validate_image_integrity_and_dimensions(data: bytes, detected_format: str) -> Tuple[int, int]:
    """Performs Pillow double-pass integrity verification and enforces dimension rules."""
    # Pass 1: Structural check (verify)
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception as e:
        raise ImgCorruptedException(f"Structural verification failed: {e}")

    # Pass 2: Re-open and force full pixel decompression (load)
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            width, height = img.size

            # Check decompression bomb pixel bounds
            if width * height > MAX_IMAGE_PIXELS:
                raise ImgTooLargeException(
                    f"Image pixel dimensions ({width}x{height}) exceed maximum allowed limit."
                )

            # Check minimum dimension rule (PRD C.9: min 64px)
            if min(width, height) < MIN_IMAGE_DIMENSION:
                raise ImgCorruptedException(
                    f"Image dimension ({width}x{height}) is too small. Both width and height must be at least {MIN_IMAGE_DIMENSION}px."
                )

            return width, height
    except (ImgTooLargeException, ImgCorruptedException):
        raise
    except Exception as e:
        raise ImgCorruptedException(f"Image decompression and integrity check failed: {e}")
