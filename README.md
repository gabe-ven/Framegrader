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

```bash
docker build -t framegrader-api backend/
docker run -p 8000:8000 --env-file backend/.env framegrader-api
```

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

The frontend builds to static files. Set `VITE_API_BASE_URL` at build time when the
SPA is served from a different origin than the API, and add that origin to the
backend's `ALLOWED_ORIGINS` (see `frontend/.env.example`).

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
