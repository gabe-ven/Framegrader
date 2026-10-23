"""The queued analysis flow: submit -> job -> snapshot / SSE, plus sharing,
history, color grade, and the queue's failure recovery.

Jobs are run synchronously with Worker.drain() so every test controls exactly
when work happens. The AI layer is stubbed: these tests are about the queue
and the API contract, not about Claude.
"""

from __future__ import annotations

import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db import repository as repo
from app.db.engine import get_engine
from app.jobs.progress import ProgressTracker
from app.jobs.worker import Worker
from app.main import app
from app.services.ai import color_grading, photo_critique

client = TestClient(app)
OWNER = {"X-Client-Id": "0f8fad5b-d9cb-469f-a165-70867728950e"}
STRANGER = {"X-Client-Id": "7c9e6679-7425-40de-944b-e07fc1f90ae7"}


def _jpeg(size=(640, 480)) -> bytes:
    image = Image.new("RGB", size, (90, 140, 200))
    # A bright band so the pipeline has some structure to measure.
    image.paste((240, 240, 240), (0, size[1] // 2, size[0], size[1] // 2 + 20))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def _submit(headers=OWNER, data: bytes | None = None) -> dict:
    res = client.post(
        "/api/analyses",
        files={"file": ("photo.jpg", data or _jpeg(), "image/jpeg")},
        headers=headers,
    )
    assert res.status_code == 202, res.text
    return res.json()


def run_jobs() -> int:
    return Worker().drain()


GOOD_CRITIQUE = {
    "available": True,
    "scene": {"summary": "A blue test card.", "tags": ["test"]},
    "camera_settings": {"iso": 640},  # a bare number: must not break validation
    "composition_critique": {"strengths": ["a"], "improvements": ["b"], "overall": "ok"},
}


@pytest.fixture
def stub_ai(monkeypatch):
    calls = {"critique": 0, "grade": 0}

    def critique(image, context=None):
        calls["critique"] += 1
        assert context and "composition" in context  # grounded in measurements
        return dict(GOOD_CRITIQUE)

    def grade(image, context=None):
        calls["grade"] += 1
        return {"available": True, "adjustments": {"exposure": 0.3}, "style": "natural"}

    monkeypatch.setattr(photo_critique, "generate_critique", critique)
    monkeypatch.setattr(color_grading, "generate_color_grade", grade)
    return calls


# --- submit + run -----------------------------------------------------------


def test_submit_returns_202_with_a_queued_stage_plan(stub_ai) -> None:
    body = _submit()
    assert body["job"]["status"] == "queued"
    assert [s["name"] for s in body["job"]["stages"]][0] == "decode"
    assert body["client_id"] is None  # caller supplied one

    snap = client.get(f"/api/analyses/{body['id']}", headers=OWNER).json()
    assert snap["status"] == "queued"
    assert snap["measurements"] is None
    assert snap["jobs"]["analyze"]["queue_position"] == 0


def test_submit_without_client_id_mints_one() -> None:
    res = client.post("/api/analyses", files={"file": ("p.jpg", _jpeg(), "image/jpeg")})
    minted = res.json()["client_id"]
    assert minted
    assert client.get(f"/api/analyses/{res.json()['id']}", headers={"X-Client-Id": minted}).status_code == 200


def test_bad_upload_is_rejected_before_queueing() -> None:
    res = client.post(
        "/api/analyses", files={"file": ("x.jpg", b"not an image", "image/jpeg")}, headers=OWNER
    )
    assert res.status_code == 422
    assert repo.queue_depth(get_engine()) == 0


def test_job_fills_in_measurements_critique_and_stage_timings(stub_ai) -> None:
    analysis_id = _submit()["id"]
    assert run_jobs() == 1

    snap = client.get(f"/api/analyses/{analysis_id}", headers=OWNER).json()
    assert snap["status"] == "succeeded"
    assert snap["measurements"]["image"]["width"] == 640
    assert snap["ai"]["available"] is True
    assert snap["ai"]["camera_settings"]["iso"] == "640"

    job = snap["jobs"]["analyze"]
    assert job["status"] == "succeeded" and job["progress"] == 1.0
    by_name = {s["name"]: s for s in job["stages"]}
    for name in ("decode", "metadata", "vision", "subject", "composition", "critique"):
        assert by_name[name]["status"] == "done", name
        assert by_name[name]["duration_ms"] is not None
    # The upload itself is not retained once measured.
    assert repo.get_blob(get_engine(), analysis_id, "original") is None


def test_unparseable_critique_shape_degrades_instead_of_failing(monkeypatch) -> None:
    monkeypatch.setattr(
        photo_critique, "generate_critique",
        lambda image, context=None: {"available": True, "recreation_guide": "not a list"},
    )
    analysis_id = _submit()["id"]
    run_jobs()
    snap = client.get(f"/api/analyses/{analysis_id}", headers=OWNER).json()
    assert snap["status"] == "succeeded"
    assert snap["measurements"] is not None
    assert snap["ai"]["available"] is False


def test_paused_ai_serves_the_placeholder_without_calling_claude(monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("AI_ANALYSIS_PAUSED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(photo_critique, "generate_critique", lambda *a, **k: pytest.fail("called"))
    analysis_id = _submit()["id"]
    run_jobs()
    snap = client.get(f"/api/analyses/{analysis_id}", headers=OWNER).json()
    assert "paused" in snap["ai"]["scene"]["summary"]


def test_a_photo_that_fails_to_decode_fails_the_analysis_with_its_reason(stub_ai, monkeypatch) -> None:
    from app.services import image_io

    analysis_id = _submit()["id"]

    def boom(*_a, **_k):
        raise image_io.ImageValidationError("Image resolution is too large to analyze.")

    monkeypatch.setattr(image_io, "open_image", boom)
    run_jobs()
    snap = client.get(f"/api/analyses/{analysis_id}", headers=OWNER).json()
    assert snap["status"] == "failed"
    assert snap["error"] == "Image resolution is too large to analyze."
    assert {s["status"] for s in snap["jobs"]["analyze"]["stages"]} >= {"failed"}


# --- access control, sharing, history ---------------------------------------


def test_private_analysis_is_invisible_to_others(stub_ai) -> None:
    analysis_id = _submit()["id"]
    run_jobs()
    assert client.get(f"/api/analyses/{analysis_id}", headers=STRANGER).status_code == 404
    assert client.get(f"/api/analyses/{analysis_id}").status_code == 404
    assert client.get(f"/api/analyses/{analysis_id}/image").status_code == 404


def test_signed_image_url_works_for_the_owner_only_until_shared(stub_ai) -> None:
    analysis_id = _submit()["id"]
    run_jobs()
    snap = client.get(f"/api/analyses/{analysis_id}", headers=OWNER).json()
    assert "sig=" in snap["image_url"]
    img = client.get(snap["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert img.headers["cache-control"].startswith("private")
    # Tampered signature
    assert client.get(snap["image_url"][:-2] + "00").status_code == 404


def test_sharing_exposes_the_result_without_gps(stub_ai) -> None:
    analysis_id = _submit()["id"]
    run_jobs()
    # Simulate a photo with GPS in its EXIF.
    row = repo.get_analysis(get_engine(), analysis_id)
    m = row["measurements"]
    m["exif"]["gps"] = {"latitude": 37.8, "longitude": -122.4}
    repo.update_analysis(get_engine(), analysis_id, measurements=m)

    assert client.put(
        f"/api/analyses/{analysis_id}/visibility", json={"public": True}, headers=STRANGER
    ).status_code == 404
    res = client.put(f"/api/analyses/{analysis_id}/visibility", json={"public": True}, headers=OWNER)
    assert res.json()["is_public"] is True

    public = client.get(f"/api/analyses/{analysis_id}").json()
    assert public["is_owner"] is False
    assert public["measurements"]["exif"]["gps"] is None
    assert public["image_url"] == f"/api/analyses/{analysis_id}/image"
    assert client.get(public["image_url"]).status_code == 200
    # The owner still sees their own GPS.
    owner = client.get(f"/api/analyses/{analysis_id}", headers=OWNER).json()
    assert owner["measurements"]["exif"]["gps"]["latitude"] == 37.8


def test_history_lists_only_the_callers_analyses_newest_first(stub_ai) -> None:
    first = _submit()["id"]
    time.sleep(0.01)
    second = _submit()["id"]
    _submit(headers=STRANGER)
    run_jobs()

    page = client.get("/api/analyses", headers=OWNER).json()
    assert [i["id"] for i in page["items"]] == [second, first]
    assert page["items"][0]["scene_summary"] == "A blue test card."
    assert page["items"][0]["thumb_url"]
    assert client.get("/api/analyses").json()["items"] == []

    paged = client.get("/api/analyses?limit=1", headers=OWNER).json()
    assert len(paged["items"]) == 1 and paged["next_before"] is not None
    rest = client.get(f"/api/analyses?limit=1&before={paged['next_before']}", headers=OWNER).json()
    assert [i["id"] for i in rest["items"]] == [first]


def test_owner_can_delete(stub_ai) -> None:
    analysis_id = _submit()["id"]
    run_jobs()
    assert client.delete(f"/api/analyses/{analysis_id}", headers=STRANGER).status_code == 404
    assert client.delete(f"/api/analyses/{analysis_id}", headers=OWNER).status_code == 204
    assert client.get(f"/api/analyses/{analysis_id}", headers=OWNER).status_code == 404
    assert repo.get_blob(get_engine(), analysis_id, "image") is None


# --- color grade ------------------------------------------------------------


def test_color_grade_job_is_deduplicated_and_cached(stub_ai) -> None:
    analysis_id = _submit()["id"]
    assert client.post(f"/api/analyses/{analysis_id}/color-grade", headers=OWNER).status_code == 409
    run_jobs()

    first = client.post(f"/api/analyses/{analysis_id}/color-grade", headers=OWNER)
    second = client.post(f"/api/analyses/{analysis_id}/color-grade", headers=OWNER)
    assert first.status_code == 202 and first.json()["id"] == second.json()["id"]
    run_jobs()
    snap = client.get(f"/api/analyses/{analysis_id}", headers=OWNER).json()
    assert snap["color_grade"]["adjustments"]["exposure"] == 0.3
    assert snap["jobs"]["color_grade"]["status"] == "succeeded"
    # Asking again returns the finished job instead of paying for another call.
    client.post(f"/api/analyses/{analysis_id}/color-grade", headers=OWNER)
    run_jobs()
    assert stub_ai["grade"] == 1


# --- SSE --------------------------------------------------------------------


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = [l for l in block.splitlines() if not l.startswith(":")]
        if not lines:
            continue
        event = next(l[7:] for l in lines if l.startswith("event: "))
        data = json.loads(next(l[6:] for l in lines if l.startswith("data: ")))
        events.append((event, data))
    return events


def test_event_stream_sends_the_current_snapshot_then_ends_when_settled(stub_ai) -> None:
    analysis_id = _submit()["id"]
    run_jobs()
    with client.stream("GET", f"/api/analyses/{analysis_id}/events", headers=OWNER) as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(res.read().decode())
    assert events[0][0] == "snapshot" and events[0][1]["status"] == "succeeded"
    assert events[-1][0] == "end"


def test_event_stream_respects_access_control(stub_ai) -> None:
    analysis_id = _submit()["id"]
    assert client.get(f"/api/analyses/{analysis_id}/events", headers=STRANGER).status_code == 404


# --- queue mechanics --------------------------------------------------------


def test_a_job_can_only_be_claimed_once(stub_ai) -> None:
    _submit()
    engine = get_engine()
    assert repo.claim_job(engine, "w1") is not None
    assert repo.claim_job(engine, "w2") is None


def test_stale_jobs_are_requeued_then_failed_when_out_of_attempts(stub_ai) -> None:
    analysis_id = _submit()["id"]
    engine = get_engine()
    from sqlalchemy import update
    from app.db.schema import jobs

    def claim_and_abandon():
        job = repo.claim_job(engine, "dead-worker")
        with engine.begin() as conn:
            conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(heartbeat_at=0.0))
        return job

    claim_and_abandon()
    requeued, failed = repo.requeue_stale(engine, stale_seconds=60)
    assert len(requeued) == 1 and not failed

    claim_and_abandon()  # attempt 2 of 2
    requeued, failed = repo.requeue_stale(engine, stale_seconds=60)
    assert not requeued and len(failed) == 1
    snap = client.get(f"/api/analyses/{analysis_id}", headers=OWNER).json()
    assert snap["status"] == "failed"


def test_a_retried_job_does_not_remeasure_or_recritique(stub_ai) -> None:
    analysis_id = _submit()["id"]
    run_jobs()
    engine = get_engine()
    # Re-run the same analysis as if the worker had died after finishing.
    repo.enqueue_job(
        engine, analysis_id, "analyze", stages=[], request_id=None, max_attempts=2
    )
    run_jobs()
    assert stub_ai["critique"] == 1
    assert repo.get_analysis(engine, analysis_id)["status"] == "succeeded"


def test_retention_purges_old_analyses(stub_ai, monkeypatch) -> None:
    analysis_id = _submit()["id"]
    run_jobs()
    engine = get_engine()
    repo.update_analysis(engine, analysis_id)
    from sqlalchemy import update
    from app.db.schema import analyses

    with engine.begin() as conn:
        conn.execute(update(analyses).values(created_at=time.time() - 40 * 86400))
    Worker().maintain()
    assert repo.get_analysis(engine, analysis_id) is None


def test_progress_is_weighted_and_marks_skipped_stages() -> None:
    seen = []
    tracker = ProgressTracker("analyze", lambda stage, p, stages: seen.append((stage, p)))
    tracker.start("decode")
    tracker.start("critique")  # metadata..scoring skipped (e.g. a resumed job)
    stages = tracker.finish()
    status = {s["name"]: s["status"] for s in stages}
    assert status["decode"] == "done" and status["critique"] == "done"
    assert status["vision"] == "skipped"
    # Entering the critique means everything before it is accounted for: the
    # bar sits at the critique's start, not at 2/7.
    assert seen[-1] == ("critique", pytest.approx(0.28, abs=0.01))
