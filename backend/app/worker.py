"""Standalone job worker: ``python -m app.worker``.

Use this when the API and the workers should run as separate processes — set
``EMBEDDED_WORKERS=0`` on the API so it only enqueues, and run as many of these
as the queue needs against the same ``DATABASE_URL`` (Postgres; SQLite is for a
single process). ``--once`` drains the queue and exits, which is handy for
cron-style deployments and for debugging a stuck job.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs.worker import Worker

logger = logging.getLogger("app.worker")


def main() -> None:
    parser = argparse.ArgumentParser(description="Frame Grader job worker")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--once", action="store_true", help="drain the queue, then exit")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    worker = Worker(threads=args.threads)

    if args.once:
        worker.maintain()
        logger.info("Drained queue", extra={"jobs": worker.drain()})
        return

    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    worker.start()
    stopped.wait()
    logger.info("Shutting down; waiting for running jobs")
    worker.stop(timeout=60)


if __name__ == "__main__":
    main()
