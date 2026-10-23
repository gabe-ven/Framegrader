"""Request IDs, stage timings, and structured log output."""

from __future__ import annotations

import io
import json
import logging

from fastapi.testclient import TestClient
from PIL import Image

from app.core.logging import ContextFilter, JsonFormatter, TextFormatter
from app.core.observability import bind, stage, timing_scope
from app.main import app

client = TestClient(app)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()


def test_every_response_carries_a_request_id() -> None:
    res = client.get("/health")
    assert len(res.headers["x-request-id"]) == 32


def test_a_well_formed_caller_request_id_is_propagated() -> None:
    res = client.get("/health", headers={"X-Request-ID": "trace-abc.123"})
    assert res.headers["x-request-id"] == "trace-abc.123"


def test_a_malformed_caller_request_id_is_replaced() -> None:
    # Echoed into headers and logs, so anything unusual is a forging vector.
    res = client.get("/health", headers={"X-Request-ID": "x" * 500})
    assert res.headers["x-request-id"] != "x" * 500


def test_sync_analyze_reports_per_stage_server_timing() -> None:
    res = client.post("/api/analyze", files={"file": ("t.png", _png(), "image/png")})
    assert res.status_code == 200
    timing = res.headers["server-timing"]
    for name in ("decode", "metadata", "vision", "subject", "composition"):
        assert f"{name};dur=" in timing


def test_request_summary_line_has_status_duration_and_stages(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        client.post("/api/analyze", files={"file": ("t.png", _png(), "image/png")})
    summary = [r for r in caplog.records if getattr(r, "event", None) == "request"][-1]
    assert summary.status == 200 and summary.path == "/api/analyze"
    assert summary.duration_ms > 0
    assert "vision" in summary.stages


def test_stage_records_into_the_active_bucket_and_reraises() -> None:
    with timing_scope() as bucket:
        with stage("ok"):
            pass
        try:
            with stage("boom"):
                raise ValueError
        except ValueError:
            pass
    assert [name for name, _ in bucket] == ["ok", "boom"]


def _record(msg: str = "hello", **extra) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, msg, None, None)
    for k, v in extra.items():
        setattr(record, k, v)
    ContextFilter().filter(record)
    return record


def test_json_lines_carry_bound_ids_and_extra_fields() -> None:
    with bind(request_id="req-1", job_id="job-1", analysis_id="an-1"):
        line = JsonFormatter().format(_record(duration_ms=12.5, stage="vision"))
    payload = json.loads(line)
    assert payload["msg"] == "hello" and payload["level"] == "INFO"
    assert payload["request_id"] == "req-1"
    assert payload["job_id"] == "job-1"
    assert payload["analysis_id"] == "an-1"
    assert payload["duration_ms"] == 12.5 and payload["stage"] == "vision"


def test_json_formatter_never_raises_on_odd_extra_values() -> None:
    from pathlib import Path

    payload = json.loads(JsonFormatter().format(_record(path_obj=Path("/x"))))
    assert payload["path_obj"]


def test_text_lines_append_fields_as_key_value_pairs() -> None:
    with bind(request_id="req-9"):
        line = TextFormatter().format(_record(duration_ms=3.0))
    assert "request_id=req-9" in line and "duration_ms=3.0" in line
