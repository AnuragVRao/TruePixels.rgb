"""Build the quality gate's reference cache from the VALIDATION split. Read-only on images.

    cd backend
    python scripts/build_reference_set.py [--per-class 50]

Takes the first ``--per-class`` images of each class from
``ml/datasets/sbr_val`` (validation split, scenes 99-296 - never the
held-out test set ``synthbuster_raise``), runs EVERY pinned content detector
(config.SEMANTIC_BACKBONES) and SPAI once, and stores per image: label, each
detector's live score, and the exact inputs of each final head (captured with
forward pre-hooks).
Writes storage/models/reference/<file named by backbone revision + weights
digest>.npz (gitignored), plus a .json manifest listing the images.

The gate re-verifies that the published heads applied to these cached inputs
reproduce the cached scores before trusting the cache (app/m2_analysis/gate.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from app.m2_analysis import detectors, frequency_detector, gate  # noqa: E402
from app.shared import config  # noqa: E402

VAL = REPO / "ml" / "datasets" / "sbr_val"
SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-class", type=int, default=50)
    args = parser.parse_args()

    items = []
    for folder, label in (("0_real", 0), ("1_fake", 1)):
        files = sorted(p for p in (VAL / folder).rglob("*") if p.suffix.lower() in SUFFIXES)
        items += [(p, label) for p in files[: args.per_class]]
    if not items:
        raise SystemExit(f"no images under {VAL}")

    content = {checkpoint: detectors.semantic(checkpoint) for checkpoint in sorted(config.SEMANTIC_BACKBONES)}
    for detector in content.values():
        detector.load()
    frequency_detector.frequency.load()
    grabbed: dict[str, torch.Tensor] = {}

    def grab(key):
        return lambda _m, inputs: grabbed.__setitem__(key, inputs[0].detach().float().cpu())

    hooks = [detector.head_module().register_forward_pre_hook(grab(checkpoint))
             for checkpoint, detector in content.items()]
    hooks.append(frequency_detector.frequency._model.cls_head.register_forward_pre_hook(grab("frequency")))
    import hashlib

    def file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()

    names, labels, freq_f, freq_s, hashes = [], [], [], [], []
    sem_f = {c: [] for c in content}
    sem_s = {c: [] for c in content}
    try:
        for n, (path, label) in enumerate(items, 1):
            grabbed.clear()
            scores = {c: d.score(str(path)).score for c, d in content.items()}
            f = frequency_detector.frequency.score(str(path)).score
            names.append(str(path.relative_to(REPO)))
            hashes.append(file_sha256(path))
            labels.append(label)
            for c in content:
                sem_f[c].append(grabbed[c][0].numpy())
                sem_s[c].append(scores[c])
            freq_f.append(grabbed["frequency"][0].numpy())
            freq_s.append(f)
            shown = " ".join(f"{c.split('/')[-1]}={v:.4f}" for c, v in scores.items())
            print(f"  [{n}/{len(items)}] {label} {shown} freq={f:.4f} {path.name}")
    finally:
        for hook in hooks:
            hook.remove()

    # Content key (Phase 5a review): the gate refuses a cache whose key no
    # longer matches the current revision, weights, preprocessing or image list.
    images = [[n, h] for n, h in zip(names, hashes)]
    key = gate.reference_key(images)
    out = gate.reference_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"semantic_features__{gate.slug(c)}": np.stack(sem_f[c]) for c in content}
    arrays.update({f"semantic_scores__{gate.slug(c)}": np.array(sem_s[c], dtype=np.float64) for c in content})
    np.savez(out, cache_key=np.array(key), labels=np.array(labels, dtype=np.int64),
             frequency_features=np.stack(freq_f), frequency_scores=np.array(freq_s, dtype=np.float64),
             **arrays)
    out.with_suffix(".json").write_text(json.dumps(
        {"split": "sbr_val (validation, scenes 99-296)", "per_class": args.per_class,
         "cache_key": key, "images": images,
         "key_inputs": {k: v for k, v in gate.key_inputs(images).items() if k != "images"}},
        indent=2, default=str) + "\n")
    print(f"-> {out} ({len(names)} images)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
