"""Subject localization: find *the subject* of a photo.

This replaces the gradient-energy centroid as the notion of "where the subject
is" for rule-of-thirds, subject-position, and negative-space. Locators are
tried in order, cheapest/most-reliable-when-confident first:

    1. YOLOWorldSubjectLocator — open-vocab detection + GrabCut mask refine.
       Fast, free, no network call. YOLO-World's raw confidence scores are
       poorly calibrated across photos (everything from 0.0000-0.13, even on
       correct detections), so an absolute threshold can't reliably separate
       real subjects from noise. CompositeSubjectLocator instead applies a
       RELATIVE gate: trust the top detection only if it beats the second-best
       by more than 3x AND clears an absolute floor of 0.10.
    2. VLMSubjectLocator — escalates to a vision-language model (Claude) when
       YOLO-World doesn't clear that bar. Answers "what did the photographer
       intend to shoot" directly, rather than "what objects are present".
       Skipped silently if ANTHROPIC_API_KEY isn't configured, and gated on
       its own reported confidence so a low-confidence VLM guess doesn't
       override the more honest saliency fallback.
    3. SaliencySubjectLocator — gradient-energy centroid. Always succeeds;
       final fallback so the pipeline never ends up with no Subject at all.

CompositeSubjectLocator owns all of the above orchestration/gating; each
individual locator only knows how to do its own job.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.services.composition._utils import saliency_centroid, to_gray_u8
from app.services.composition.subject import Subject

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locator interface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocatorResult:
    """What a SubjectLocator produces: a Subject candidate plus locator-
    specific diagnostics (e.g. raw confidence gap) that CompositeSubjectLocator
    may use to decide whether to trust it.
    """

    subject: Subject
    diagnostics: dict[str, Any] = field(default_factory=dict)


class SubjectLocator(ABC):
    """A strategy for locating the subject of a photo.

    Implementations should stay narrowly focused on "how do I find a
    subject" — trust/escalation decisions across locators belong in
    CompositeSubjectLocator, not here.
    """

    @abstractmethod
    def locate(self, rgb: np.ndarray) -> LocatorResult | None:
        """Return a LocatorResult, or None if this locator found nothing usable."""


# ---------------------------------------------------------------------------
# Tier 1: YOLO-World open-vocab detector + GrabCut refinement
# ---------------------------------------------------------------------------

# YOLO-World checkpoint. Small variant keeps CPU latency/download reasonable.
_MODEL_NAME = "yolov8s-worldv2.pt"

# Near-zero pre-filter only — drops literal noise so we don't run GrabCut on
# garbage. The real trust decision (abs floor + relative ratio) lives in
# CompositeSubjectLocator, which needs the true top-2 raw confidences to make
# it, so this can't be a meaningful threshold on its own.
_MIN_DETECTION_CONF = 0.01

# Generic open-vocabulary prompt list — the things photos are usually "about".
# YOLO-World scores boxes against these text prompts rather than fixed classes.
_DEFAULT_VOCAB: tuple[str, ...] = (
    # --- original subject vocabulary (people, animals, objects) ---
    "person",
    "face",
    "animal",
    "dog",
    "cat",
    "bird",
    "horse",
    "car",
    "bicycle",
    "motorcycle",
    "boat",
    "airplane",
    "building",
    "flower",
    "plant",
    "tree",
    "food",
    "bottle",
    "cup",
    "statue",
    "sign",
    # --- additive: discrete architecture/structure subjects (see note) ---
    # Added because some structural subjects had no matching prompt (e.g. a
    # bridge only matched the generic "building"). Additive only — nothing above
    # was removed or renamed.
    #
    # NOTE: large background-region terms (sky, skyline, cityscape, mountain,
    # water) were intentionally NOT added. Empirically they make YOLO-World
    # label the background as the "subject" (a night bridge photo picked the
    # sky at 0.33), and the area-weighted box selection below then favors that
    # huge region — the opposite of a subject. Keep prompts to discrete things.
    "bridge",
    "tower",
    "road",
)

# GrabCut iterations for mask refinement from the detection box.
_GRABCUT_ITERS = 5

# Resolution cap for YOLO-World inference. The model internally uses 640 px
# anyway; passing a pre-downsampled array avoids numpy/tensor conversion
# overhead on large camera files (e.g. 26 MP FUJI raw).
_YOLO_INFER_MAX_EDGE = 1280


class YOLOWorldSubjectLocator(SubjectLocator):
    """Open-vocab detection (YOLO-World) + GrabCut mask refinement.

    Lazily loads a thread-safe, process-wide singleton model on first use.
    Reports the raw top-2 detection confidences as diagnostics so
    CompositeSubjectLocator can decide whether the result is trustworthy —
    this class does not gate on confidence itself.
    """

    _model = None
    _model_load_failed = False
    _model_lock = threading.Lock()
    # Ultralytics locks *inference* (BasePredictor._lock) but not the lazy
    # construction of the predictor itself: Model.predict does an unguarded
    # `if not self.predictor: self.predictor = ...`. Loading the weights does
    # not build it — only the first predict() call does — so once the route
    # handlers run in a threadpool, two concurrent first requests can race
    # there. These serialize that first call; afterwards it is a flag check.
    _predictor_ready = False
    _predictor_lock = threading.Lock()

    @classmethod
    def _ensure_predictor(cls, model) -> None:
        """Build the predictor exactly once, under a lock.

        Runs a throwaway inference because that is the only way to trigger
        construction through ultralytics' public API. Failures are swallowed:
        the real call right after will surface any genuine problem, and a
        warm-up that cannot run must not take the detector tier down.
        """
        if cls._predictor_ready:
            return
        with cls._predictor_lock:
            if cls._predictor_ready:
                return
            try:
                model.predict(
                    np.zeros((640, 640, 3), dtype=np.uint8),
                    conf=_MIN_DETECTION_CONF,
                    verbose=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "YOLO-World predictor warm-up failed (%s: %s); continuing.",
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
            cls._predictor_ready = True

    @classmethod
    def warm_up(cls) -> None:
        """Load the weights *and* build the predictor, off the request path.

        Called from the startup warm-up thread. Loading alone left the first
        real request paying predictor construction (the ~30s cold start) and
        exposed the race described above.
        """
        model = cls._get_model()
        if model is not None:
            cls._ensure_predictor(model)

    @classmethod
    def _get_model(cls):
        """Return a cached YOLO-World model, or ``None`` if it can't be loaded.

        Thread-safe and memoized: a failed load is remembered so we don't retry
        (and re-log) on every request.
        """
        if cls._model is not None:
            return cls._model
        if cls._model_load_failed:
            return None

        with cls._model_lock:
            if cls._model is not None:
                return cls._model
            if cls._model_load_failed:
                return None
            try:
                from ultralytics import YOLO

                model = YOLO(_MODEL_NAME)
                model.set_classes(list(_DEFAULT_VOCAB))
                cls._model = model
                logger.info(
                    "Loaded YOLO-World model %s for subject localization", _MODEL_NAME
                )
                return cls._model
            except Exception as exc:  # noqa: BLE001 - any failure -> escalate
                cls._model_load_failed = True
                logger.warning(
                    "YOLO-World load/import failed (%s: %s); skipping detector tier.",
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                return None

    def locate(self, rgb: np.ndarray) -> LocatorResult | None:
        model = self._get_model()
        if model is None:
            return None
        # No-op once warmed; only matters if a request beats the startup thread.
        self._ensure_predictor(model)

        orig_h, orig_w = rgb.shape[:2]

        # Downsample to _YOLO_INFER_MAX_EDGE before inference to avoid
        # tensor-conversion overhead on large camera files. Boxes returned by
        # the model are in the downsampled coordinate space and must be scaled
        # back before being passed to _refine_mask (which runs on the original).
        long_edge = max(orig_h, orig_w)
        if long_edge > _YOLO_INFER_MAX_EDGE:
            infer_scale = _YOLO_INFER_MAX_EDGE / long_edge
            infer_w = max(1, int(orig_w * infer_scale))
            infer_h = max(1, int(orig_h * infer_scale))
            rgb_infer = cv2.resize(rgb, (infer_w, infer_h), interpolation=cv2.INTER_AREA)
        else:
            infer_scale = 1.0
            infer_w, infer_h = orig_w, orig_h
            rgb_infer = rgb

        try:
            results = model.predict(rgb_infer, conf=_MIN_DETECTION_CONF, verbose=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "YOLO-World inference failed (%s: %s); skipping detector tier.",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return None

        if not results:
            return None

        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return None

        best = _best_box(result, infer_w, infer_h)
        if best is None:
            return None

        top_confidence, second_confidence = _top_two_confidences(boxes)

        (x0, y0, x1, y1), confidence, label = best

        # Scale pixel coords back to original resolution for mask refinement.
        if infer_scale != 1.0:
            inv = 1.0 / infer_scale
            x0 = int(x0 * inv)
            y0 = int(y0 * inv)
            x1 = int(x1 * inv)
            y1 = int(y1 * inv)

        bbox_norm = (
            x0 / max(orig_w - 1, 1),
            y0 / max(orig_h - 1, 1),
            x1 / max(orig_w - 1, 1),
            y1 / max(orig_h - 1, 1),
        )
        mask = _refine_mask(rgb, (x0, y0, x1, y1))
        subject = Subject.from_detection(
            bbox_norm, confidence=confidence, label=label, mask=mask
        )
        return LocatorResult(
            subject=subject,
            diagnostics={
                "top_confidence": top_confidence,
                "second_confidence": second_confidence,
            },
        )


def _top_two_confidences(boxes) -> tuple[float, float]:
    """Return the two highest raw per-box detection confidences.

    ``second`` is ``0.0`` when there's only one candidate box — i.e. no
    competing detection to be uncertain against.
    """
    confs = boxes.conf.cpu().numpy()
    if confs.size == 0:
        return 0.0, 0.0
    ranked = np.sort(confs)[::-1]
    top = float(ranked[0])
    second = float(ranked[1]) if ranked.size > 1 else 0.0
    return top, second


def _best_box(
    result, width: int, height: int
) -> tuple[tuple[int, int, int, int], float, str | None] | None:
    """Pick the most "subject-like" box by confidence x normalized area."""
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return None

    names = getattr(result, "names", {}) or {}
    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy()
    classes = boxes.cls.cpu().numpy().astype(int)

    frame_area = float(max(width * height, 1))
    best_score = -1.0
    best: tuple[tuple[int, int, int, int], float, str | None] | None = None

    for (bx0, by0, bx1, by1), conf, cls_id in zip(xyxy, confs, classes):
        x0 = int(round(float(bx0)))
        y0 = int(round(float(by0)))
        x1 = int(round(float(bx1)))
        y1 = int(round(float(by1)))
        box_area = max(x1 - x0, 0) * max(y1 - y0, 0)
        if box_area <= 0:
            continue
        score = float(conf) * (box_area / frame_area)
        if score > best_score:
            best_score = score
            label = names.get(int(cls_id)) if isinstance(names, dict) else None
            best = ((x0, y0, x1, y1), float(conf), label)

    return best


_GRABCUT_MAX_EDGE = 1024  # downsample to this before running GrabCut

# Fixed seed for OpenCV's (thread-local) RNG so GrabCut is reproducible.
# Any constant works; the value is arbitrary, the fixedness is the point.
_CV_RNG_SEED = 42


def _refine_mask(
    rgb: np.ndarray, box: tuple[int, int, int, int]
) -> np.ndarray | None:
    """Refine the detection box into a pixel mask with GrabCut.

    Returns a boolean ``(H, W)`` mask at the original image resolution, or
    ``None`` if refinement isn't viable (degenerate box, tiny image, or
    GrabCut failure) so the caller can fall back to the bbox footprint.

    GrabCut runs on a downsampled copy (long edge ≤ ``_GRABCUT_MAX_EDGE``) so
    it stays fast even on high-resolution camera files.
    """
    orig_h, orig_w = rgb.shape[:2]
    x0, y0, x1, y1 = box

    # Clamp to a valid rect strictly inside the image; GrabCut requires it.
    x0 = max(0, min(x0, orig_w - 1))
    y0 = max(0, min(y0, orig_h - 1))
    x1 = max(0, min(x1, orig_w))
    y1 = max(0, min(y1, orig_h))
    if (x1 - x0) < 2 or (y1 - y0) < 2 or orig_w < 3 or orig_h < 3:
        return None

    # --- Downsample for GrabCut speed ---
    long_edge = max(orig_h, orig_w)
    if long_edge > _GRABCUT_MAX_EDGE:
        scale = _GRABCUT_MAX_EDGE / long_edge
        small_w = max(3, int(orig_w * scale))
        small_h = max(3, int(orig_h * scale))
        rgb_small = cv2.resize(rgb, (small_w, small_h), interpolation=cv2.INTER_AREA)
        sx0 = max(0, min(int(x0 * scale), small_w - 1))
        sy0 = max(0, min(int(y0 * scale), small_h - 1))
        sx1 = max(0, min(int(x1 * scale), small_w))
        sy1 = max(0, min(int(y1 * scale), small_h))
    else:
        scale = 1.0
        small_w, small_h = orig_w, orig_h
        rgb_small = rgb
        sx0, sy0, sx1, sy1 = x0, y0, x1, y1

    rect_w = sx1 - sx0
    rect_h = sy1 - sy0
    if rect_w < 2 or rect_h < 2:
        return None

    bgr = np.ascontiguousarray(rgb_small[:, :, ::-1], dtype=np.uint8)
    gc_mask = np.zeros((small_h, small_w), dtype=np.uint8)
    bgd_model = np.zeros((1, 65), dtype=np.float64)
    fgd_model = np.zeros((1, 65), dtype=np.float64)

    # GrabCut seeds its internal GMMs from OpenCV's RNG, so an unseeded run
    # gives a different mask every time — measured a 2.3x swing in mask area on
    # identical input, which moved the subject centroid enough to change its
    # rule-of-thirds score and its 3x3 region. That made composition metrics
    # irreproducible and the eval harness unable to attribute a score change to
    # a code change. cv2's RNG is thread-local, so seeding here is confined to
    # the request's own thread and safe under the handler threadpool.
    cv2.setRNGSeed(_CV_RNG_SEED)

    try:
        cv2.grabCut(
            bgr,
            gc_mask,
            (sx0, sy0, rect_w, rect_h),
            bgd_model,
            fgd_model,
            _GRABCUT_ITERS,
            cv2.GC_INIT_WITH_RECT,
        )
    except Exception:  # noqa: BLE001
        logger.debug("GrabCut refinement failed; using bbox footprint.", exc_info=True)
        return None

    foreground_small = (gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD)
    if not foreground_small.any():
        return None

    # Upsample mask back to original resolution if we downsampled.
    if scale != 1.0:
        foreground = (
            cv2.resize(
                foreground_small.astype(np.uint8),
                (orig_w, orig_h),
                interpolation=cv2.INTER_NEAREST,
            )
            > 0
        )
    else:
        foreground = foreground_small

    return foreground


# ---------------------------------------------------------------------------
# Tier 2: VLM (Claude) subject identification
# ---------------------------------------------------------------------------

_VLM_MODEL = "claude-sonnet-4-6"
_VLM_MAX_EDGE = 1024
_VLM_MAX_TOKENS = 256

_VLM_SYSTEM_PROMPT = (
    "You are a photography composition analyzer. Given a photo, identify the "
    "single most likely intended photographic subject — the thing the "
    "photographer pointed the camera at. Return ONLY a JSON object with these "
    "fields, no other text:\n"
    "{\n"
    "  'label': string (one or two words describing the subject),\n"
    "  'bbox': [x1, y1, x2, y2] (normalized 0.0-1.0 coordinates, \n"
    "           top-left origin),\n"
    "  'confidence': float (0.0-1.0, your confidence this is the \n"
    "                photographer's intended subject)\n"
    "}\n"
    "If the image has no clear single subject (abstract, pure texture, etc.), "
    "return confidence below 0.4 and bbox covering the most visually prominent "
    "region."
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class VLMSubjectLocator(SubjectLocator):
    """Ask a vision-language model (Claude) what the photo's subject is.

    Directly answers "what did the photographer intend to shoot" rather than
    "what objects are present" — used as an escalation when YOLO-World's
    confidence is too ambiguous to trust (see CompositeSubjectLocator's gate).

    Independently testable: pass a fake/mock ``client`` (anything exposing
    ``.messages.create(...)`` like the Anthropic SDK) to the constructor to
    avoid a real network call in tests.
    """

    def __init__(self, *, client: Any | None = None, model: str = _VLM_MODEL) -> None:
        self._client = client
        self._model = model

    def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning(
                "ANTHROPIC_API_KEY not set; skipping VLM subject localization."
            )
            return None

        try:
            from anthropic import Anthropic
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "anthropic SDK unavailable (%s: %s); skipping VLM subject "
                "localization.",
                type(exc).__name__,
                exc,
            )
            return None

        self._client = Anthropic(api_key=api_key)
        return self._client

    def locate(self, rgb: np.ndarray) -> LocatorResult | None:
        client = self._get_client()
        if client is None:
            return None

        try:
            image_b64, media_type = _encode_for_vlm(rgb)
            response = client.messages.create(
                model=self._model,
                max_tokens=_VLM_MAX_TOKENS,
                system=_VLM_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": "Identify the main photographic subject.",
                            },
                        ],
                    }
                ],
            )
            text = _extract_response_text(response)
            parsed = _parse_vlm_json(text)
        except Exception as exc:  # noqa: BLE001 - never let a VLM failure crash the pipeline
            logger.warning(
                "VLM subject localization failed (%s: %s); falling back.",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return None

        if parsed is None:
            logger.warning("VLM response was not parseable JSON: %r", text)
            return None

        bbox = _validate_vlm_bbox(parsed.get("bbox"))
        if bbox is None:
            logger.warning("VLM response had an invalid bbox: %r", parsed.get("bbox"))
            return None

        label = parsed.get("label")
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        subject = Subject.from_detection(
            bbox, confidence=confidence, label=label, mask=None, source="vlm"
        )
        return LocatorResult(subject=subject, diagnostics={"vlm_confidence": confidence})


def _encode_for_vlm(rgb: np.ndarray) -> tuple[str, str]:
    """Resize to <=1024px on the long edge and base64-encode as JPEG."""
    image = Image.fromarray(rgb)
    width, height = image.size
    scale = _VLM_MAX_EDGE / float(max(width, height))
    if scale < 1.0:
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = image.resize(new_size, Image.LANCZOS)

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=85)
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii"), "image/jpeg"


def _extract_response_text(response: Any) -> str:
    """Pull the concatenated text out of an Anthropic Messages API response."""
    blocks = getattr(response, "content", None) or []
    texts = [getattr(block, "text", None) for block in blocks]
    return "".join(t for t in texts if t)


def _parse_vlm_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON parse of the VLM response.

    Tolerates minor deviations (surrounding prose, single-quoted keys/strings)
    since a VLM's output format can't be fully constrained.
    """
    if not text:
        return None

    match = _JSON_OBJECT_RE.search(text)
    candidate = match.group(0) if match else text

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    try:
        import ast

        parsed = ast.literal_eval(candidate)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, SyntaxError):
        return None


