"""One-time conversion of the released SPAI checkpoint to a tensors-only file.

    cd backend
    python scripts/convert_spai_checkpoint.py [path/to/spai.pth]

WHY THIS EXISTS. The authors publish ``spai.pth`` (Google Drive, ~935 MB) as a
pickled training checkpoint: model weights plus optimizer state, LR schedule
and a ``yacs.config.CfgNode`` holding the training configuration. Two things
follow:

1. ``torch.load(..., weights_only=True)`` refuses it, because the safe
   unpickler cannot rebuild a ``CfgNode``. Loading it with
   ``weights_only=False`` at every server start would mean running an
   unrestricted unpickler on a file fetched from a file-sharing link, on
   every boot. Not acceptable for the inference path.
2. Two thirds of the file is optimizer state that inference never reads.

So the conversion happens here, ONCE, offline, under a deliberately
restricted unpickler that admits torch / collections globals and exactly one
extra name - ``yacs.config.CfgNode`` - mapped to a plain dict. Anything else
in the pickle stream (``os.system``, ``builtins.eval``, ...) raises. The model
weights are then written as safetensors, which contains no code at all, and
the runtime loader in ``app/m2_analysis/frequency_detector.py`` reads only
that file, verified against a pinned digest of the weights.

NO WEIGHT IS MODIFIED. The output is ``checkpoint["model"]`` byte-for-byte,
re-serialised. The upstream file's own SHA-256 is verified before conversion
and recorded in the output's metadata, so provenance is traceable both ways.
"""

from __future__ import annotations

import hashlib
import pickle
import sys
import types
from pathlib import Path

import torch
from safetensors.torch import save_file

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.m2_analysis.frequency_detector import weights_digest  # noqa: E402
from app.shared import config  # noqa: E402


class _CfgNode(dict):
    """Stand-in for yacs.config.CfgNode: a dict that accepts pickled attributes."""

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)


_SAFE_BUILTINS = {"set", "frozenset"}  # the yacs config pickles a `set`


class _RestrictedUnpickler(pickle.Unpickler):
    """Admits torch/collections globals, two builtins, and the one yacs class."""

    def find_class(self, module: str, name: str):
        if module == "yacs.config" and name == "CfgNode":
            return _CfgNode
        if module in ("builtins", "__builtin__") and name in _SAFE_BUILTINS:
            return super().find_class("builtins", name)
        if module.startswith("torch") or module == "collections":
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"refusing to unpickle {module}.{name}: not a torch/collections "
            "global. The checkpoint contains something this converter was not "
            "written to trust."
        )


def _pickle_module() -> types.ModuleType:
    module = types.ModuleType("restricted_pickle")
    module.Unpickler = _RestrictedUnpickler
    module.load = lambda file, **kwargs: _RestrictedUnpickler(file, **kwargs).load()
    return module


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    source = Path(argv[1]) if len(argv) > 1 else config.MODELS_DIR / "spai.pth"
    target = config.MODELS_DIR / config.DETECTOR_FREQUENCY_FILENAME

    if not source.exists():
        print(f"upstream checkpoint not found: {source}")
        print(f"download it from {config.DETECTOR_FREQUENCY_SOURCE_URL}")
        return 1

    print(f"verifying {source} ...")
    upstream_sha = sha256_of(source)
    if upstream_sha != config.DETECTOR_FREQUENCY_UPSTREAM_SHA256:
        print("SHA-256 MISMATCH against the pinned upstream checkpoint:")
        print(f"  expected {config.DETECTOR_FREQUENCY_UPSTREAM_SHA256}")
        print(f"  got      {upstream_sha}")
        print("Refusing to convert an unrecognised file.")
        return 1
    print(f"  ok  {upstream_sha}")

    print("unpickling under the restricted unpickler ...")
    checkpoint = torch.load(
        source, map_location="cpu", weights_only=False, pickle_module=_pickle_module()
    )
    state_dict = checkpoint["model"]
    tensors = {key: value.detach().contiguous() for key, value in state_dict.items()}
    print(f"  {len(tensors)} tensors, {sum(t.numel() for t in tensors.values()):,} elements")

    metadata = {
        "source": "mever-team/spai spai.pth",
        "source_url": config.DETECTOR_FREQUENCY_SOURCE_URL,
        "source_sha256": upstream_sha,
        "upstream_commit": config.DETECTOR_FREQUENCY_UPSTREAM_COMMIT,
        "epoch": str(checkpoint.get("epoch")),
        "max_accuracy_upstream_val": str(checkpoint.get("max_accuracy")),
        "converted_by": "backend/scripts/convert_spai_checkpoint.py",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    save_file(tensors, str(target), metadata=metadata)

    digest = weights_digest(tensors)
    print(f"wrote {target}")
    print(f"  size            {target.stat().st_size:,} bytes")
    print(f"  weights digest  {digest}")
    if digest != config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST:
        print("NOTE: this differs from DETECTOR_FREQUENCY_WEIGHTS_DIGEST in app/shared/config.py.")
        print("      If this is the first conversion, pin the value above there.")
    else:
        print("  matches DETECTOR_FREQUENCY_WEIGHTS_DIGEST in app/shared/config.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
