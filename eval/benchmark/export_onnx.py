"""Export the chosen aesthetic model to ONNX for the app, and verify it.

    python -m benchmark.export_onnx --model nima --out ../backend/models

Writes ``aesthetic.onnx`` plus ``aesthetic.json`` (the sidecar
app/services/scoring/aesthetic.py reads), then checks the export three ways:

1. **Parity**: ONNX Runtime vs. the original PyTorch model on real benchmark
   images, through each side's own preprocessing — the correlation must be
   ~1.0 and the max abs difference tiny.
2. **Memory**: RSS of a fresh process that loads only onnxruntime + the model
   and scores an image, which is what the app actually pays.
3. **Latency**: mean ms/image on CPU with the app's thread setting.

Optionally ``--quantize`` writes a dynamic-int8 copy and runs the same checks
on it, for builds where even the fp32 weights are too much.

The model is wrapped so the ONNX graph takes an already-cropped, normalised
1x3xHxW tensor and returns the 10-bin score distribution. Resize + centre
crop + normalisation happen in numpy in the app (aesthetic._preprocess),
matching pyiqa's own eval-mode preprocessing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from benchmark.fetch import DATA_DIR  # noqa: E402

# Per exportable model: how to build the core network and how the app must
# feed it. Only models whose preprocessing is a fixed-size crop are listed —
# MUSIQ's multi-scale patching and CLIP-IQA's prompt logic don't reduce to a
# static graph worth maintaining.
EXPORTABLE = {
    "nima": {"output": "distribution"},
    "nima-vgg16-ava": {"output": "distribution"},
}


def _core(model_name: str):
    import pyiqa
    import torch

    metric = pyiqa.create_metric(model_name, device="cpu", as_loss=False)
    net = metric.net.eval()

    class Core(torch.nn.Module):
        """NIMA without its preprocess(): features -> pool -> softmax head."""

        def __init__(self) -> None:
            super().__init__()
            self.base_model = net.base_model
            self.global_pool = net.global_pool
            self.classifier = net.classifier

        def forward(self, x):
            feats = self.base_model(x)[-1]
            return self.classifier(self.global_pool(feats))

    size = int(net.base_model.default_cfg["input_size"][-1])
    mean = [float(v) for v in net.default_mean.reshape(-1)]
    std = [float(v) for v in net.default_std.reshape(-1)]
    return metric, Core().eval(), size, mean, std


def _sample_images(n: int) -> list[Path]:
    manifest = json.loads((Path(__file__).parent / "manifests" / "cadb.json").read_text(encoding="utf-8"))
    return [DATA_DIR / "cadb" / "images" / name for name in manifest["splits"]["test"][:n]]


def _onnx_scores(model_path: Path, spec: dict, images: list[Path]) -> tuple[list[float], float]:
    import onnxruntime as ort
    from PIL import Image

    from app.services.scoring import aesthetic

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    sess = ort.InferenceSession(str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    scores, times = [], []
    for path in images:
        img = Image.open(path).convert("RGB")
        img.thumbnail((512, 512), Image.LANCZOS)  # what the benchmark fed pyiqa
        x = aesthetic._preprocess(img, spec)
        start = time.perf_counter()
        (out,) = sess.run(None, {name: x})
        times.append((time.perf_counter() - start) * 1000)
        scores.append(aesthetic._raw_score(out, spec))
    return scores, float(np.mean(times[1:])) if len(times) > 1 else float(times[0])


def _torch_scores(metric, images: list[Path]) -> list[float]:
    import torch
    from PIL import Image

    out = []
    with torch.inference_mode():
        for path in images:
            img = Image.open(path).convert("RGB")
            img.thumbnail((512, 512), Image.LANCZOS)
            x = torch.from_numpy(np.asarray(img).copy()).permute(2, 0, 1).float().unsqueeze(0) / 255
            out.append(float(metric(x).reshape(-1)[0]))
    return out


_RSS_PROBE = r"""
import json, sys, psutil
proc = psutil.Process()
base = proc.memory_info().rss
sys.path.insert(0, sys.argv[3])
import onnxruntime as ort
from PIL import Image
from app.services.scoring import aesthetic
spec = json.load(open(sys.argv[2]))
opts = ort.SessionOptions(); opts.intra_op_num_threads = 2; opts.enable_cpu_mem_arena = False
sess = ort.InferenceSession(sys.argv[1], sess_options=opts, providers=["CPUExecutionProvider"])
loaded = proc.memory_info().rss
x = aesthetic._preprocess(Image.new("RGB", (1920, 1280), (120, 120, 120)), spec)
for _ in range(3):
    sess.run(None, {sess.get_inputs()[0].name: x})
info = proc.memory_info()
peak = getattr(info, "peak_wset", info.rss)
print(json.dumps({"python_baseline_mb": base / 2**20, "after_load_mb": loaded / 2**20,
                  "after_inference_mb": info.rss / 2**20, "peak_mb": peak / 2**20}))
"""


def _rss(model_path: Path, spec_path: Path) -> dict:
    out = subprocess.run(
        [sys.executable, "-c", _RSS_PROBE, str(model_path), str(spec_path), str(REPO / "backend")],
        capture_output=True, text=True, check=True,
    )
    vals = json.loads(out.stdout.strip().splitlines()[-1])
    return {k: round(v, 1) for k, v in vals.items()}


def main() -> None:
    import torch

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="nima", choices=list(EXPORTABLE))
    parser.add_argument("--out", default=str(REPO / "backend" / "models"))
    parser.add_argument("--parity-images", type=int, default=50)
    parser.add_argument("--quantize", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    metric, core, size, mean, std = _core(args.model)
    onnx_path = out_dir / "aesthetic.onnx"
    torch.onnx.export(
        core, torch.zeros(1, 3, size, size), str(onnx_path),
        input_names=["image"], output_names=["distribution"], opset_version=17, dynamo=False,
    )

    calibration = json.loads(
        (REPO / "backend" / "app" / "services" / "scoring" / "calibration.json").read_text(encoding="utf-8")
    )
    raw_range = next(
        (m["aesthetic_raw_range"] for m in calibration["models"] if m.get("aesthetic_model") == args.model),
        [1.0, 10.0],
    )
    spec = {
        "name": args.model,
        "input_size": [size, size],
        "resize": "short_side_center_crop",
        "mean": mean,
        "std": std,
        "output": EXPORTABLE[args.model]["output"],
        # Same mapping onto 0-100 the calibration was fitted with.
        "raw_range": raw_range,
    }
    spec_path = out_dir / "aesthetic.json"
    spec_path.write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")

    images = _sample_images(args.parity_images)
    reference = _torch_scores(metric, images)
    report: dict = {"model": args.model, "onnx_bytes": onnx_path.stat().st_size, "variants": {}}
    variants = [("fp32", onnx_path)]
    if args.quantize:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        q_path = out_dir / "aesthetic.int8.onnx"
        quantize_dynamic(str(onnx_path), str(q_path), weight_type=QuantType.QUInt8)
        variants.append(("int8", q_path))
    for label, path in variants:
        scores, ms = _onnx_scores(path, spec, images)
        diff = np.abs(np.array(scores) - np.array(reference))
        report["variants"][label] = {
            "file_mb": round(path.stat().st_size / 2**20, 1),
            "parity_pearson": round(float(np.corrcoef(scores, reference)[0, 1]), 5),
            "parity_max_abs_diff": round(float(diff.max()), 5),
            "ms_per_image": round(ms, 1),
            "memory": _rss(path, spec_path),
        }
    results = REPO / "eval" / "results" / "onnx_export.json"
    results.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
