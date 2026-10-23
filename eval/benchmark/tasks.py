"""The four benchmark tasks. Each returns a JSON-able result dict.

Every task scores the production code path — the same functions the API
calls — never a reimplementation. Per-image outputs are cached under
eval/data/<dataset>/cache/ keyed by task, so re-running a report or refitting
the calibration doesn't recompute a 20-minute feature pass.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from benchmark import metrics  # noqa: E402
from benchmark.fetch import DATA_DIR, MANIFEST_DIR  # noqa: E402


def _manifest(dataset: str) -> dict[str, Any]:
    path = MANIFEST_DIR / f"{dataset}.json"
    if not path.exists():
        raise FileNotFoundError(f"No manifest for {dataset}; run `python -m benchmark.fetch` first")
    return json.loads(path.read_text(encoding="utf-8"))


def load_rgb(path: Path, max_edge: int = 1920) -> np.ndarray:
    """Decode like production: EXIF-transposed RGB, capped at 1920px."""
    from PIL import ImageOps

    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return np.asarray(image)


def _cached_map(
    dataset: str, key: str, ids: list[str], fn: Callable[[str], Any], workers: int
) -> dict[str, Any]:
    """Run fn(id) for every id not yet in the cache file; return id -> result."""
    cache_path = DATA_DIR / dataset / "cache" / f"{key}.jsonl"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    done: dict[str, Any] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done[row["id"]] = row["result"]
    todo = [i for i in ids if i not in done]
    if todo:
        print(f"  {dataset}/{key}: {len(todo)} to compute ({len(done)} cached), {workers} workers")
        start = time.perf_counter()
        with cache_path.open("a") as out:
            results: Iterable[tuple[str, Any]]
            if workers > 1:
                pool = ProcessPoolExecutor(max_workers=workers, initializer=_worker_init)
                results = zip(todo, pool.map(fn, todo, chunksize=4))
            else:
                _worker_init()
                results = ((i, fn(i)) for i in todo)
            for n, (i, result) in enumerate(results, 1):
                done[i] = result
                out.write(json.dumps({"id": i, "result": result}) + "\n")
                if n % 50 == 0:
                    rate = n / (time.perf_counter() - start)
                    print(f"    {n}/{len(todo)}  ({rate:.1f} img/s)")
            if workers > 1:
                pool.shutdown()
    return {i: done[i] for i in ids}


def _worker_init() -> None:
    # Each process gets a slice of the CPU rather than every process trying to
    # use all cores at once, which thrashes on a laptop.
    import cv2

    # YOLO-World is loaded by bare filename, i.e. relative to the CWD; run
    # where the backend keeps its weights instead of downloading a copy here.
    os.chdir(REPO / "backend")
    threads =str(max(1, (os.cpu_count() or 4) // max(1, int(os.environ.get("BENCH_WORKERS", "1")))))
    os.environ.setdefault("OMP_NUM_THREADS", threads)
    cv2.setNumThreads(int(threads))
    try:
        import torch

        torch.set_num_threads(int(threads))
    except ImportError:
        pass
    if os.environ.get("BENCH_WITH_VLM") != "1":
        # The VLM tier is a paid Claude call per image. Off unless asked for.
        os.environ.pop("ANTHROPIC_API_KEY", None)


# ---------------------------------------------------------------------------
# Horizon (HLW)
# ---------------------------------------------------------------------------

# A detection is correct when the predicted line is within this fraction of the
# image height of the ground truth at both image edges — HLW's own "horizon
# error" metric, thresholded.
HORIZON_TOLERANCE = 0.05


def _hlw_gt(row: dict[str, str], width: int, height: int, coords: str) -> tuple[float, float]:
    """Ground-truth line as (y at left edge, y at right edge) in top-left pixel
    coordinates, y down."""
    x1, y1, x2, y2 = (float(row[k]) for k in ("left_x", "left_y", "right_x", "right_y"))
    if coords.startswith("center"):
        x1, x2 = x1 + width / 2, x2 + width / 2
        if coords == "center-up":
            y1, y2 = height / 2 - y1, height / 2 - y2
        else:
            y1, y2 = y1 + height / 2, y2 + height / 2
    slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0.0
    return y1 - slope * x1, y1 + slope * (width - x1)


def _horizon_one(path: str) -> dict[str, Any]:
    from app.services.composition.horizon_detection import detect_horizon

    rgb = load_rgb(Path(path))
    h, w = rgb.shape[:2]
    start = time.perf_counter()
    result = detect_horizon(rgb)
    return {**result, "w": w, "h": h, "ms": (time.perf_counter() - start) * 1000}


def run_horizon(workers: int, coords: str = "center-up") -> dict[str, Any]:
    manifest = _manifest("hlw")
    ids = manifest["splits"]["test"]
    root = DATA_DIR / "hlw"
    meta = {}
    with (root / "metadata.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 5 and row[0] != "image":
                meta[row[0]] = dict(zip(("left_x", "left_y", "right_x", "right_y"), row[1:5]))

    preds = _cached_map("hlw", "horizon", [str(root / "images" / i) for i in ids], _horizon_one, workers)
    tp = fp = fn = tn = 0
    errors, tilt_errors, tilt_errors_all = [], [], []
    for i in ids:
        p = preds[str(root / "images" / i)]
        w, h = p["w"], p["h"]
        gl, gr = _hlw_gt(meta[i], w, h, coords)
        positive = min(gl, gr) <= h and max(gl, gr) >= 0  # line crosses the frame
        gt_tilt = math.degrees(math.atan2(gr - gl, w))
        if p["horizon_detected"]:
            tilt = p["tilt_angle"] if p["tilt_reliable"] else 0.0
            centre = p["horizon_y"] * (h - 1)
            dy = math.tan(math.radians(tilt)) * w / 2
            pl, pr = centre - dy, centre + dy
            err = max(abs(pl - gl), abs(pr - gr)) / h
            errors.append(err)
            if positive and err <= HORIZON_TOLERANCE:
                tp += 1
                tilt_errors_all.append(abs(tilt - gt_tilt))
                if p["tilt_reliable"]:
                    tilt_errors.append(abs(p["tilt_angle"] - gt_tilt))
            else:
                fp += 1
                if positive:
                    fn += 1  # detected, but in the wrong place: a miss too
        elif positive:
            fn += 1
        else:
            tn += 1
    return {
        "dataset": "HLW test", "n": len(ids), "tolerance_frac_height": HORIZON_TOLERANCE,
        "coords": coords,
        "detection": {**metrics.precision_recall(tp, fp, fn), "tn": tn},
        "tilt_mae_deg_reliable": metrics.mean_ci(tilt_errors),
        "tilt_mae_deg_all_correct_detections": metrics.mean_ci(tilt_errors_all),
        "tilt_reported_fraction": round(len(tilt_errors) / tp, 4) if tp else None,
        "horizon_error_median": round(float(np.median(errors)), 4) if errors else None,
        "ms_per_image": round(float(np.mean([preds[str(root / 'images' / i)]["ms"] for i in ids])), 1),
    }


# ---------------------------------------------------------------------------
# Subject localization (DUTS-TE)
# ---------------------------------------------------------------------------


def _gt_box(mask_path: Path) -> tuple[tuple[float, float, float, float] | None, np.ndarray]:
    mask = np.asarray(Image.open(mask_path).convert("L")) > 127
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None, mask
    h, w = mask.shape
    return (xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h), mask


def _subject_one(path: str) -> dict[str, Any]:
    from app.services.composition import subject_localization as sl

    rgb = load_rgb(Path(path))
    out: dict[str, Any] = {}
    tiers: dict[str, Any] = {
        "detector": sl.YOLOWorldSubjectLocator(),
        "saliency": sl.SaliencySubjectLocator(),
        "composite": sl.CompositeSubjectLocator(),
    }
    if os.environ.get("BENCH_WITH_VLM") == "1":
        tiers["vlm"] = sl.VLMSubjectLocator()
    for name, locator in tiers.items():
        start = time.perf_counter()
        try:
            res = locator.locate(rgb)
        except Exception:  # noqa: BLE001
            res = None
        ms = (time.perf_counter() - start) * 1000
        if res is None:
            out[name] = {"bbox": None, "centroid": None, "ms": ms}
            continue
        s = res.subject
        out[name] = {
            "bbox": list(s.bbox) if s.bbox else None,
            "centroid": list(s.centroid),
            "source": s.source,
            "ms": ms,
        }
        if name == "composite":
            out[name]["tier"] = getattr(locator, "last_decision", {}).get("tier")
    return out


def run_subject(workers: int) -> dict[str, Any]:
    ids = _manifest("duts")["splits"]["test"]
    root = DATA_DIR / "duts"
    preds = _cached_map(
        "duts", "subject", [str(root / "images" / f"{i}.jpg") for i in ids], _subject_one, workers
    )
    gts = {i: _gt_box(root / "masks" / f"{i}.png") for i in ids}

    def score(get: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
        ious, ious_boxed, hits, ms = [], [], [], []
        for i in ids:
            p = get(i)
            gt_box, mask = gts[i]
            iou = metrics.box_iou(p["bbox"], gt_box)
            ious.append(iou)
            if p["bbox"] is not None:
                ious_boxed.append(iou)
            if p["centroid"] is not None:
                h, w = mask.shape
                cx = min(w - 1, int(p["centroid"][0] * w))
                cy = min(h - 1, int(p["centroid"][1] * h))
                hits.append(1.0 if mask[cy, cx] else 0.0)
            else:
                hits.append(0.0)
            ms.append(p.get("ms", 0.0))
        return {
            "box_iou_all": metrics.mean_ci(ious),  # no box counts as IoU 0
            "box_iou_when_boxed": metrics.mean_ci(ious_boxed),
            "box_coverage": round(len(ious_boxed) / len(ids), 4),
            "iou_at_0.5_rate": round(float(np.mean([x >= 0.5 for x in ious])), 4),
            "centroid_in_mask_rate": metrics.mean_ci(hits),
            "ms_per_image": round(float(np.mean(ms)), 1),
        }

    key = lambda i: str(root / "images" / f"{i}.jpg")  # noqa: E731
    tiers = sorted({t for p in preds.values() for t in p})
    out: dict[str, Any] = {"dataset": "DUTS-TE", "n": len(ids), "tiers": {}}
    for tier in tiers:
        out["tiers"][tier] = score(lambda i, t=tier: preds[key(i)][t])
    # The honest floor: a fixed centred box covering the middle 50% of each axis.
    out["tiers"]["center_prior_baseline"] = score(
        lambda i: {"bbox": [0.25, 0.25, 0.75, 0.75], "centroid": [0.5, 0.5], "ms": 0.0}
    )
    composite_tiers = [preds[key(i)]["composite"].get("tier") for i in ids]
    out["composite_tier_mix"] = {t: composite_tiers.count(t) for t in set(composite_tiers)}
    return out


# ---------------------------------------------------------------------------
# Composition (CADB) — features for the score + calibration
# ---------------------------------------------------------------------------


def _composition_one(path: str) -> dict[str, Any]:
    from app.services.composition.composition_pipeline import run_composition_analysis
    from PIL import ImageOps

    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    start = time.perf_counter()
    result = run_composition_analysis(image)
    result["_ms"] = (time.perf_counter() - start) * 1000
    return result


def composition_results(split: str, workers: int) -> dict[str, dict[str, Any]]:
    ids = _manifest("cadb")["splits"][split]
    root = DATA_DIR / "cadb"
    by_path = _cached_map(
        "cadb", "composition", [str(root / "images" / i) for i in ids], _composition_one, workers
    )
    return {i: by_path[str(root / "images" / i)] for i in ids}


def cadb_labels() -> tuple[dict[str, float], dict[str, float]]:
    root = DATA_DIR / "cadb" / "labels"
    comp = json.loads((root / "composition_scores.json").read_text(encoding="utf-8"))
    attrs = json.loads((root / "composition_attributes.json").read_text(encoding="utf-8"))
    return (
        {k: float(v["mean"]) for k, v in comp.items()},
        {k: float(v["score"]) for k, v in attrs.items()},  # AADB aesthetic, 0-1
    )


def koniq_labels() -> dict[str, float]:
    with (DATA_DIR / "koniq" / "labels.csv").open(encoding="utf-8", newline="") as f:
        return {r["img_name"]: float(r["mos"]) for r in csv.DictReader(f)}
