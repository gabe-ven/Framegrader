# Frame Grader

Upload a photograph, get a structured critique: composition metrics, lighting/vision
stats, EXIF, and improvement suggestions. The core of the composition analysis is a
**three-tier subject locator** — YOLO-World open-vocabulary detection first (fast,
free), a Claude vision-language model as escalation when the detector is unsure
(answers "what did the photographer point the camera at?" rather than "what objects
are present?"), and a gradient-saliency centroid as a guaranteed local fallback. The
located subject then feeds seven geometric composition metrics (rule of thirds,
subject position, leading lines, horizon, symmetry, edge density, negative space)
rendered as overlays and scores in the React frontend.

## Stack

| Layer           | Tech                                       |
| --------------- | ------------------------------------------ |
| Frontend        | React, TypeScript, Tailwind CSS, Vite      |
| Backend         | Python, FastAPI                            |
| Computer Vision | OpenCV, Pillow, scikit-image               |
| Subject/AI      | YOLO-World (ultralytics), Anthropic Claude |

## Setup & run

```bash
# Backend (Python 3.13)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock   # pinned transitively — see note below
cp .env.example .env               # set ANTHROPIC_API_KEY to enable the VLM tier
uvicorn app.main:app --reload      # http://localhost:8000

# Frontend
cd frontend
npm install
npm run dev                     # http://localhost:5173

# Tests
backend/.venv/bin/python -m pytest backend/tests/

# Eval harness (accuracy vs. your own judgment on real photos)
cp eval/ground_truth.example.json eval/ground_truth.json  # fill in judgments
# drop JPEGs into eval/photos/ (gitignored), then:
backend/.venv/bin/python eval/run_eval.py
```

Notes: YOLO-World weights (~25 MB) auto-download on first use, and both the model
and its predictor are warmed in a background thread at startup — so the first
analysis runs at normal speed rather than paying a cold-start penalty. Without
`ANTHROPIC_API_KEY` the VLM tier is silently skipped.

**Install from `requirements.lock`, not `requirements.txt`.** The former pins every
transitive dependency; the latter pins only direct ones and re-resolves the rest on
each install. That difference is not theoretical: `ultralytics` declares an unpinned
dependency on `opencv-python`, which shares its `cv2` module directory with our
pinned `opencv-python-headless`, so the effective OpenCV version was whichever pip
wrote last. CI resolved OpenCV 5.0 the day it shipped while dev machines stayed on
4.x, and `LineSegmentDetector` changed its return shape between those majors —
green locally, ten failures in CI. Both OpenCV pins must move together.

Regenerate the lock after changing `requirements.txt`:

```bash
pip install -r requirements.txt
pip freeze | grep -viE '^(pytest|pluggy|iniconfig)==' > requirements.lock
```

## Deployment

The two halves deploy to different places, because they have different shapes:
the frontend is static files, the backend is a long-lived process holding a
~1.1 GB dependency tree and a loaded model in memory.

**The backend cannot run on serverless functions.** torch alone is 342 MB against
Vercel's 250 MB unzipped limit, and the full dependency set is ~9x over. Dropping
torch would mean dropping the YOLO-World tier — the core of the composition
analysis. Beyond size, the in-process rate limiter, the threadpool cap, and the
startup model warm-up all assume a process that stays alive between requests.

### Backend — any container host

Render, Railway, Fly.io and Cloud Run all build the `Dockerfile` directly:

```bash
docker build -t framegrader-api .
docker run -p 8000:8000 --env-file backend/.env framegrader-api
```

`render.yaml` is a ready Blueprint. Two settings in it are not optional — they are
the two ways this deploy fails:

- **Leave the Docker path settings at their defaults.** The `Dockerfile` lives at
  the repo root with the root as its build context, which is exactly what Render
  looks for. Pointing them at `backend/` instead produces
  "failed to read dockerfile: open Dockerfile: no such file or directory".
- **A Blueprint only configures services created *from* a Blueprint.** Adding
  `render.yaml` does nothing to a service you created by hand in the dashboard —
  it keeps using its own settings. Create the service via **New → Blueprint**, or
  set the equivalent values in the dashboard yourself.
- **Instance size.** The full build needs **≥ 2 GB** — measured ~1.4 GB resident
  once torch and the YOLO weights load. Render's free and starter plans are both
  512 MB, so it OOMs at startup. The **lite build fits free**: see below.

The container binds `$PORT` when the host provides one, falling back to 8000.

#### Lite build — fits a free 512 MB instance

```bash
docker build -t framegrader-api --build-arg REQUIREMENTS=requirements-lite.lock .
```

Drops torch, torchvision, ultralytics and CLIP. Measured against the full build:

| | Full | Lite |
| --- | --- | --- |
| Dependencies on disk | 1.1 GB | 348 MB |
| Idle RSS | ~1441 MB | ~88 MB |
| Peak RSS (3x 26 MP analyses) | ~1322 MB | ~292 MB |

Measured inside the actual container, the lite build is smaller still: **73 MiB
idle, 179 MiB peak** for one 26 MP analysis, against Render's 512 MiB cap.
Image size 815 MB.

Nothing is stubbed. The subject locator is a three-tier chain and only tier 1
needs torch: the import fails, the detector tier is skipped with a logged
warning, and requests escalate to the Claude VLM tier — which in practice labels
subjects *better* than YOLO did. What you give up:

- **`ANTHROPIC_API_KEY` becomes required** for subject localization. Without it
  the chain falls through to the saliency centroid, which has no box and no label.
- **One extra Claude call per `/analyze`**, so it is slower and costs more per photo.
- **No offline subject detection.**

`render.yaml` is already configured this way (`plan: free` + the build arg). To
deploy the full build instead, drop `dockerBuildArgs` and move to a 2 GB plan.

Peak memory is bounded by two settings, both on by default: `DECODE_MAX_EDGE`
asks libjpeg to decode JPEGs at a reduced scale (26 MP frame: 238 MB → 86 MB),
and `MAX_ANALYSIS_MEGAPIXELS` backstops formats without scaled decoding. Neither
costs accuracy — every metric already caps its own working resolution at 1920 px
— with one exception worth knowing: **sharpness reads ~16% lower** under scaled
decode, because libjpeg's DCT downscale is slightly softer than LANCZOS. It is
documented as a relative metric and the qualitative band is unchanged, but values
are not comparable across the two decode paths.

The image installs from the lock, bakes the detector weights in at build time, uses
CPU-only torch (the default CUDA wheels add ~2 GB for a GPU it will never see), and
runs as a non-root user with a `/health` healthcheck.

Two things to get right in front of it:

- **Set `FORWARDED_ALLOW_IPS` to your proxy's address.** Per-IP rate limiting reads
  `X-Forwarded-For`; uvicorn only trusts `127.0.0.1` by default, so behind a proxy
  every request otherwise shares one bucket and a single user throttles everyone.
  Do not set it to `*` on a directly-exposed container — a client could then spoof
  its address and evade the limit entirely.
- **Scale with replicas, not `--workers`.** The rate limiter's storage is in-process
  (N workers = N x the configured limit) and each worker loads its own copy of the
  model. Multiple replicas need a shared Redis backend for slowapi.

### Frontend — Vercel

`vercel.json` at the repo root builds `frontend/` to static files. No Root Directory
change is needed in the dashboard. Two environment variables tie the halves together,
and both must be set or the browser blocks every request:

| Where | Variable | Value |
| ----- | -------- | ----- |
| Vercel (frontend) | `VITE_API_BASE_URL` | the backend's public origin, e.g. `https://framegrader-api.onrender.com` |
| Backend host | `ALLOWED_ORIGINS` | the Vercel domain, e.g. `https://framegrader.vercel.app` |

`VITE_API_BASE_URL` is inlined at **build** time, not read at runtime — changing it
requires a redeploy, not just a restart. Leave it unset only when the SPA and API
share an origin behind one reverse proxy.

## Architecture

**Composition modules** (`backend/app/services/composition/`) — each measures one thing:

| Module                 | Measures                                                                  |
| ---------------------- | ------------------------------------------------------------------------- |
| `rule_of_thirds`       | Distance from subject centroid to nearest thirds power point              |
| `subject_position`     | Which 3×3 grid region the subject occupies, offset from center            |
| `leading_lines`        | Hough line segments, merged/deduped, with a spatial-spread gate           |
| `horizon_detection`    | Dominant horizontal edge row + tilt estimate                              |
| `symmetry`             | SSIM between each half and its mirror (vertical + horizontal axes)        |
| `edge_density`         | Canny edge fraction, overall and per region — a busyness proxy            |
| `negative_space`       | Low-gradient (flat) area share, raw and with the subject footprint excluded |

**Subject locator gating** (`CompositeSubjectLocator`):

1. **YOLO-World** runs first. Trusted if top confidence ≥ 0.5 (unambiguous), or if
   top confidence > 3× the second-best AND ≥ 0.10 absolute. The relative gate exists
   because open-vocab YOLO-World confidences are poorly calibrated — ranking is
   meaningful, absolute values often aren't.
2. **VLM (Claude)** runs if YOLO-World fails that gate. Trusted if its self-reported
   confidence ≥ 0.40; requires `ANTHROPIC_API_KEY`.
3. **Saliency centroid** (Sobel gradient center-of-mass) always succeeds as the
   final fallback.

## Known limitations

- The composition metrics are **geometric CV heuristics** (Sobel, Canny, Hough,
  SSIM) — not learned or perceptual models. They approximate photographic concepts
  without understanding semantics.
- Texture-heavy scenes can fool them: dense foliage can still occasionally register
  as false leading lines even after segment clustering and the spatial-spread gate;
  busy patterns inflate edge density; strong repeating structure can read as
  intentional symmetry.
- A low rule-of-thirds score isn't necessarily bad composition — centered symmetric
  shots break the rule by design. The overall score excludes non-applicable axes
  (no horizon, no lines) but is still a heuristic average, not a taste model.
- Accuracy against real photographer judgment is tracked with the harness in
  `eval/`, but the labeled set is small and personal — **not yet comprehensively
  validated**. Treat scores as conversation starters, not verdicts.

## Repository layout

```
ai-photography/
├── backend/     # FastAPI service: CV pipeline, subject localization, EXIF
├── frontend/    # React SPA: upload UI + analysis report with overlays
├── eval/        # Accuracy harness: your judgments vs. pipeline output
├── scripts/     # smoke_test_subject.py — manual subject-locator inspection
└── README.md
```

See `backend/README.md` and `frontend/README.md` for per-app details.
