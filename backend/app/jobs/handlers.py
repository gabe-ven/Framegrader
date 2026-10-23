"""What each job kind actually does.

Handlers are idempotent, because the queue is at-least-once: a job whose
worker died is requeued and run again from the top. Re-running ``analyze``
after measurements were already saved skips straight to what is missing
(the original upload is deleted once measured, so it *has* to).
"""

from __future__ import annotations

import io
import logging
from typing import Any

from PIL import Image
from sqlalchemy import Engine

from app.core.config import Settings
from app.core.observability import stage
from app.db import repository as repo
from app.jobs.progress import ProgressTracker
from app.services import analysis_service, image_io
from app.services.ai import color_grading, photo_critique

logger = logging.getLogger(__name__)

THUMB_MAX_EDGE = 480


class JobFailed(Exception):
    """A failure the user should see verbatim, and that retrying cannot fix."""


def _load_stored_image(engine: Engine, analysis_id: str) -> Image.Image:
    blob = repo.get_blob(engine, analysis_id, "image")
    if blob is None:
        raise JobFailed("The stored photo for this analysis is missing.")
    image = Image.open(io.BytesIO(blob["data"]))
    image.load()
    return image


def run_analyze(
    engine: Engine, job: dict[str, Any], tracker: ProgressTracker, settings: Settings
) -> None:
    analysis_id = job["analysis_id"]
    analysis = repo.get_analysis(engine, analysis_id)
    if analysis is None:
        raise JobFailed("This analysis was deleted.")
    repo.update_analysis(engine, analysis_id, status="running", error=None)

    measurements = analysis["measurements"]
    if measurements is None:
        original = repo.get_blob(engine, analysis_id, "original")
        if original is None:
            raise JobFailed("The uploaded photo is no longer available. Please upload it again.")
        try:
            response, image = analysis_service.measure(
                original["data"],
                filename=analysis["filename"],
                content_type=original["content_type"],
                settings=settings,
                on_stage=tracker.start,
            )
        except image_io.ImageValidationError as exc:
            raise JobFailed(str(exc)) from exc

        with stage("store_images"):
            data, size = image_io.encode_jpeg(image, settings.stored_image_max_edge)
            repo.put_blob(engine, analysis_id, "image", data, "image/jpeg", size)
            thumb, thumb_size = image_io.encode_jpeg(image, THUMB_MAX_EDGE, quality=80)
            repo.put_blob(engine, analysis_id, "thumb", thumb, "image/jpeg", thumb_size)

        measurements = response.model_dump(mode="json")
        # Written before the critique starts, so a client can render the
        # measurements ~2s in rather than waiting ~20s for everything.
        repo.update_analysis(engine, analysis_id, measurements=measurements)
        # The original is only needed to measure (MakerNotes, full-res EXIF).
        # Holding a 25MB upload any longer is cost and liability for nothing.
        repo.delete_blob(engine, analysis_id, "original")
    else:
        image = _load_stored_image(engine, analysis_id)

    if analysis["ai"] is None:
        tracker.start("critique")
        with stage("critique"):
            if settings.ai_analysis_paused:
                critique = photo_critique.placeholder_critique()
            else:
                critique = photo_critique.generate_critique(image, measurements)
        ai = analysis_service.coerce_ai(critique)
        repo.update_analysis(engine, analysis_id, ai=ai.model_dump(mode="json"))

    repo.update_analysis(engine, analysis_id, status="succeeded")


def run_color_grade(
    engine: Engine, job: dict[str, Any], tracker: ProgressTracker, settings: Settings
) -> None:
    analysis_id = job["analysis_id"]
    analysis = repo.get_analysis(engine, analysis_id)
    if analysis is None:
        raise JobFailed("This analysis was deleted.")
    if analysis["color_grade"] is not None:
        return  # already graded by an earlier attempt

    tracker.start("grade")
    image = _load_stored_image(engine, analysis_id)
    context: dict[str, Any] = dict(analysis["measurements"] or {})
    context["scene_summary"] = ((analysis["ai"] or {}).get("scene") or {}).get("summary")
    with stage("grade"):
        result = color_grading.generate_color_grade(image, context)
    grade = analysis_service.coerce_color_grade(result)
    repo.update_analysis(engine, analysis_id, color_grade=grade.model_dump(mode="json"))


HANDLERS = {
    "analyze": run_analyze,
    "color_grade": run_color_grade,
}
