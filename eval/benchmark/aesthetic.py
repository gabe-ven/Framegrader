"""Candidate learned quality/aesthetic models: accuracy *and* cost.

Each candidate is scored in its own subprocess (`python -m benchmark.aesthetic
score ...`) so the memory numbers are clean: resident set before loading,
after loading, and the peak during inference, measured by the OS. Latency is
mean wall-clock per image on CPU after a warm-up image.

Inputs are downscaled to a 512px long edge first, because that is what the
app would feed the model (the analysis image is capped at 1920px and nobody
pays for MUSIQ's multi-scale pass at full resolution on a free instance).

Candidates and what they were trained on — this matters for reading the KonIQ
column: a model trained on KonIQ's train split is being tested in-domain.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from benchmark.fetch import DATA_DIR

CANDIDATES: dict[str, dict[str, str]] = {
    "nima": {"family": "NIMA (InceptionResNetV2)", "trained_on": "AVA"},
    "nima-vgg16-ava": {"family": "NIMA (VGG16)", "trained_on": "AVA"},
    "musiq-ava": {"family": "MUSIQ (multi-scale ViT)", "trained_on": "AVA"},
    "musiq-koniq": {"family": "MUSIQ (multi-scale ViT)", "trained_on": "KonIQ train"},
    "clipiqa": {"family": "CLIP-IQA (RN50, zero-shot prompts)", "trained_on": "none (zero-shot)"},
    "laion_aes": {"family": "LAION aesthetic (CLIP ViT-L/14 + MLP)", "trained_on": "SAC + LAION-Logos + AVA"},
    "topiq_iaa": {"family": "TOPIQ (Swin)", "trained_on": "AVA"},
}

INPUT_MAX_EDGE = 512


def _images(dataset: str, split: str) -> list[Path]:
    manifest = json.loads((Path(__file__).parent / "manifests" / f"{dataset}.json").read_text(encoding="utf-8"))
    return [DATA_DIR / dataset / "images" / name for name in manifest["splits"][split]]


def _rss_mb() -> tuple[float, float]:
    import psutil

    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None)  # Windows exposes the true peak
    if peak is None:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # Linux: KB
    return info.rss / 2**20, peak / 2**20


def score_cmd(model: str, targets: list[tuple[str, str]], threads: int) -> None:
    """Child-process entry: score every image of every (dataset, split)."""
    import torch
    from PIL import Image

    torch.set_num_threads(threads)
    rss_before, _ = _rss_mb()
    import pyiqa

    metric = pyiqa.create_metric(model, device="cpu", as_loss=False)
    metric.eval()
    rss_loaded, _ = _rss_mb()
    n_params = sum(p.numel() for p in metric.parameters())

    def prep(path: Path) -> torch.Tensor:
        img = Image.open(path).convert("RGB")
        img.thumbnail((INPUT_MAX_EDGE, INPUT_MAX_EDGE), Image.LANCZOS)
        import numpy as np

        arr = torch.from_numpy(np.asarray(img).copy()).permute(2, 0, 1).float() / 255.0
        return arr.unsqueeze(0)

    timings: list[float] = []
    for dataset, split in targets:
        out_path = DATA_DIR / dataset / "cache" / f"aesthetic_{model}.json"
        scores: dict[str, float] = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
        paths = [p for p in _images(dataset, split) if p.name not in scores]
        with torch.inference_mode():
            for i, path in enumerate(paths):
                x = prep(path)
                start = time.perf_counter()
                value = float(metric(x).reshape(-1)[0])
                if i > 0 or timings:  # first call includes lazy init
                    timings.append((time.perf_counter() - start) * 1000)
                scores[path.name] = value
                if (i + 1) % 100 == 0:
                    print(f"    {model} {dataset}/{split}: {i + 1}/{len(paths)}", flush=True)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(json.dumps(scores), encoding="utf-8")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(scores), encoding="utf-8")

    rss_now, rss_peak = _rss_mb()
    resources_path = DATA_DIR / "aesthetic_resources.json"
    resources = json.loads(resources_path.read_text(encoding="utf-8")) if resources_path.exists() else {}
    prev = resources.get(model, {})
    resources[model] = {
        "params_m": round(n_params / 1e6, 1),
        "rss_before_mb": round(rss_before, 0),
        "model_load_mb": round(rss_loaded - rss_before, 0),
        "peak_rss_mb": round(max(rss_peak, prev.get("peak_rss_mb", 0)), 0),
        "ms_per_image": round(sum(timings) / len(timings), 1) if timings else prev.get("ms_per_image"),
        "threads": threads,
        "input_max_edge": INPUT_MAX_EDGE,
    }
    resources_path.write_text(json.dumps(resources, indent=1), encoding="utf-8")


def ensure_scores(models: list[str], targets: list[tuple[str, str]], threads: int) -> None:
    for model in models:
        missing = any(
            not (DATA_DIR / d / "cache" / f"aesthetic_{model}.json").exists()
            or len(json.loads((DATA_DIR / d / "cache" / f"aesthetic_{model}.json").read_text(encoding="utf-8")))
            < len(_images(d, s))
            for d, s in targets
        )
        if not missing:
            continue
        print(f"  scoring with {model} …", flush=True)
        args = [sys.executable, "-m", "benchmark.aesthetic", "score", "--model", model, "--threads", str(threads)]
        for d, s in targets:
            args += ["--target", f"{d}:{s}"]
        subprocess.run(args, check=True, cwd=Path(__file__).resolve().parents[1], env={**os.environ})


def load_scores(model: str, dataset: str) -> dict[str, float]:
    return json.loads((DATA_DIR / dataset / "cache" / f"aesthetic_{model}.json").read_text(encoding="utf-8"))


def load_resources() -> dict[str, Any]:
    path = DATA_DIR / "aesthetic_resources.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--model", required=True, choices=list(CANDIDATES))
    s.add_argument("--target", action="append", required=True, help="dataset:split")
    s.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    score_cmd(args.model, [tuple(t.split(":")) for t in args.target], args.threads)  # type: ignore[misc]


if __name__ == "__main__":
    main()
