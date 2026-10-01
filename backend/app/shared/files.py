"""Serving stored files through authenticated endpoints.

Nothing under ``config.STORAGE_ROOT`` is web-served directly any more: every
file goes out through an endpoint that has already checked ownership, and
through :func:`stored_file_response`, which additionally refuses any path
that does not resolve inside the directory it is meant to come from. File
references are written by the server, never by a client, so the containment
check is defence in depth rather than the primary control.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse

from app.shared.errors import AppException

_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def stored_file_response(reference: str | None, root: Path, not_found: AppException) -> FileResponse:
    """A ``FileResponse`` for ``reference`` if it is an image file inside ``root``.

    Raises ``not_found`` - the same error the caller uses for "not yours" -
    for a missing reference, a missing file, a path outside ``root`` or an
    unexpected file type, so the response never reveals which of those it was.
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
    media_type = _MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None or not path.is_file():
        raise not_found
    return FileResponse(
        path,
        media_type=media_type,
        # Per-user content: never stored by a shared cache.
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
