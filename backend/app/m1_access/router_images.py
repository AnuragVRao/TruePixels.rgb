"""Image upload and management API router.

Conforms to PRD Section 5.2 / 6.3 and SRS F.5, F.6, F.7.
"""
from typing import Optional
from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from app.m1_access.models import Image as DBImage
from app.m1_access.schemas import ImageMetadataResponse, ImageUploadResponse
from app.m1_access.security import current_session
from app.m1_access.storage import sanitize_and_persist_image
from app.m1_access.validation import validate_and_read_image_stream
from app.shared import config as shared_config
from app.shared.db import get_db
from app.shared.files import stored_file_response, thumbnail_response
from app.shared.errors import (
    AppException,
    ImgNotFoundException,
)
from app.shared.logging import emit
from app.shared.schemas import SessionContext

router = APIRouter(prefix="/images", tags=["Image Upload & Validation"])


@router.post(
    "",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and validate a new image (F.5, F.6, F.7)",
)
async def upload_image(
    file: UploadFile = File(...),
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
):
    try:
        # Stage 1 - 4 Validation (Stream size cap, Magic bytes, Dimensions, Integrity)
        image_bytes, content_sha256, detected_format, file_size = await validate_and_read_image_stream(file)

        # Stage 5: Content-addressed persistence & EXIF stripping (PRD §5.2.5)
        file_reference, width, height = sanitize_and_persist_image(
            image_bytes=image_bytes,
            content_sha256=content_sha256,
            file_format=detected_format,
        )

        # Record in D2.images
        db_image = DBImage(
            user_id=session.user_id,
            file_reference=file_reference,
            content_sha256=content_sha256,
            file_format=detected_format,
            file_size=file_size,
            width=width,
            height=height,
            validation_status="valid",
            rejection_reason=None,
        )
        db.add(db_image)
        db.commit()
        db.refresh(db_image)

        # INTEGRATION: the Contract C1 preprocessing call that used to run here
        # built and saved a CLIP tensor nothing reads, and discarded its result;
        # removed (changes.md 6.3). C1 is assembled at prediction time.
        emit(
            "prediction-request",
            f"Image validated and stored: image_id={db_image.image_id}, sha256={content_sha256[:8]}...",
            severity="info",
            user_id=session.user_id,
        )

        return ImageUploadResponse(
            image_id=db_image.image_id,
            validation_status="valid",
            content_sha256=db_image.content_sha256,
            width=db_image.width,
            height=db_image.height,
            file_format=db_image.file_format,
        )

    except AppException as e:
        # Audit log rejection reason (PRD US-1.5 AC5)
        rejection_code = e.code.lower().replace("img_", "")
        emit(
            "error",
            f"Image upload rejected: code={e.code}, reason={e.message}",
            severity="warning",
            user_id=session.user_id,
        )
        raise e


@router.get(
    "/{image_id}",
    response_model=ImageMetadataResponse,
    status_code=status.HTTP_200_OK,
    summary="Get metadata for an uploaded image",
)
def get_image_metadata(
    image_id: int,
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
):
    image = db.query(DBImage).filter(DBImage.image_id == image_id).first()

    # Anti-enumeration rule (PRD §6.3): return IMG_NOT_FOUND if not found or belongs to another user
    if not image or (image.user_id != session.user_id and session.role != "Admin"):
        raise ImgNotFoundException(f"Image with id {image_id} not found.")

    return image


@router.get(
    "/{image_id}/file",
    status_code=status.HTTP_200_OK,
    summary="Download an uploaded image (owner only)",
    response_class=FileResponse,
)
def get_image_file(
    image_id: int,
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
):
    """INTEGRATION: replaces the unauthenticated /static mount (changes.md).

    Owner only - stricter than the metadata endpoint above, which also admits
    Admins. The file is the user's photograph itself, so least privilege
    applies (SRS F.4, NF.7), consistent with the explainability panels. Admin
    access, if it is ever needed, should come with a D6 audit entry. Same
    IMG_NOT_FOUND for "not yours" and "does not exist".
    """
    image = db.query(DBImage).filter(DBImage.image_id == image_id).first()
    try:
        if not image or image.user_id != session.user_id:
            raise ImgNotFoundException(f"Image with id {image_id} not found.")
        response = stored_file_response(
            image.file_reference,
            shared_config.UPLOADS_DIR,
            ImgNotFoundException(f"Image with id {image_id} not found."),
        )
    except ImgNotFoundException:
        # F.4: refused access is logged. The caller sees one 404 whatever the
        # reason; D6 records only the attempt, which is what an admin needs.
        emit("error", f"Image file refused: image_id={image_id}",
             severity="warning", user_id=session.user_id)
        raise
    emit("prediction-request", f"Image file served: image_id={image_id}",
         severity="info", user_id=session.user_id)
    return response


@router.get(
    "/{image_id}/thumbnail",
    status_code=status.HTTP_200_OK,
    summary="A small JPEG preview of an uploaded image (owner only)",
    response_class=Response,
)
def get_image_thumbnail(
    image_id: int,
    session: SessionContext = Depends(current_session),
    db: Session = Depends(get_db),
):
    """INTEGRATION: history-table previews (changes.md 6.4).

    Same owner-only rule and same IMG_NOT_FOUND as ``/file``. Refusals are
    audited exactly like ``/file``; routine successful serves are NOT, because
    one history page would otherwise write a D6 row per thumbnail. Full
    originals (``/file``) and PDF reports keep logging every serve - that is
    the audit trail for the actual image. This is a separate endpoint rather
    than a flag on ``/file`` so a client cannot opt a full download out of
    the audit log.
    """
    image = db.query(DBImage).filter(DBImage.image_id == image_id).first()
    try:
        if not image or image.user_id != session.user_id:
            raise ImgNotFoundException(f"Image with id {image_id} not found.")
        return thumbnail_response(
            image.file_reference,
            shared_config.UPLOADS_DIR,
            ImgNotFoundException(f"Image with id {image_id} not found."),
        )
    except ImgNotFoundException:
        emit("error", f"Image thumbnail refused: image_id={image_id}",
             severity="warning", user_id=session.user_id)
        raise
