"""Build the control and degradation arms of the Synthbuster/RAISE evaluation.

    python ml/datasets/make_variants.py [--degrade] [--root <dir>]

The primary set pits 4288x2848 camera TIFFs against 1024x1024 generated PNGs.
That is the published Synthbuster/RAISE protocol - SPAI's own evaluation uses
it - but the two classes differ in resolution as well as in origin, and a
detector could in principle separate them on the former. These arms say how
much of the headline number survives when that difference is removed.

CONTROL ARMS (reals only; the generated class is already 1024x1024 and is
shared unchanged, by hard link where the filesystem allows it):

    crop1024    centre crop to 1024x1024. Equalises resolution AND SPAI's
                patch count (16 patches both sides), and keeps native pixel
                statistics intact. Caveat, stated in advance: it keeps only
                ~8.6% of each photograph, so some loss is expected from having
                less evidence per image, quite apart from any confound.
    resize1024  LANCZOS downscale of the longest side to 1024. Keeps the whole
                scene but low-passes it, which is exactly what Contract C1
                section 4.3 says destroys the frequency branch's evidence.
                The contrast with crop1024 separates "less evidence" from
                "resolution was doing the work".

DEGRADATION ARMS (--degrade; applied to BOTH classes, since a real deployment
degrades everything it receives):

    jpeg90, jpeg75    re-encoded at those qualities
    half              both dimensions halved (LANCZOS), but never below
                      MIN_SIDE - see below

THE 224-PIXEL FLOOR. SPAI tiles its input into 224x224 patches and cannot
accept an image smaller than that in either dimension: ``Tensor.unfold``
raises. Glide's Synthbuster images are 256x256, so halving them would produce
128x128 and crash the branch - which is exactly what happened on the first
attempt. ``half`` therefore floors every output at 224 on the short side.
Images that hit the floor are downscaled by less than 2x and are listed in the
output, because that makes the arm non-uniform and the reader needs to know.

(The underlying fragility is a real one and is NOT this script's to fix: the
production path returns HTTP 500 for any upload with a side under 224 px.
Recorded in CLAUDE.md.)

These measure limitation 5 in CLAUDE.md - "heavy recompression or
social-media resizing degrades detectors of this kind; unmeasured here" - and
turn it into a number.

Control arms are written as lossless PNG so the control itself introduces no
compression artefact. Nothing here is fitted or tuned; these are fixed,
declared transformations.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
MIN_SIDE = 224  # SPAI's patch size; below this the branch raises
Image.MAX_IMAGE_PIXELS = None  # 12 MP camera originals, not decompression bombs


def link_or_copy(source: Path, target: Path) -> None:
    """Hard-link when the filesystem allows it, copy otherwise.

    The generated class is byte-identical across every arm, so linking avoids
    storing the same 130 MB five times over.
    """
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except (OSError, NotImplementedError):
        shutil.copy2(source, target)


def centre_crop(image: Image.Image, size: int) -> Image.Image:
    width, height = image.size
    if width < size or height < size:
        raise SystemExit(f"image is {width}x{height}, smaller than the {size} crop")
    left, top = (width - size) // 2, (height - size) // 2
    return image.crop((left, top, left + size, top + size))


def resize_longest(image: Image.Image, longest: int) -> Image.Image:
    scale = longest / max(image.size)
    if scale >= 1.0:
        return image.copy()
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                        Image.Resampling.LANCZOS)


def build_arm(root: Path, name: str, transform, suffix: str = ".png",
              save_kwargs: dict | None = None, both_classes: bool = False) -> Path:
    """Write one arm; returns its root. Existing files are left alone."""
    out = root.parent / f"{root.name}__{name}"
    save_kwargs = save_kwargs or {}
    written = 0

    for source in sorted((root / "0_real").rglob("*")):
        if source.is_dir() or source.suffix.lower() not in {".tif", ".tiff", ".png", ".jpg"}:
            continue
        target = out / "0_real" / (source.stem + suffix)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(source) as image:
                transform(image.convert("RGB")).save(target, **save_kwargs)
            written += 1

    for source in sorted((root / "1_fake").rglob("*")):
        if source.is_dir() or source.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        relative = source.relative_to(root / "1_fake")
        if both_classes:
            target = out / "1_fake" / relative.with_suffix(suffix)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(source) as image:
                    transform(image.convert("RGB")).save(target, **save_kwargs)
                written += 1
        else:
            link_or_copy(source, out / "1_fake" / relative)

    reals = sum(1 for _ in (out / "0_real").rglob("*") if _.is_file())
    fakes = sum(1 for _ in (out / "1_fake").rglob("*") if _.is_file())
    print(f"  {name:10} -> {out.name}  ({reals} real / {fakes} generated, {written} newly written)")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path,
                        default=REPO_ROOT / "ml" / "datasets" / "synthbuster_raise")
    parser.add_argument("--degrade", action="store_true",
                        help="also build the JPEG and half-size arms, on both classes")
    args = parser.parse_args()

    if not (args.root / "0_real").is_dir() or not (args.root / "1_fake").is_dir():
        raise SystemExit(f"{args.root} must contain 0_real/ and 1_fake/")

    print("control arms (reals transformed; generated class shared unchanged):")
    build_arm(args.root, "crop1024", lambda im: centre_crop(im, 1024))
    build_arm(args.root, "resize1024", lambda im: resize_longest(im, 1024))

    if args.degrade:
        print("\ndegradation arms (both classes):")
        for quality in (90, 75):
            build_arm(args.root, f"jpeg{quality}", lambda im: im, suffix=".jpg",
                      save_kwargs={"quality": quality, "subsampling": 0}, both_classes=True)
        floored: list[str] = []

        def halve(image: Image.Image) -> Image.Image:
            """Halve, but never below SPAI's 224 px patch size."""
            scale = max(0.5, MIN_SIDE / min(image.size))
            if scale > 0.5:
                floored.append(f"{image.width}x{image.height}")
            return image.resize((max(MIN_SIDE, round(image.width * scale)),
                                 max(MIN_SIDE, round(image.height * scale))),
                                Image.Resampling.LANCZOS)

        build_arm(args.root, "half", halve, both_classes=True)
        if floored:
            import collections
            print(f"    NOTE: {len(floored)} image(s) hit the {MIN_SIDE}px floor and were "
                  f"downscaled by less than 2x: {dict(collections.Counter(floored))}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
