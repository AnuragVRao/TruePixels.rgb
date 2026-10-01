"""Fetch a sample of the Synthbuster generated-image set. EVALUATION DATA ONLY.

    python ml/datasets/fetch_synthbuster.py [--per-model 11] [--out <dir>]

Synthbuster (Bammey, 2023) is 9,000 images — 1,000 from each of nine diffusion
generators — produced from prompts describing the RAISE-1k photographs, so its
filenames ARE RAISE image ids and the two sets pair scene for scene.
Zenodo record 10066460, **CC-BY-NC-SA-4.0: non-commercial**.

WHY THIS EXISTS RATHER THAN `dataset/1.py`. That script is correct — its
``parts[1]`` really is the generator name, because archive members are
``synthbuster/<generator>/<id>.png``. But it needs the 12.4 GB archive on disk
to take ~1.3 GB of images out of it. Zenodo honours HTTP range requests, so
this script reads the zip's central directory remotely and pulls only the
members it wants, decompressing them itself. The selection rule and the output
bytes are the same; only the transfer is smaller.

SAMPLING. Every generator was given the same 1,000 scenes, so taking the first
N names of each would cover only N distinct scenes, N times over. Instead each
generator gets a DISJOINT slice of the shared sorted id list — generator i
takes ids [offset + N*i : offset + N*i + N] — so the output spans ``9 * N``
distinct scenes and can be paired one-to-one with the same number of RAISE
reals. Every scene then appears exactly once as real and once as generated.

``--offset`` slides that whole window, which is how a VALIDATION set disjoint
from the test set is built: the test set is ``--per-model 11`` at offset 0
(scenes 0-98), so ``--per-model 22 --offset 99`` takes scenes 99-296 and
shares not one image with it. Choosing a threshold on one and reporting on
the other is the difference between an operating point and a number fitted to
its own test set.

Integrity: every member's CRC-32 is checked against the central directory, and
every extracted file is opened with PIL. Dimensions are recorded per generator
and printed, because they are NOT assumed to be uniform - a generator that
emits 256x256 puts its images into SPAI's five-crop fallback rather than its
sliding-window regime, which changes how the detector sees them.
"""

from __future__ import annotations

import argparse
import collections
import csv
import struct
import sys
import time
import urllib.request
import zlib
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]

ZENODO_URL = "https://zenodo.org/records/10066460/files/synthbuster.zip?download=1"
ARCHIVE_BYTES = 12372557226  # verified 2026-09-30
EXPECTED_GENERATORS = 9
EXPECTED_PER_GENERATOR = 1000
ATTEMPTS = 4  # per range request; the run makes one per image over ~20 minutes

_EOCD64_LOCATOR = b"PK\x06\x07"
_EOCD64 = b"PK\x06\x06"
_CENTRAL = b"PK\x01\x02"
_LOCAL = b"PK\x03\x04"


