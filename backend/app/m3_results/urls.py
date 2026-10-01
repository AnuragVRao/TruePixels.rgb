"""
Maps stored file references to the URLs they are served at (INTEGRATION).

M3 originally built URLs as f"/static/{reference}", which only works for paths
relative to the server's working directory. M1 stores absolute paths
(e.g. C:/.../storage/uploads/ab/cd/<sha>.jpg), so that produced broken links.
main.py now serves the shared storage tree at /static, and this turns any path
inside it into its URL. See changes.md.
"""
from __future__ import annotations
from pathlib import Path
from app.shared import config


def storage_url(reference: str) -> str:
    """URL for a file under the shared storage tree, served at /static."""
    try:
        relative = Path(reference).resolve().relative_to(config.STORAGE_ROOT)
    except ValueError:
        # Outside the served tree: keep M3's original behaviour.
        return f"/static/{reference}"
    return f"/static/{relative.as_posix()}"