def _validate_vlm_bbox(raw: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not all(0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


# ---------------------------------------------------------------------------
# Tier 3: saliency centroid (always succeeds — final fallback)
# ---------------------------------------------------------------------------


class SaliencySubjectLocator(SubjectLocator):
    """Gradient-energy saliency centroid. The original, pre-detector heuristic.

    Always succeeds (never returns ``None``) so the pipeline always ends up
    with *some* Subject.
    """

    def locate(self, rgb: np.ndarray) -> LocatorResult:
        gray = to_gray_u8(rgb)
        subject = Subject.from_saliency(saliency_centroid(gray))
        return LocatorResult(subject=subject)


# ---------------------------------------------------------------------------
# Composite: orchestrates the tier chain and both confidence gates
# ---------------------------------------------------------------------------


class CompositeSubjectLocator(SubjectLocator):
    """Chains locators, cheapest/most-reliable-when-confident first.

    1. YOLOWorldSubjectLocator — trusted only if its top raw detection
       confidence beats the second-best by more than ``_YOLO_RATIO_THRESHOLD``
       AND clears an absolute floor of ``_YOLO_ABS_FLOOR``. YOLO-World's raw
       confidences are poorly calibrated across photos (see module docstring),
       so an absolute-only threshold isn't reliable on its own — the relative
       comparison is what actually distinguishes a real detection from noise.
    2. VLMSubjectLocator — escalates to Claude when YOLO-World doesn't clear
       that bar. Its own reported confidence must clear ``_VLM_CONF_FLOOR``,
       so a low-confidence VLM guess ("no clear subject") doesn't override the
       more honest saliency fallback. Silently skipped if unconfigured (see
       VLMSubjectLocator).
    3. SaliencySubjectLocator — final fallback, always succeeds.
    """

    _YOLO_RATIO_THRESHOLD = 3.0
    _YOLO_ABS_FLOOR = 0.10
    # Above this confidence, trust YOLO-World unconditionally — no ratio check
    # needed when the model is already very confident (e.g. two people detected
    # at equal ~0.90 confidence both clear this bar so we take the best box
    # rather than escalating to VLM unnecessarily).
    _YOLO_HIGH_CONF_SHORTCUT = 0.5
    _VLM_CONF_FLOOR = 0.4

    def __init__(
        self,
        *,
        yolo: SubjectLocator | None = None,
        vlm: SubjectLocator | None = None,
        saliency: SubjectLocator | None = None,
    ) -> None:
        self._yolo = yolo or YOLOWorldSubjectLocator()
        self._vlm = vlm or VLMSubjectLocator()
        self._saliency = saliency or SaliencySubjectLocator()
        # Diagnostics from the most recent locate() call — which tier fired
        # and why. Populated fresh on every call; read it right after
        # locate() returns if you need it (see locate_subject_with_diagnostics).
        self.last_decision: dict[str, Any] = {}

    def locate(self, rgb: np.ndarray) -> LocatorResult:
        yolo_result = self._safe_locate(self._yolo, rgb, "YOLO-World")
        if yolo_result is not None and self._passes_yolo_gate(yolo_result.diagnostics):
            self.last_decision = {
                "tier": "detector",
                "reason": self._yolo_gate_reason(yolo_result.diagnostics, passed=True),
            }
            return yolo_result

        yolo_reason = (
            self._yolo_gate_reason(yolo_result.diagnostics, passed=False)
            if yolo_result is not None
            else "YOLO-World found no usable detection"
        )

        vlm_result = self._safe_locate(self._vlm, rgb, "VLM")
        if vlm_result is not None and self._passes_vlm_gate(vlm_result.diagnostics):
            self.last_decision = {
                "tier": "vlm",
                "reason": (
                    f"{yolo_reason}; escalated to VLM "
                    f"({self._vlm_gate_reason(vlm_result.diagnostics, passed=True)})"
                ),
            }
            return vlm_result

        vlm_reason = (
            self._vlm_gate_reason(vlm_result.diagnostics, passed=False)
            if vlm_result is not None
            else "VLM unavailable or failed"
        )

        saliency_result = self._safe_locate(self._saliency, rgb, "saliency")
        if saliency_result is None:
            # Defensive only: SaliencySubjectLocator is designed to never fail.
            saliency_result = LocatorResult(subject=Subject.from_saliency((0.5, 0.5)))
        self.last_decision = {
            "tier": "saliency",
            "reason": f"{yolo_reason}; {vlm_reason}; used saliency fallback",
        }
        return saliency_result

    def _passes_yolo_gate(self, diagnostics: dict[str, Any]) -> bool:
        top = float(diagnostics.get("top_confidence", 0.0))
        second = float(diagnostics.get("second_confidence", 0.0))
        if top < self._YOLO_ABS_FLOOR:
            return False
        if top >= self._YOLO_HIGH_CONF_SHORTCUT:
            return True
        if second <= 0.0:
            return True
        return top > self._YOLO_RATIO_THRESHOLD * second

    def _yolo_gate_reason(self, diagnostics: dict[str, Any], *, passed: bool) -> str:
        top = float(diagnostics.get("top_confidence", 0.0))
        second = float(diagnostics.get("second_confidence", 0.0))
        ratio_str = f"{(top / second):.1f}x" if second > 0 else "inf"
        if passed:
            if top >= self._YOLO_HIGH_CONF_SHORTCUT:
                return (
                    f"YOLO-World top confidence {top:.3f} cleared high-confidence "
                    f"shortcut (>={self._YOLO_HIGH_CONF_SHORTCUT})"
                )
            return (
                f"YOLO-World confidence ratio {ratio_str} (top={top:.3f}, "
                f"2nd={second:.3f}) cleared {self._YOLO_RATIO_THRESHOLD}x threshold "
                f"and {self._YOLO_ABS_FLOOR} floor"
            )
        if top < self._YOLO_ABS_FLOOR:
            return (
                f"YOLO-World top confidence {top:.3f} below absolute floor "
                f"{self._YOLO_ABS_FLOOR}"
            )
        return (
            f"YOLO-World confidence ratio {ratio_str} below "
            f"{self._YOLO_RATIO_THRESHOLD}x threshold (top={top:.3f}, 2nd={second:.3f})"
        )

    def _passes_vlm_gate(self, diagnostics: dict[str, Any]) -> bool:
        confidence = float(diagnostics.get("vlm_confidence", 0.0))
        return confidence >= self._VLM_CONF_FLOOR

    def _vlm_gate_reason(self, diagnostics: dict[str, Any], *, passed: bool) -> str:
        confidence = float(diagnostics.get("vlm_confidence", 0.0))
        comparator = ">=" if passed else "<"
        return f"VLM confidence {confidence:.3f} {comparator} {self._VLM_CONF_FLOOR} floor"

    @staticmethod
    def _safe_locate(
        locator: SubjectLocator, rgb: np.ndarray, name: str
    ) -> LocatorResult | None:
        try:
            return locator.locate(rgb)
        except Exception as exc:  # noqa: BLE001 - a locator must never crash the pipeline
            logger.warning(
                "%s locator raised unexpectedly (%s: %s); skipping.",
                name,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return None


_composite = CompositeSubjectLocator()


def locate_subject(rgb: np.ndarray) -> Subject:
    """Locate the subject in an RGB image via the tiered locator chain.

    Always returns a Subject: YOLO-World (if it clears the relative-confidence
    gate) -> VLM (if configured and confident enough) -> saliency centroid
    (always succeeds).
    """
    return _composite.locate(np.asarray(rgb)).subject


def locate_subject_with_diagnostics(rgb: np.ndarray) -> tuple[Subject, dict[str, Any]]:
    """Like ``locate_subject``, but also returns which tier fired and why.

    Intended for debugging/smoke-testing (see scripts/smoke_test_subject.py);
    the production pipeline only needs ``locate_subject``.
    """
    result = _composite.locate(np.asarray(rgb))
    return result.subject, dict(_composite.last_decision)
