"""Vendored inference subset of SPAI (mever-team/spai), Apache-2.0.

See NOTICE in this directory for provenance and the list of local edits.
"""

from .config import build_config
from .sid import PatchBasedMFViT, build_mf_vit

__all__ = ["PatchBasedMFViT", "build_config", "build_mf_vit"]
