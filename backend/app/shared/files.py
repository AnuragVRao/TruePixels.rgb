"""Serving stored files through authenticated endpoints.

Nothing under ``config.STORAGE_ROOT`` is web-served directly any more: every
file goes out through an endpoint that has already checked ownership, and
through :func:`resolve_stored_file`, which additionally refuses any path that
does not resolve inside the directory it is meant to come from. File
references are written by the server, never by a client, so the containment
check is defence in depth rather than the primary control.
"""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.responses import FileResponse, Response

from app.shared.errors import AppException

_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
# Per-user content: never stored by a shared cache.
_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}

THUMBNAIL_MAX_SIDE = 256


def resolve_stored_file(reference: str | None, root: Path, not_found: AppException) -> Path:
    """The resolved path of ``reference`` if it is an image file inside ``root``.

    Raises ``not_found`` - the same error the caller uses for "not yours" -
    for a missing reference, a missing file, a path outside ``root`` (after
    resolving ``..`` and links) or an unexpected file type, so the response
    never reveals which of those it was.
    """
    if not reference:
        raise not_found
    path = Path(reference)
    if not path.is_absolute():
        path = root / path
    try:
        path = path.resolve(strict=True)
        path.relative_to(root.resolve())
    except (OSError, ValueError):
        raise not_found from None
    if path.suffix.lower() not in _MEDIA_TYPES or not path.is_file():
        raise not_found
    return path


def stored_file_response(reference: str | None, root: Path, not_found: AppException) -> FileResponse:
    """A ``FileResponse`` for a stored image, after :func:`resolve_stored_file`."""
    path = resolve_stored_file(reference, root, not_found)
    return FileResponse(path, media_type=_MEDIA_TYPES[path.suffix.lower()], headers=_HEADERS)


def thumbnail_response(reference: str | None, root: Path, not_found: AppException) -> Response:
    """A JPEG at most ``THUMBNAIL_MAX_SIDE`` px on its longer side.

    Made on the fly from the stored original (already EXIF-transposed and
    stripped at upload); never written to disk.
    """
    from PIL import Image

    path = resolve_stored_file(reference, root, not_found)
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
    except OSError:
        raise not_found from None
    return Response(buffer.getvalue(), media_type="image/jpeg", headers=_HEADERS)
