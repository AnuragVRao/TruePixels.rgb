"""Deterministic image preprocessing for CLIP and frequency branches.

Conforms strictly to PRD Section 5.3 and Module Interface Contract C1.
Processes:
  0.3.1 Receive validated image, handle EXIF orientation, convert to 3-channel RGB.
  0.3.2 Bicubic resize shorter side to 224, then 224x224 center crop.
  0.3.3 Scale to [0,1], normalize with CLIP mean/std.
  0.3.4 Transpose to (3, 224, 224) float32, persist .npy, assemble PreprocessedImage.
"""
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from sqlalchemy.orm import Session
from app.m1_access.models import Image as DBImage
from app.m1_access.storage import get_tensor_path
from app.shared.errors import ImgCorruptedException, ImgNotFoundException
from app.shared.schemas import NormalizationParams, PreprocessedImage, SessionContext

# CLIP standard normalization constants (PRD §5.3)
CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def preprocess_pil_to_clip_tensor(img: Image.Image) -> np.ndarray:
    """Performs deterministic bicubic resize, center-crop, and CLIP normalization.

    Returns:
        np.ndarray with shape (3, 224, 224) and dtype float32.
    """
    # 1. Ensure EXIF orientation is respected
    transposed = ImageOps.exif_transpose(img)
    if transposed is not None:
        img = transposed

    # 2. Collapse all color modes (Grayscale, Palette, RGBA, CMYK) to RGB (PRD 0.3.1)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # 3. Resize shorter side to 224 preserving aspect ratio using BICUBIC (PRD 0.3.2)
    width, height = img.size
    target_size = 224

    if width < height:
        new_width = target_size
        new_height = int(round(height * (target_size / width)))
    else:
        new_height = target_size
        new_width = int(round(width * (target_size / height)))

    resized = img.resize((new_width, new_height), resample=Image.Resampling.BICUBIC)

    # 4. Center crop to 224x224 (PRD 0.3.2)
    left = (new_width - target_size) // 2
    top = (new_height - target_size) // 2
    right = left + target_size
    bottom = top + target_size
    cropped = resized.crop((left, top, right, bottom))

    # 5. Convert to numpy array, scale to [0, 1] float32
    arr = np.array(cropped, dtype=np.float32) / 255.0

    # 6. Apply channel-wise CLIP normalization (PRD 0.3.3)
    # arr shape is (224, 224, 3) -> broadcast over channels
    normalized = (arr - CLIP_MEAN) / CLIP_STD

    # 7. Transpose to (Channels, Height, Width) -> (3, 224, 224)
    tensor = np.transpose(normalized, (2, 0, 1)).astype(np.float32)

    return tensor


def prepare_model_input(
    image_id: int,
    db: Session,
    session: SessionContext = None,
) -> PreprocessedImage:
    """Preprocesses a stored image and returns the Contract C1 PreprocessedImage hand-off."""
    db_img = db.query(DBImage).filter(DBImage.image_id == image_id).first()
    if not db_img:
        raise ImgNotFoundException(f"Image with id {image_id} does not exist.")

    image_path = Path(db_img.file_reference)
    if not image_path.exists():
        raise ImgCorruptedException(f"Image source file missing on disk: {db_img.file_reference}")

    # Load original image
    with Image.open(image_path) as img:
        tensor = preprocess_pil_to_clip_tensor(img)

    # Persist serialized tensor to .npy on shared storage
    tensor_path = get_tensor_path(image_id)
    np.save(tensor_path, tensor)

    return PreprocessedImage(
        image_id=db_img.image_id,
        user_id=db_img.user_id,
        tensor_ref=str(tensor_path.resolve()),
        shape=(3, 224, 224),
        dtype="float32",
        normalization=NormalizationParams(
            mean=(0.48145466, 0.4578275, 0.40821073),
            std=(0.26862954, 0.26130258, 0.27577711),
            scheme="clip_openai",
        ),
        source_reference=str(image_path.resolve()),
        created_at=datetime.now(timezone.utc),
    )
