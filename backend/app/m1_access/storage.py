"""Content-addressed image storage with EXIF sanitization and path isolation.

Conforms to PRD Section 5.2.5 and 6.4 (Upload Safety).
"""
import io
from pathlib import Path
from typing import Tuple
from PIL import Image, ImageOps
from app.m1_access.config import UPLOADS_DIR, TENSORS_DIR


def get_content_addressed_path(content_sha256: str, ext: str) -> Path:
    """Calculates deterministic nested directory path: uploads/<sha[0:2]>/<sha[2:4]>/<sha>.<ext>"""
    prefix1 = content_sha256[:2]
    prefix2 = content_sha256[2:4]
    folder = UPLOADS_DIR / prefix1 / prefix2
    folder.mkdir(parents=True, exist_ok=True)
    extension = ext.lower().lstrip(".")
    if extension == "jpeg":
        extension = "jpg"
    return folder / f"{content_sha256}.{extension}"


def sanitize_and_persist_image(
    image_bytes: bytes,
    content_sha256: str,
    file_format: str,
) -> Tuple[str, int, int]:
    """Applies EXIF orientation, strips metadata (GPS/device info for privacy), and persists the image.

    Returns:
        (file_reference_path, width, height)
    """
    ext = "png" if file_format.upper() == "PNG" else "jpg"
    target_path = get_content_addressed_path(content_sha256, ext)

    # Open image with Pillow to handle EXIF and stripping
    with Image.open(io.BytesIO(image_bytes)) as img:
        # Correct orientation based on EXIF tag (if any)
        transposed_img = ImageOps.exif_transpose(img)
        if transposed_img is None:
            transposed_img = img

        width, height = transposed_img.size

        # If already on disk with identical content, we avoid duplicate write
        if not target_path.exists():
            # Save without EXIF metadata (data privacy control)
            if ext == "png":
                # Convert RGBA or RGB
                if transposed_img.mode not in ("RGB", "RGBA"):
                    clean_img = transposed_img.convert("RGBA" if "A" in transposed_img.mode else "RGB")
                else:
                    clean_img = transposed_img
                clean_img.save(target_path, format="PNG", optimize=True)
            else:
                # JPEG format
                clean_img = transposed_img.convert("RGB")
                clean_img.save(target_path, format="JPEG", quality=95, optimize=True)

    return str(target_path.resolve()), width, height


def get_tensor_path(image_id: int) -> Path:
    """Returns filesystem path for preprocessed model tensor (.npy)."""
    return TENSORS_DIR / f"{image_id}.npy"
