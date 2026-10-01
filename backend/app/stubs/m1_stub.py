"""
Module M1 Stub (Image & Access Management) according to Interface Contract Section 10.
Allows M3 to operate and test completely standalone.
"""
from __future__ import annotations
import os
import hashlib
from datetime import datetime, timezone, timedelta
import numpy as np
from PIL import Image
from sqlalchemy.orm import Session
from app.shared.schemas import PreprocessedImage, NormalizationParams, SessionContext
from app.m3_results.models import User, Image as DBImage


def create_dummy_user(db: Session, email: str = "testuser@nitk.edu.in", role: str = "User") -> User:
    """Helper to seed a test user."""
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return existing
    user = User(
        full_name="Debanshu Mitra",
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$dummyhash...",
        role=role,
        account_status="active",
        registered_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_dummy_image(
    db: Session,
    user_id: int,
    width: int = 800,
    height: int = 600,
    storage_dir: str = "./uploads/images",
) -> DBImage:
    """Creates a physical dummy image on disk and registers it in D2.images."""
    os.makedirs(storage_dir, exist_ok=True)
    img_filename = f"img_{user_id}_{width}x{height}.png"
    img_path = os.path.join(storage_dir, img_filename)

    # Generate image with gradient if not exists
    if not os.path.exists(img_path):
        img_arr = np.linspace(0, 255, width * height, dtype=np.uint8).reshape((height, width))
        rgb_arr = np.stack([img_arr, 255 - img_arr, (img_arr // 2)], axis=-1)
        pil_img = Image.fromarray(rgb_arr)
        pil_img.save(img_path, format="PNG")

    file_size = os.path.getsize(img_path)
    sha256 = hashlib.sha256(open(img_path, "rb").read()).hexdigest()

    db_img = DBImage(
        user_id=user_id,
        file_reference=img_path,
        content_sha256=sha256,
        file_format="PNG",
        file_size=file_size,
        width=width,
        height=height,
        upload_timestamp=datetime.now(timezone.utc),
        validation_status="valid",
    )
    db.add(db_img)
    db.commit()
    db.refresh(db_img)
    return db_img


def prepare_model_input(
    image_id: int,
    session: SessionContext,
    db: Session,
    tensor_dir: str = "./uploads/tensors",
) -> PreprocessedImage:
    """
    Contract C1 Stub: Returns PreprocessedImage pointing to a 3x224x224 float32 tensor
    and the native-resolution original image reference.
    """
    os.makedirs(tensor_dir, exist_ok=True)
    db_img = db.query(DBImage).filter(DBImage.image_id == image_id).first()
    if not db_img:
        raise ValueError(f"Image {image_id} not found in database.")

    tensor_path = os.path.join(tensor_dir, f"tensor_{image_id}.npy")
    if not os.path.exists(tensor_path):
        dummy_tensor = np.random.randn(3, 224, 224).astype(np.float32)
        np.save(tensor_path, dummy_tensor)

    return PreprocessedImage(
        image_id=image_id,
        user_id=session.user_id,
        tensor_ref=tensor_path,
        shape=(3, 224, 224),
        dtype="float32",
        normalization=NormalizationParams(
            mean=(0.48145466, 0.4578275, 0.40821073),
            std=(0.26862954, 0.26130258, 0.27577711),
            scheme="clip_openai",
        ),
        source_reference=db_img.file_reference,
        created_at=datetime.now(timezone.utc),
    )
