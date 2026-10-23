"""Download and sample the benchmark datasets into eval/data/ (gitignored).

    python -m benchmark.fetch                 # everything that's public
    python -m benchmark.fetch --only cadb duts
    python -m benchmark.fetch --hlw-archive ~/Downloads/hlw_1_0.zip

Reproducibility contract: the first fetch draws each sample with a fixed seed
and writes eval/benchmark/manifests/<dataset>.json — the sampled IDs plus the
SHA-256 of every extracted image and label file. That manifest is committed.
Every later fetch, on any machine, reuses the manifest's IDs instead of
resampling and fails loudly if any file's hash differs. So the numbers in
eval/results/ are tied to exactly these images, and drift upstream is detected
rather than absorbed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import random
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from benchmark import sources
from benchmark.remote_zip import open_remote_zip

EVAL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = EVAL_DIR / "data"
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"


class FetchError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "framegrader-benchmark/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def _sample(ids: list[str], n: int, salt: str) -> list[str]:
    # Seeded per dataset+split, over a sorted list: independent of archive
    # order and of which other datasets were fetched in the same run.
    rng = random.Random(f"{sources.SEED}:{salt}")
    pool = sorted(ids)
    return sorted(rng.sample(pool, min(n, len(pool))))


class Manifest:
    """Read-or-create the committed manifest for one dataset."""

    def __init__(self, dataset: str) -> None:
        self.path = MANIFEST_DIR / f"{dataset}.json"
        self.existing: dict[str, Any] | None = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None
        )
        self.data: dict[str, Any] = {
            "dataset": dataset,
            "seed": sources.SEED,
            "splits": {},
            "files": {},
        }

    def ids(self, split: str, candidates: list[str], n: int) -> list[str]:
        if self.existing and split in self.existing.get("splits", {}):
            ids = self.existing["splits"][split]
            missing = set(ids) - set(candidates)
            if missing:
                raise FetchError(f"{self.path.name}: {len(missing)} manifest IDs absent upstream")
            return ids
        return _sample(candidates, n, f"{self.data['dataset']}:{split}")

    def record(self, rel_path: str, data: bytes) -> None:
        digest = sha256(data)
        expected = (self.existing or {}).get("files", {}).get(rel_path)
        if expected and expected != digest:
            raise FetchError(
                f"{self.data['dataset']}: {rel_path} has sha256 {digest[:12]}…, "
                f"manifest says {expected[:12]}… — upstream changed"
            )
        self.data["files"][rel_path] = digest

    def save(self, **extra: Any) -> None:
        self.data.update(extra)
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _write(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _extract(zf: zipfile.ZipFile, member: str, dest_root: Path, rel: str, manifest: Manifest) -> None:
    dest = dest_root / rel
    if dest.exists():
        data = dest.read_bytes()
    else:
        data = zf.read(member)  # raises BadZipFile on a CRC mismatch
        _write(dest, data)
    manifest.record(rel, data)


# Remote members are independent ranged GETs dominated by round-trip latency
# (Dropbox adds a redirect to each), so fetch several at once.
_FETCH_THREADS = 8


def _extract_many(
    zf: zipfile.ZipFile,
    jobs: list[tuple[str, str]],
    dest_root: Path,
    manifest: Manifest,
    label: str,
    threads: int = _FETCH_THREADS,
) -> None:
    def one(job: tuple[str, str]) -> None:
        _extract(zf, job[0], dest_root, job[1], manifest)

    with ThreadPoolExecutor(threads) as pool:
        for i, _ in enumerate(pool.map(one, jobs), 1):
            if i % 100 == 0:
                print(f"  {label}: {i}/{len(jobs)}", flush=True)


# ---------------------------------------------------------------------------


def fetch_duts() -> None:
    cfg, root = sources.DUTS, DATA_DIR / "duts"
    archive = root / "DUTS-TE.zip"
    if not archive.exists() or sha256(archive.read_bytes()) != cfg["archive_sha256"]:
        print("  downloading DUTS-TE.zip (140 MB)…")
        data = _download(cfg["archive_url"])
        if sha256(data) != cfg["archive_sha256"]:
            raise FetchError("DUTS-TE.zip sha256 mismatch")
        _write(archive, data)
    zf = zipfile.ZipFile(archive)
    names = {Path(n).stem for n in zf.namelist() if n.startswith(cfg["image_dir"]) and n.endswith(".jpg")}
    manifest = Manifest("duts")
    sample = sources.SAMPLES["duts"]["test"]
    ids = manifest.ids("test", list(names), sample.n)
    for stem in ids:
        _extract(zf, f"{cfg['image_dir']}{stem}.jpg", root, f"images/{stem}.jpg", manifest)
        _extract(zf, f"{cfg['mask_dir']}{stem}.png", root, f"masks/{stem}.png", manifest)
    manifest.data["splits"]["test"] = ids
    manifest.save(source=cfg["archive_url"], archive_sha256=cfg["archive_sha256"], license=cfg["license"])
    print(f"  duts: {len(ids)} images")


def fetch_cadb() -> None:
    cfg, root = sources.CADB, DATA_DIR / "cadb"
    zf, remote = open_remote_zip(cfg["archive_url"])
    manifest = Manifest("cadb")
    labels: dict[str, Any] = {}
    for local, member in cfg["labels"].items():
        data = zf.read(member)
        _write(root / "labels" / local, data)
        manifest.record(f"labels/{local}", data)
        labels[local] = json.loads(data)

    split = labels["split.json"]
    for name, sample in sources.SAMPLES["cadb"].items():
        ids = manifest.ids(name, list(split[sample.split]), sample.n)
        _extract_many(
            zf, [(f"{cfg['image_dir']}{i}", f"images/{i}") for i in ids], root, manifest, f"cadb {name}",
            # Dropbox starts ignoring Range (answering 200 with the whole
            # archive) when pushed harder than this.
            threads=4,
        )
        manifest.data["splits"][name] = ids
    manifest.save(source=cfg["archive_url"], license=cfg["license"])
    print(f"  cadb: done, {remote.bytes_fetched / 1e6:.0f} MB transferred of a 2.1 GB archive")


def fetch_koniq() -> None:
    cfg, root = sources.KONIQ, DATA_DIR / "koniq"
    manifest = Manifest("koniq")
    rev = (manifest.existing or {}).get("labels_rev")
    if not rev:
        with urllib.request.urlopen(cfg["labels_rev_api"], timeout=60) as resp:
            rev = json.load(resp)["sha"]
    labels_bytes = _download(cfg["labels_url"].format(rev=rev))
    _write(root / "labels.csv", labels_bytes)
    manifest.record("labels.csv", labels_bytes)
    rows = list(csv.DictReader(io.StringIO(labels_bytes.decode("utf-8"))))
    test_names = [r["img_name"] for r in rows if r["official_split"] == "test"]

    zf, remote = open_remote_zip(cfg["archive_url"])
    sample = sources.SAMPLES["koniq"]["test"]
    ids = manifest.ids("test", test_names, sample.n)
    _extract_many(zf, [(f"{cfg['image_dir']}{n}", f"images/{n}") for n in ids], root, manifest, "koniq")
    manifest.data["splits"]["test"] = ids
    manifest.save(source=cfg["archive_url"], labels_rev=rev, license=cfg["license"])
    print(f"  koniq: {len(ids)} images, {remote.bytes_fetched / 1e6:.0f} MB transferred")


def _open_hlw(archive: str) -> zipfile.ZipFile:
    if archive.startswith(("http://", "https://")):
        return open_remote_zip(archive)[0]
    return zipfile.ZipFile(archive)


def fetch_hlw(archive: str | None) -> bool:
    archive = archive or os.environ.get(sources.HLW["archive_env"])
    if not archive:
        print(
            "  hlw: SKIPPED — HLW is distributed on request only (no public URL).\n"
            "       Request it from the authors, then pass --hlw-archive PATH_OR_URL\n"
            "       (or set HLW_ARCHIVE). See eval/benchmark/sources.py."
        )
        return False
    root = DATA_DIR / "hlw"
    zf = _open_hlw(archive)
    names = zf.namelist()

    def member(suffix: str) -> str:
        hits = [n for n in names if n.endswith(suffix)]
        if not hits:
            raise FetchError(f"HLW archive has no {suffix}")
        return min(hits, key=len)  # shortest path: the top-level copy

    manifest = Manifest("hlw")
    meta = zf.read(member("metadata.csv"))
    _write(root / "metadata.csv", meta)
    manifest.record("metadata.csv", meta)
    test_list = zf.read(member("split/test.txt")).decode().split()
    image_prefix = member("metadata.csv")[: -len("metadata.csv")] + "images/"

    sample = sources.SAMPLES["hlw"]["test"]
    ids = manifest.ids("test", test_list, sample.n)
    for name in ids:
        _extract(zf, image_prefix + name, root, f"images/{name}", manifest)
    manifest.data["splits"]["test"] = ids
    manifest.save(source="user-supplied HLW 1.0 archive", license=sources.HLW["license"])
    print(f"  hlw: {len(ids)} images")
    return True


FETCHERS = {"duts": fetch_duts, "cadb": fetch_cadb, "koniq": fetch_koniq}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", choices=[*FETCHERS, "hlw"])
    parser.add_argument("--hlw-archive", help="path or URL of the HLW 1.0 zip")
    args = parser.parse_args(argv)
    wanted = args.only or [*FETCHERS, "hlw"]
    for name in wanted:
        print(f"[{name}]")
        if name == "hlw":
            fetch_hlw(args.hlw_archive)
        else:
            FETCHERS[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