def fetch_range(start: int, end: int) -> bytes:
    """Inclusive byte range from the remote archive, with retries.

    A run makes one request per image plus two for the directory, over tens of
    minutes, so a transient reset is not an exceptional case - it is the
    expected case eventually. Without this, one ``ConnectionResetError`` threw
    away a 95-image download (observed 2026-09-30).
    """
    last: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            request = urllib.request.Request(
                ZENODO_URL, headers={"Range": f"bytes={start}-{end}"}
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                if response.status != 206:
                    raise SystemExit(
                        f"server ignored the Range header (HTTP {response.status}); "
                        "selective download is not possible against this mirror"
                    )
                payload = response.read()
            expected = end - start + 1
            if len(payload) != expected:
                raise OSError(f"short read: {len(payload)} of {expected} bytes")
            return payload
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport failure is retryable
            last = exc
            if attempt < ATTEMPTS:
                time.sleep(2 ** attempt)
    raise SystemExit(f"range {start}-{end} failed after {ATTEMPTS} attempts: {last}")


class Entry:
    """One archive member, as described by the central directory."""

    __slots__ = ("name", "method", "crc", "compressed_size", "header_offset")

    def __init__(self, name: str, method: int, crc: int, compressed_size: int,
                 header_offset: int) -> None:
        self.name = name
        self.method = method
        self.crc = crc
        self.compressed_size = compressed_size
        self.header_offset = header_offset

    @property
    def generator(self) -> str:
        return self.name.split("/")[1]

    @property
    def image_id(self) -> str:
        return Path(self.name).stem


def _zip64_extra(blob: bytes, wanted: list[str], values: dict[str, int]) -> None:
    """Pull 0xFFFFFFFF-sentinelled fields out of the zip64 extra field, in order."""
    position = 0
    while position + 4 <= len(blob):
        tag, size = struct.unpack("<HH", blob[position:position + 4])
        if tag == 0x0001:
            payload = blob[position + 4:position + 4 + size]
            offset = 0
            for field in wanted:
                if values[field] == 0xFFFFFFFF and offset + 8 <= len(payload):
                    values[field] = struct.unpack("<Q", payload[offset:offset + 8])[0]
                    offset += 8
            return
        position += 4 + size


def read_central_directory() -> list[Entry]:
    """Locate and parse the archive's central directory over HTTP."""
    tail = fetch_range(ARCHIVE_BYTES - 70_000, ARCHIVE_BYTES - 1)

    locator = tail.rfind(_EOCD64_LOCATOR)
    if locator < 0:
        raise SystemExit("no ZIP64 end-of-central-directory locator found")
    eocd64_offset = struct.unpack("<Q", tail[locator + 8:locator + 16])[0]

    record = fetch_range(eocd64_offset, eocd64_offset + 55)
    if record[:4] != _EOCD64:
        raise SystemExit("ZIP64 end-of-central-directory record not where the locator says")
    directory_size = struct.unpack("<Q", record[40:48])[0]
    directory_offset = struct.unpack("<Q", record[48:56])[0]

    print(f"central directory: {directory_size / 2**20:.1f} MB at offset {directory_offset}")
    blob = fetch_range(directory_offset, directory_offset + directory_size - 1)

    entries: list[Entry] = []
    position = 0
    while position + 46 <= len(blob) and blob[position:position + 4] == _CENTRAL:
        method = struct.unpack("<H", blob[position + 10:position + 12])[0]
        crc = struct.unpack("<I", blob[position + 16:position + 20])[0]
        values = {
            "compressed": struct.unpack("<I", blob[position + 20:position + 24])[0],
            "uncompressed": struct.unpack("<I", blob[position + 24:position + 28])[0],
            "header_offset": struct.unpack("<I", blob[position + 42:position + 46])[0],
        }
        name_len, extra_len, comment_len = struct.unpack("<HHH", blob[position + 28:position + 34])
        name = blob[position + 46:position + 46 + name_len].decode("utf-8", "replace")
        extra = blob[position + 46 + name_len:position + 46 + name_len + extra_len]
        _zip64_extra(extra, ["uncompressed", "compressed", "header_offset"], values)

        if name.lower().endswith(".png"):
            entries.append(Entry(name, method, crc, values["compressed"], values["header_offset"]))
        position += 46 + name_len + extra_len + comment_len

    return entries


def extract(entry: Entry) -> bytes:
    """Range-fetch one member and return its decompressed bytes, CRC verified."""
    header = fetch_range(entry.header_offset, entry.header_offset + 29)
    if header[:4] != _LOCAL:
        raise SystemExit(f"{entry.name}: local header signature missing")
    name_len, extra_len = struct.unpack("<HH", header[26:30])
    start = entry.header_offset + 30 + name_len + extra_len
    payload = fetch_range(start, start + entry.compressed_size - 1)

    if entry.method == 0:
        data = payload
    elif entry.method == 8:
        data = zlib.decompressobj(-zlib.MAX_WBITS).decompress(payload)
    else:
        raise SystemExit(f"{entry.name}: unsupported compression method {entry.method}")

    if zlib.crc32(data) & 0xFFFFFFFF != entry.crc:
        raise SystemExit(f"{entry.name}: CRC-32 mismatch - refusing a corrupt image")
    return data


def select(entries: list[Entry], per_model: int, offset: int = 0) -> list[Entry]:
    """Disjoint slice per generator, so scenes are not repeated across generators."""
    by_generator: dict[str, list[Entry]] = collections.defaultdict(list)
    for entry in entries:
        by_generator[entry.generator].append(entry)

    generators = sorted(by_generator)
    print(f"generators: {len(generators)}")
    for name in generators:
        print(f"  {name}: {len(by_generator[name])} images")

    if len(generators) != EXPECTED_GENERATORS:
        raise SystemExit(f"expected {EXPECTED_GENERATORS} generators, found {len(generators)}")
    for name in generators:
        if len(by_generator[name]) != EXPECTED_PER_GENERATOR:
            raise SystemExit(f"{name}: expected {EXPECTED_PER_GENERATOR} images")

    id_sets = {name: {e.image_id for e in items} for name, items in by_generator.items()}
    shared = set.intersection(*id_sets.values())
    if len(shared) != EXPECTED_PER_GENERATOR:
        raise SystemExit(
            "generators do not share an identical scene id set "
            f"(intersection {len(shared)}); disjoint slicing assumes they do"
        )
    print(f"all {len(generators)} generators share the same {len(shared)} scene ids")

    if offset + per_model * len(generators) > len(shared):
        raise SystemExit(
            f"--per-model {per_model} at --offset {offset} needs "
            f"{offset + per_model * len(generators)} ids; only {len(shared)} exist"
        )

    ordered_ids = sorted(shared)
    chosen: list[Entry] = []
    for index, name in enumerate(generators):
        start = offset + index * per_model
        wanted = set(ordered_ids[start:start + per_model])
        chosen.extend(sorted((e for e in by_generator[name] if e.image_id in wanted),
                             key=lambda e: e.image_id))
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-model", type=int, default=11)
    parser.add_argument("--offset", type=int, default=0, help=(
        "skip this many scene ids before slicing - use it to build a validation "
        "set that shares no scene with the test set"))
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "ml" / "datasets" / "synthbuster_raise")
    args = parser.parse_args()

    entries = read_central_directory()
    print(f"{len(entries)} image entries in the archive")
    chosen = select(entries, args.per_model, args.offset)
    print(f"\nselected {len(chosen)} images "
          f"({args.per_model} per generator, disjoint scenes, offset {args.offset})\n")

    fake_root = args.out / "1_fake"
    rows = []
    for index, entry in enumerate(chosen, 1):
        target = fake_root / entry.generator / f"{entry.image_id}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        # `exists()` alone is not a safe resume guard: write_bytes is not
        # atomic, so a run killed mid-write leaves a truncated file that
        # exists, opens (PIL reads only the header) and would be recorded in
        # the manifest under a CRC it never matched. Verify what is on disk,
        # and write through a .part file so a future interruption cannot
        # leave a half-image in place.
        if target.exists() and zlib.crc32(target.read_bytes()) & 0xFFFFFFFF == entry.crc:
            pass
        else:
            partial = target.with_suffix(".part")
            partial.write_bytes(extract(entry))
            partial.replace(target)
        with Image.open(target) as image:
            width, height, mode = image.width, image.height, image.mode
        rows.append({"generator": entry.generator, "image_id": entry.image_id,
                     "crc32": f"{entry.crc:08x}", "bytes": target.stat().st_size,
                     "width": width, "height": height, "mode": mode})
        if index % 10 == 0 or index == len(chosen):
            print(f"  {index}/{len(chosen)}", flush=True)

    manifest = args.out / "manifest_fake.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print("\nper-generator image size (NOT assumed uniform - it changes SPAI's patch regime):")
    sizes_by_generator = collections.defaultdict(collections.Counter)
    for row in rows:
        sizes_by_generator[row["generator"]][f"{row['width']}x{row['height']} {row['mode']}"] += 1
    majority = collections.Counter(f"{r['width']}x{r['height']}" for r in rows).most_common(1)[0][0]
    for name in sorted(sizes_by_generator):
        detail = dict(sizes_by_generator[name])
        flag = "" if all(k.startswith(majority) for k in detail) else "   <-- DIFFERS"
        print(f"  {name:22} {detail}{flag}")
    print(f"  majority size: {majority}")

    print(f"\n{len(rows)} images under {fake_root}")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
