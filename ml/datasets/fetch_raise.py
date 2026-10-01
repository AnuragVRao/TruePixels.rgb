"""Fetch the RAISE-1k photographs paired with the Synthbuster sample. EVALUATION DATA ONLY.

    python ml/datasets/fetch_raise.py [--out <dir>] [--workers 4]

RAISE-1k (Dang-Nguyen et al., 2015) is 1,000 uncompressed camera originals from
three Nikon DSLRs, distributed as RAW (NEF) and TIFF. Research use; cite the
paper. The TIFF variant is what SPAI's own published protocol uses
(``data/real_raise.csv`` lists ``RAISE-1k/tiff/<id>.tif``), so using it keeps
our numbers comparable to theirs.

Which images: exactly the scene ids that ``fetch_synthbuster.py`` selected, read
from its manifest. Synthbuster filenames ARE RAISE ids, so the two classes pair
scene for scene — every scene appears once as a photograph and once as a
generated image.

TWO PRACTICAL NOTES, both verified on 2026-09-30:

- The download host in ``RAISE_1k.csv`` (``193.205.194.113``) is effectively
  dead: an 8 MB range request timed out twice at over 180 s. The mirror at
  ``loki.disi.unitn.it`` serves the same paths at ~1 MB/s, so that is what this
  script uses. The CSV's own URLs are ignored.
- The CSV is read straight out of ``dataset/RAISE_1k.csv.zip``; nothing is
  unpacked to disk.

Each file is checked against the server's ``Content-Length`` and opened with
PIL before being counted. Existing files are skipped, so an interrupted run
resumes where it stopped.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import csv
import io
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_ZIP = REPO_ROOT / "dataset" / "RAISE_1k.csv.zip"
# NOT the IP host named in the CSV - see the module docstring.
TIFF_URL = "https://loki.disi.unitn.it/RAISE/TIFF/{image_id}.TIF"
ATTEMPTS = 3

Image.MAX_IMAGE_PIXELS = None  # these are 12 MP camera originals, not decompression bombs


def read_raise_ids() -> set[str]:
    """Every `File` id in RAISE_1k.csv, read from inside the zip."""
    if not CSV_ZIP.is_file():
        raise SystemExit(f"{CSV_ZIP} not found")
    with zipfile.ZipFile(CSV_ZIP) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
        text = archive.read(name).decode("utf-8", "replace")
    return {row["File"].strip() for row in csv.DictReader(io.StringIO(text))}


def read_wanted_ids(manifest: Path) -> list[str]:
    with manifest.open(encoding="utf-8") as handle:
        return [row["image_id"] for row in csv.DictReader(handle)]


def download(image_id: str, target: Path) -> tuple[str, int, str]:
    """Fetch one TIFF, verifying length and decodability. Returns (id, bytes, size)."""
    if target.exists() and target.stat().st_size > 0:
        try:
            with Image.open(target) as image:
                return image_id, target.stat().st_size, f"{image.width}x{image.height}"
        except Exception:  # noqa: BLE001 - a truncated resume; re-fetch it
            target.unlink(missing_ok=True)

    url = TIFF_URL.format(image_id=image_id)
    last: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=300) as response:
                declared = response.headers.get("Content-Length")
                payload = response.read()
            if declared is not None and len(payload) != int(declared):
                raise OSError(f"short read: {len(payload)} of {declared} bytes")
            temporary = target.with_suffix(".part")
            temporary.write_bytes(payload)
            with Image.open(temporary) as image:
                size = f"{image.width}x{image.height}"
            temporary.replace(target)
            return image_id, len(payload), size
        except Exception as exc:  # noqa: BLE001
            last = exc
            target.with_suffix(".part").unlink(missing_ok=True)
            if attempt < ATTEMPTS:
                time.sleep(2 * attempt)
    raise SystemExit(f"{image_id}: failed after {ATTEMPTS} attempts - {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "ml" / "datasets" / "synthbuster_raise")
    parser.add_argument("--workers", type=int, default=4,
                        help="parallel connections; kept low - this is an academic server")
    args = parser.parse_args()

    manifest = args.out / "manifest_fake.csv"
    if not manifest.is_file():
        raise SystemExit(f"{manifest} not found - run fetch_synthbuster.py first")

    wanted = read_wanted_ids(manifest)
    known = read_raise_ids()
    missing = [i for i in wanted if i not in known]
    if missing:
        raise SystemExit(f"{len(missing)} selected ids are not in RAISE_1k.csv: {missing[:5]}")
    print(f"{len(wanted)} scene ids, all present in RAISE_1k.csv")

    real_root = args.out / "0_real"
    real_root.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    rows: list[dict] = []
    with futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(download, i, real_root / f"{i}.tif"): i for i in wanted}
        for done, future in enumerate(futures.as_completed(pending), 1):
            image_id, size_bytes, dimensions = future.result()
            rows.append({"image_id": image_id, "bytes": size_bytes, "size": dimensions})
            if done % 10 == 0 or done == len(wanted):
                elapsed = time.perf_counter() - started
                total = sum(r["bytes"] for r in rows) / 2**20
                print(f"  {done}/{len(wanted)}  {total:.0f} MB  "
                      f"{total / elapsed:.2f} MB/s  eta {(len(wanted) - done) * elapsed / done / 60:.1f} min",
                      flush=True)

    rows.sort(key=lambda r: r["image_id"])
    out_manifest = args.out / "manifest_real.csv"
    with out_manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["image_id", "bytes", "size"])
        writer.writeheader()
        writer.writerows(rows)

    import collections
    print(f"\n{len(rows)} TIFFs, {sum(r['bytes'] for r in rows) / 2**30:.2f} GB")
    print("dimensions:", dict(collections.Counter(r["size"] for r in rows)))
    print(f"manifest: {out_manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
