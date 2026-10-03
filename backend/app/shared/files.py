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

from fastapi.responses import Response

from app.shared.errors import AppException

_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
# Per-user content: never stored by a shared cache.
_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}

THUMBNAIL_MAX_SIDE = 256


def resolve_stored_file(
    reference: str | None,
    root: Path,
    not_found: AppException,
    missing: AppException | None = None,
) -> Path:
    """The resolved path of ``reference`` if it is an image file inside ``root``.

    Raises ``not_found`` - the same error the caller uses for "not yours" -
    for an empty reference, a path outside ``root`` (after resolving ``..``
    and links) or an unexpected file type, so the response never reveals
    which of those it was.

    Raises ``missing`` instead (when given) for a reference that is safely
    inside ``root`` but whose file no longer exists. Callers only pass it
    after the ownership check, so it tells the OWNER something true ("your
    record survives, its file does not") without telling anyone else that
    the record exists.
    """
    if not reference:
        raise not_found
    path = Path(reference)
    if not path.is_absolute():
        path = root / path
    root = root.resolve()
    try:
        # Lexical containment first (".." collapsed, links followed where they
        # exist), so a missing file outside root is still "not found".
        path.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        raise not_found from None
    if not path.exists():
        raise missing if missing is not None else not_found
    try:
        path = path.resolve(strict=True)
        path.relative_to(root)  # again, now that every link is resolved
    except (OSError, ValueError):
        raise not_found from None
    if path.suffix.lower() not in _MEDIA_TYPES or not path.is_file():
        raise not_found
    return path


def stored_file_response(
    reference: str | None, root: Path, not_found: AppException, missing: AppException | None = None
) -> Response:
    """The stored image's bytes, after :func:`resolve_stored_file`.

    Read in full with a ``with`` block and sent from memory rather than as a
    streaming ``FileResponse``: every stored file is bounded (uploads <= 10 MB,
    panels a few MB), and the handle is then closed deterministically before
    the response is sent - a browser run on Windows found storage files left
    open by the server, which blocks deleting them (Phase 5a).
    """
    path = resolve_stored_file(reference, root, not_found, missing)
    with open(path, "rb") as handle:
        data = handle.read()
    return Response(data, media_type=_MEDIA_TYPES[path.suffix.lower()], headers=_HEADERS)


def thumbnail_response(
    reference: str | None, root: Path, not_found: AppException, missing: AppException | None = None
) -> Response:
    """A JPEG at most ``THUMBNAIL_MAX_SIDE`` px on its longer side.

    Made on the fly from the stored original (already EXIF-transposed and
    stripped at upload); never written to disk.
    """
    from PIL import Image

    path = resolve_stored_file(reference, root, not_found, missing)
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
    except OSError:
        raise not_found from None
    return Response(buffer.getvalue(), media_type="image/jpeg", headers=_HEADERS)
