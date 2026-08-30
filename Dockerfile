# Frame Grader backend.
#
# Build from the REPO ROOT:
#   docker build -t framegrader-api .
#   docker run -p 8000:8000 --env-file backend/.env framegrader-api
#
# Lives at the root, not under backend/, on purpose. Render, Railway and most
# managed hosts default to looking for ./Dockerfile with the repo root as build
# context. Keeping it here means a service created through a dashboard works
# with no path overrides — the misconfiguration that produced two failed
# deploys ("failed to read dockerfile: open Dockerfile: no such file").
#
# Two things this image deliberately does:
#   1. Installs from requirements.lock, not requirements.txt, so the transitive
#      set is frozen. Resolving fresh is what put CI on OpenCV 5.0 while dev
#      machines sat on 4.x.
#   2. Bakes the YOLO-World weights in at build time. Otherwise every cold
#      container downloads ~25MB before it can serve its first analysis.

# ---------------------------------------------------------------------------
# Builder — compilers, git (the CLIP dep is a git URL) and the weights fetch.
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

# Which lock to install. Default is the full app. Pass
#   --build-arg REQUIREMENTS=requirements-lite.lock
# to drop torch/ultralytics and fit a 512MB free instance — see that file's
# header for exactly what the lite build gives up.
ARG REQUIREMENTS=requirements.lock

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements*.lock ./

# CPU-only torch first, and only when the chosen lock actually wants it. The
# default PyPI wheels bundle CUDA and add ~2GB to an image that will never see a
# GPU; installing the matching versions from the CPU index up front means the
# lock install below finds them already satisfied.
RUN if grep -q '^torch==' "${REQUIREMENTS}"; then \
        pip install --index-url https://download.pytorch.org/whl/cpu \
            torch==2.6.0 torchvision==0.21.0; \
    fi

RUN pip install -r "${REQUIREMENTS}"

# Pre-download the detector weights, so a cold container serves its first
# analysis at full speed instead of fetching 25MB. Skipped for the lite build,
# which has no detector tier. Runs in the directory the app will use as its
# working dir, because the code asks for the checkpoint by bare filename.
WORKDIR /weights
RUN if python -c "import ultralytics" 2>/dev/null; then \
        python -c "from ultralytics import YOLO; YOLO('yolov8s-worldv2.pt')"; \
    else \
        echo "lite build: no detector tier, skipping weights"; \
    fi

# ---------------------------------------------------------------------------
# Runtime — no compilers, no git, no pip cache.
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# libgomp1: torch's OpenMP runtime. libglib2.0-0 + libgl1: linked by the
# non-headless opencv-python wheel (in requirements.lock alongside the headless
# one); libgl1 provides libGL.so.1, without which `import cv2` fails at runtime.
# curl: for the HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
        libgl1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Ultralytics and matplotlib write settings/caches to $HOME on import and
    # fail noisily if it is not writable. Point them somewhere the non-root
    # user owns.
    YOLO_CONFIG_DIR=/home/appuser/.config/Ultralytics \
    MPLCONFIGDIR=/home/appuser/.cache/matplotlib

WORKDIR /app
# Trailing slash + glob: copies the checkpoint for the full build, and copies
# nothing (without failing) for the lite build.
COPY --from=builder /weights/ /app/
COPY backend/app ./app

RUN mkdir -p "$YOLO_CONFIG_DIR" "$MPLCONFIGDIR" && chown -R appuser:appuser /app /home/appuser
USER appuser

EXPOSE 8000

# start-period covers model warm-up; the app answers /health immediately, but
# giving it room avoids a restart loop on a slow first boot.
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

# --proxy-headers makes uvicorn resolve X-Forwarded-For, which the per-IP rate
# limiter depends on: without it every request behind a proxy shares the
# proxy's address and one bucket throttles all users. Restrict which proxies
# are trusted with the FORWARDED_ALLOW_IPS env var — leaving it open lets a
# client spoof its address and evade the limit.
#
# Single worker on purpose: the rate limiter's storage is in-process (N workers
# = N x the limit) and each worker loads its own copy of the model. Scale with
# replicas behind a shared Redis for slowapi, not with --workers.
# Shell form on purpose, so ${PORT} expands at runtime: managed hosts (Render,
# Cloud Run, Railway) assign the port and expect the process to bind it rather
# than a fixed one. `exec` keeps uvicorn as PID 1 so it receives SIGTERM and
# shuts down cleanly instead of being killed after the grace period.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers
