# Architecture

```
Browser (React SPA, react-router)
  │  POST /api/analyses (photo) ── 202 {id}
  │  GET  /api/analyses/{id}/events  (SSE; polling fallback)
  ▼
FastAPI (uvicorn, one process)
  ├─ RequestContextMiddleware   request IDs, Server-Timing, access log
  ├─ routes/analyses.py         queued flow: submit, snapshot, SSE, share, history
  ├─ routes/analysis.py         original synchronous endpoints (scripts, eval)
  └─ embedded job workers       claim → run → record (app/jobs)
        │
        ▼
SQL database (SQLite by default, Postgres in production)
  analyses │ jobs (the queue) │ blobs (stored photo copies)
```

## Request flow

1. **Submit.** `POST /api/analyses` validates the upload (size, type, an
   integrity probe that decodes nothing) and, in one transaction, inserts the
   analysis row, the original upload, and an `analyze` job. It answers `202` in
   milliseconds. A bad file still gets an immediate `422`.
2. **Work.** A worker claims the job and runs the stages
   `decode → metadata → vision → subject → composition → scoring → critique`,
   persisting progress at every boundary. Measurements are written as soon as
   they exist (~2 s in). The original upload is deleted once measured; a
   2048 px copy without EXIF (so no GPS) and a 480 px thumbnail are kept.
3. **Watch.** The client follows `GET /api/analyses/{id}/events`, a Server-Sent
   Events stream that pushes a full snapshot whenever the row's `version`
   changes and ends once everything has settled. If the stream can't be opened
   or drops, the client polls `GET /api/analyses/{id}`, which returns the same
   snapshot shape.
4. **Later.** `POST /api/analyses/{id}/color-grade` queues a second job kind
   against the stored copy. It is idempotent: an in-flight or finished grade is
   returned instead of paying for another Claude call.

## Background jobs: why a SQL-backed queue

The slow work — the Claude critique (~16 s) and the colour grade (~10 s) — runs
in a job queue whose storage is a table in the app's own database. On Postgres
workers claim jobs with `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)`;
on SQLite the same statement is safe because SQLite serialises writers and the
claim re-checks `status = 'queued'`.

Options considered:

| | RQ | Celery | arq | **SQL table (chosen)** |
|---|---|---|---|---|
| Extra infrastructure | Redis | Redis/RabbitMQ (+ result backend) | Redis | none — the DB we need anyway |
| Separate worker process required | yes | yes | yes | no (embedded), optional |
| Fits a 512 MB free instance | no: 2nd service | no | no | yes |
| Windows dev | no (`fork`) | yes | yes | yes |
| Enqueue atomic with the analysis row | no (dual write) | no | no | **yes** |
| Progress / result storage | bolt-on | result backend | Redis keys | the same row |
| Throughput ceiling | high | high | high | ~hundreds of jobs/s on Postgres |

The deciding factors:

- **History and share links need a database regardless.** With the queue in
  that same database there is one thing to run, back up and reason about, and
  creating an analysis and its job is one transaction — there is no window in
  which a job references an analysis that doesn't exist, or an analysis waits
  forever for a job that was never enqueued.
- **The free deployment is a single 512 MB process.** Render's free tier has no
  background workers, and a broker plus a worker process would roughly double
  baseline memory. Embedded workers (`EMBEDDED_WORKERS`, default 1) run inside
  the API process; the same code runs standalone (`python -m app.worker`) when
  the API and workers should scale separately.
- **The load is tiny.** Every analysis is rate-limited (10/hour/IP) and spends
  its time waiting on Claude. A table queue on Postgres comfortably handles
  orders of magnitude more than that.
- **Celery** brings the most machinery (broker, result backend, beat, ~80 MB per
  worker) for features this doesn't need. **RQ** forks per job, which doesn't
  work on Windows and copies torch's address space on Linux. **arq** is
  asyncio-native, but every task here is synchronous CPU work or a blocking SDK
  call, so it would just run them in threads anyway.

When this stops being the right choice: sustained thousands of jobs per second,
or fan-out across many queues with priorities and schedules. Neither is on the
horizon.

**Delivery semantics: at-least-once.** Workers heartbeat with every progress
update; a job whose heartbeat is older than `JOB_STALE_SECONDS` (worker
OOM-killed, instance redeployed) is requeued until `JOB_MAX_ATTEMPTS`, then
failed. Handlers are idempotent — a rerun skips whatever is already stored —
so a retry never double-charges a Claude call that already succeeded.

## Progress

Progress is stage-based. The plan (`app/jobs/progress.py`) gives each stage a
weight equal to its typical share of wall-clock time, so the bar tracks time
rather than stage count (the critique alone is ~70% of an analysis). The bar
moves only when the worker crosses a stage boundary; each finished stage
carries its measured duration, and the UI's only local computation is how long
the current stage has been running. Nothing advances on a timer.

## Ownership, history and sharing (no accounts)

The browser keeps a random UUID in `localStorage` and sends it as `X-Client-Id`.
The server stores only its SHA-256 as the analysis owner. The owner can read a
private analysis, list their history, share, and delete. Anyone can read an
analysis its owner made public at `/r/:id`; non-owners never see GPS
coordinates. IDs are 128-bit random tokens, so unshared results aren't
enumerable.

`<img>` tags can't send headers, so image URLs in a snapshot carry a short-lived
HMAC signature (`SECRET_KEY`); public analyses get plain cacheable URLs.

Analyses older than `RETENTION_DAYS` (default 30) are purged by the worker's
maintenance loop.

## Observability

- **Request IDs.** `RequestContextMiddleware` (pure ASGI, so it doesn't buffer
  the SSE stream) accepts a well-formed `X-Request-ID` or mints one, echoes it on
  the response, and binds it in a context variable that every log record picks
  up. Jobs store the enqueuing request's ID and re-bind it, so one ID finds the
  request *and* the background work it caused; job lines also carry `job_id` and
  `analysis_id`.
- **Per-stage timings.** `observability.stage(name)` times a block, logs it, and
  adds it to the current bucket. For requests the bucket becomes a
  `Server-Timing` header and a field on the access line; for jobs it is logged
  on completion and the per-stage durations are stored on the job row.
- **Format.** `LOG_FORMAT=json` writes one JSON object per line for log
  collectors; `text` (default) is human-readable with the same fields appended.

## Frontend routes

| Path | Screen |
|---|---|
| `/` | choose and preview a photo |
| `/r/:id` | live progress, then the report; also the public share link |
| `/r/:id/edit` | the editor (full-resolution original if this tab uploaded it, else the stored copy) |
| `/history` | this browser's analyses |

State lives on the server, so back/forward, refresh and shared links all show
the same page. Routes past `/` are lazy-loaded, keeping the chart and 3D
libraries out of the landing page bundle.

## Scoring

- **Composition score** (`app/services/scoring/composition_score.py`): a ridge
  regression from the composition features onto expert composition ratings,
  fitted on CADB's train split and reported on its test split
  (`eval/results/RESULTS.md`). The coefficients ship as `calibration.json`. The
  previous hand-weighted average is kept as the fallback and is reported
  alongside for comparison.
- **Aesthetic score** (`app/services/scoring/aesthetic.py`): a learned model
  served through ONNX Runtime, chosen by the benchmark on correlation *and*
  memory/latency. Optional: without the model file the composition score uses
  its geometry-only calibrated model.

## Database

There is no migration framework yet: `metadata.create_all` creates missing
tables at startup. The first schema change that must preserve existing rows is
the point to introduce Alembic.
