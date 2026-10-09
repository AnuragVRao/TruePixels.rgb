"""Uploaded classification heads (Phase 4, F.19) - loaded once, never mutated.

An uploaded head replaces only the final classifier of a branch; the
backbone stays the published one, resident and shared. Heads are cached by
the D3 row id that registered them, and a cached head is never modified -
activating a different row selects a different cached object - so a request
always uses exactly the head of the row it resolved at its start, even when
an admin activates another one meanwhile (Phase 7 runs requests in a
threadpool; GPU access itself is serialised there).

Files are safetensors only - tensors, no code - read with
``safetensors.torch.load_file``. Their SHA-256 is re-verified against the D3
row on every load, so a file changed on disk after registration is refused.
"""

from __future__ import annotations

import contextvars
import copy
import hashlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass

import torch
from torch import nn

from app.shared import config
from app.shared.contracts.errors import ModelUnavailableError

SEMANTIC_PREFIX = "classifier."
FREQUENCY_PREFIX = "cls_head."

_cache: dict[int, "LoadedHead"] = {}
_lock = threading.Lock()
# Inside no_store(), a head that is not cached yet is built for this call
# only and NOT added to the cache (the read-only gate preview, Phase 5b).
_no_store = contextvars.ContextVar("heads_no_store", default=False)


@contextmanager
def no_store():
    token = _no_store.set(True)
    try:
        yield
    finally:
        _no_store.reset(token)


@dataclass(frozen=True)
class LoadedHead:
    model_id: int
    module: nn.Module
    ai_index: int | None  # semantic heads only
    sha256: str


def file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _tensors(spec: dict) -> dict[str, torch.Tensor]:
    from safetensors.torch import load_file

    path = (config.MODELS_DIR / spec["file"]).resolve()
    path.relative_to((config.MODELS_DIR / "uploads").resolve())  # never outside uploads/
    if not path.is_file():
        raise ModelUnavailableError(f"head artefact {spec['file']} is missing")
    actual = file_sha256(path)
    if actual != spec["sha256"]:
        raise ModelUnavailableError(
            f"head artefact {spec['file']} changed on disk: sha256 {actual} != registered {spec['sha256']}"
        )
    return load_file(str(path), device="cpu")


def _strip(tensors: dict, prefix: str) -> dict:
    return {key[len(prefix):]: value for key, value in tensors.items()}


def build_semantic_head(tensors: dict, published: nn.Module) -> nn.Module:
    """A copy of the published classifier carrying the uploaded weights (strict)."""
    module = copy.deepcopy(published).cpu()
    module.load_state_dict(_strip(tensors, SEMANTIC_PREFIX), strict=True)
    return module.eval().requires_grad_(False).to(config.DEVICE)


def build_frequency_head(tensors: dict, published: nn.Module) -> nn.Module:
    module = copy.deepcopy(published).cpu()
    module.load_state_dict(_strip(tensors, FREQUENCY_PREFIX), strict=True)
    return module.eval().requires_grad_(False).to(config.DEVICE)


def semantic_head(model_id: int, spec: dict | None) -> LoadedHead | None:
    """The cached head for this D3 row, or None for the published head."""
    if not spec:
        return None
    from app.m2_analysis import detectors

    with _lock:
        if model_id not in _cache:
            # Uploaded semantic heads are SigLIP 2 classifier heads (the only
            # pinned content detector with a swappable head; registry._valid_semantic).
            siglip = detectors.semantic(config.SEMANTIC_SIGLIP)
            siglip.load()
            module = build_semantic_head(_tensors(spec), siglip._model.classifier)
            ai_index = detectors.resolve_ai_index({int(k): v for k, v in spec["id2label"].items()})
            loaded = LoadedHead(model_id, module, ai_index, spec["sha256"])
            if _no_store.get():
                return loaded
            _cache[model_id] = loaded
        return _cache[model_id]


def frequency_head(model_id: int, spec: dict | None) -> LoadedHead | None:
    if not spec:
        return None
    from app.m2_analysis import frequency_detector

    with _lock:
        if model_id not in _cache:
            module = build_frequency_head(_tensors(spec), frequency_detector.frequency.cls_head_module())
            loaded = LoadedHead(model_id, module, None, spec["sha256"])
            if _no_store.get():
                return loaded
            _cache[model_id] = loaded
        return _cache[model_id]


def cached_ids() -> set[int]:
    with _lock:
        return set(_cache)


def clear() -> None:
    """For tests only."""
    with _lock:
        _cache.clear()
