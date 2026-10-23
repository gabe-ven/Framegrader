"""Table definitions (SQLAlchemy Core — no ORM).

Three tables, and the job queue is one of them. That is the point of the
design: an analysis row, its stored images, and the job that fills it in are
written in one transaction, so there is no window where a job exists for an
analysis that doesn't (or vice versa) — the dual-write problem a separate
Redis queue would introduce. See docs/architecture.md, "Background jobs".

Portable across SQLite and Postgres: timestamps are epoch-seconds floats
(SQLite has no timezone-aware type, and floats compare and index the same
everywhere), JSON becomes JSONB on Postgres, and blobs become BYTEA.

There is no migration framework yet; `create_all` builds missing tables at
startup. The first schema change that has to preserve existing rows is the
moment to add Alembic.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

_Json = JSON().with_variant(JSONB(), "postgresql")

analyses = Table(
    "analyses",
    metadata,
    # 128-bit URL-safe random token. It is also the public share-link ID, so it
    # must be unguessable: sequential IDs would make every "unlisted" result
    # enumerable.
    Column("id", String(32), primary_key=True),
    # sha256 of the browser's X-Client-Id. Never the raw ID: a database leak
    # should not hand out the bearer tokens that grant owner access.
    Column("owner_hash", String(64), nullable=True),
    Column("filename", String(255), nullable=False),
    # queued | running | succeeded | failed — the analysis as a whole. Each
    # job additionally carries its own status.
    Column("status", String(16), nullable=False),
    Column("is_public", Boolean, nullable=False, default=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    # Bumped on every write. The SSE stream compares it to decide whether to
    # push an update, so a progress tick costs one integer read when nothing
    # changed.
    Column("version", Integer, nullable=False, default=1),
    Column("measurements", _Json, nullable=True),  # AnalysisResponse
    Column("ai", _Json, nullable=True),  # AIAnalysis
    Column("color_grade", _Json, nullable=True),  # ColorGradeResponse
    Column("error", Text, nullable=True),
)
Index("ix_analyses_owner_created", analyses.c.owner_hash, analyses.c.created_at)
Index("ix_analyses_created", analyses.c.created_at)

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "analysis_id",
        String(32),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", String(32), nullable=False),  # analyze | color_grade
    Column("status", String(16), nullable=False),  # queued|running|succeeded|failed
    Column("stage", String(32), nullable=True),  # name of the stage now running
    Column("progress", Float, nullable=False, default=0.0),  # 0..1, weighted
    # [{name, label, status, duration_ms}] — the full plan, so the client can
    # draw upcoming stages before they start.
    Column("stages", _Json, nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=2),
    Column("error", Text, nullable=True),
    # The request that enqueued the job, re-bound in the worker so the job's
    # log lines share its request_id.
    Column("request_id", String(128), nullable=True),
    Column("worker_id", String(64), nullable=True),
    Column("created_at", Float, nullable=False),
    Column("started_at", Float, nullable=True),
    Column("heartbeat_at", Float, nullable=True),
    Column("finished_at", Float, nullable=True),
)
# The claim query's access path: oldest queued job first.
Index("ix_jobs_status_created", jobs.c.status, jobs.c.created_at)
Index("ix_jobs_analysis", jobs.c.analysis_id)

blobs = Table(
    "blobs",
    metadata,
    Column(
        "analysis_id",
        String(32),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # original (the upload, deleted once measured) | image | thumb
    Column("kind", String(16), primary_key=True),
    Column("content_type", String(64), nullable=False),
    Column("data", LargeBinary, nullable=False),
    Column("width", Integer, nullable=True),
    Column("height", Integer, nullable=True),
    Column("created_at", Float, nullable=False),
)
