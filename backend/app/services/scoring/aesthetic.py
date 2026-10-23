"""Learned aesthetic score, served from an ONNX model.

Which model, and why, is decided by the benchmark (eval/results/RESULTS.md,
"Learned quality / aesthetic models"): correlation with human ratings weighed
against memory and latency on a 512 MB instance. The export script
(eval/benchmark/export_onnx.py) writes two files:

- ``aesthetic.onnx`` — the network, fixed input size, CPU-friendly opset;
- ``aesthetic.json`` — everything this module needs to drive it: input size,
  normalisation, how to read the output (a score distribution or a scalar),
  and the raw range that maps onto 0-100.

Optional by construction. If onnxruntime isn't installed or the model file
isn't there (a dev checkout that never ran the export, or a build that opts
out), ``score_image`` returns None and the composition score falls back to its
geometry-only calibrated model. Nothing else changes.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict[str, Any] = {"loaded": False, "session": None, "spec": None}


def _load() -> tuple[Any, dict[str, Any]] | None:
    with _lock:
        if _state["loaded"]:
            return (_state["session"], _state["spec"]) if _state["session"] else None
        _state["loaded"] = True
        settings = get_settings()
        if not settings.aesthetic_enabled:
            return None
        model_path = Path(settings.aesthetic_model_path)
        spec_path = model_path.with_suffix(".json")
        if not model_path.exists() or not spec_path.exists():
            logger.info(
                "Aesthetic model not present; aesthetic score disabled",
                extra={"path": str(model_path)},
            )
            return None
        try:
            import onnxruntime as ort
        except ImportError:
            logger.info("onnxruntime not installed; aesthetic score disabled")
            return None
        options = ort.SessionOptions()
        # One analysis at a time per worker; more threads buy little on a
        # shared vCPU and each one carries its own scratch buffers.
        options.intra_op_num_threads = settings.aesthetic_threads
        options.inter_op_num_threads = 1
        # The arena pre-allocates aggressively; off keeps RSS near what the
        # model actually needs, which matters more here than a few ms.
        options.enable_cpu_mem_arena = False
        session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        spec = json.loads(spec_path.read_text())
        _state.update(session=session, spec=spec)
        logger.info("Aesthetic model loaded", extra={"model": spec.get("name")})
        return session, spec


def model_name() -> str | None:
    loaded = _load()
    return loaded[1].get("name") if loaded else None


def _preprocess(image: Image.Image, spec: dict[str, Any]) -> np.ndarray:
    height, width = spec["input_size"]
    rgb = image.convert("RGB")
    if spec.get("resize") == "short_side_center_crop":
        # How the model was evaluated in training (torchvision Resize(int) +
        # CenterCrop): keep aspect, crop the middle. A plain resize would
        # squash the photo and shift the scores.
        w, h = rgb.size
        scale = max(width, height) / min(w, h)
        rgb = rgb.resize((max(width, round(w * scale)), max(height, round(h * scale))), Image.BILINEAR)
        w, h = rgb.size
        left, top = (w - width) // 2, (h - height) // 2
        rgb = rgb.crop((left, top, left + width, top + height))
    else:
        rgb = rgb.resize((width, height), Image.BICUBIC)
    x = np.asarray(rgb, dtype=np.float32) / 255.0
    mean = np.asarray(spec.get("mean", [0.0, 0.0, 0.0]), dtype=np.float32)
    std = np.asarray(spec.get("std", [1.0, 1.0, 1.0]), dtype=np.float32)
    x = (x - mean) / std
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


def _raw_score(output: np.ndarray, spec: dict[str, Any]) -> float:
    out = np.asarray(output, dtype=np.float64).reshape(-1)
    if spec.get("output") == "distribution":
        # NIMA-style: probabilities over score bins 1..K -> expected score.
        probs = out / out.sum() if out.sum() > 0 else out
        return float(np.dot(probs, np.arange(1, len(probs) + 1)))
    return float(out[0])


def to_100(raw: float, spec: dict[str, Any]) -> float:
    lo, hi = spec["raw_range"]
    return round(float(np.clip((raw - lo) / (hi - lo), 0.0, 1.0)) * 100, 1)


def score_image(image: Image.Image) -> dict[str, Any] | None:
    """{"score": 0-100, "raw": model units, "model": name}, or None if disabled."""
    loaded = _load()
    if loaded is None:
        return None
    session, spec = loaded
    try:
        x = _preprocess(image, spec)
        (output,) = session.run(None, {session.get_inputs()[0].name: x})
        raw = _raw_score(output, spec)
    except Exception:  # noqa: BLE001 - a scoring failure must not fail the analysis
        logger.warning("Aesthetic scoring failed", exc_info=True)
        return None
    return {"score": to_100(raw, spec), "raw": round(raw, 4), "model": spec.get("name")}


def reset_for_tests() -> None:
    with _lock:
        _state.update(loaded=False, session=None, spec=None)
