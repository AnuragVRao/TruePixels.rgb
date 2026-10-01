"""
URLs for stored files (INTEGRATION).

Files under the storage tree are no longer web-served directly: the old
``/static`` mount exposed every user's uploads without authentication
(changes.md). Each URL here points at an endpoint that checks ownership
before streaming the file, so the URLs carry ids, never filesystem paths.
"""
from __future__ import annotations


def image_file_url(image_id: int) -> str:
    """The original upload, served by M1's owner-checked endpoint."""
    return f"/api/v1/images/{image_id}/file"


def explainability_file_url(prediction_id: int, branch: str) -> str:
    """One explainability panel, served by M3's owner-checked endpoint."""
    return f"/api/v1/explainability/{prediction_id}/{branch}"
