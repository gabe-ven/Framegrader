"""Stage plans and the progress tracker that reports against them.

Progress is *stage-based*, never time-based: the bar only moves when the worker
actually crosses a stage boundary. Each stage carries a weight — its share of a
typical job's wall-clock time — so the fraction tracks elapsed time rather
than stage count (the critique alone is half of an analysis; counting it as
1/7 would park the bar at 85% for seventeen seconds).

Weights are from measured stage timings on 26MP JPEGs (README, Performance):
decode ~0.4s, metadata ~0.3s, vision ~0.6s, subject 0.3s (detector) to ~6s
(VLM escalation), composition ~0.8s, critique ~16s. They only shape the bar;
which stage is running, and how long each finished one took, are exact.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StageSpec:
    name: str
    label: str
    weight: float


ANALYZE_PLAN: tuple[StageSpec, ...] = (
    StageSpec("decode", "Reading the photo", 0.02),
    StageSpec("metadata", "Reading EXIF and film recipe", 0.02),
    StageSpec("vision", "Measuring exposure and color", 0.03),
    StageSpec("subject", "Locating the subject", 0.13),
    StageSpec("composition", "Measuring composition", 0.04),
    StageSpec("scoring", "Scoring the photo", 0.04),
    StageSpec("critique", "Writing the critique", 0.72),
)

COLOR_GRADE_PLAN: tuple[StageSpec, ...] = (
    StageSpec("grade", "Suggesting a color grade", 1.0),
)

PLANS: dict[str, tuple[StageSpec, ...]] = {
    "analyze": ANALYZE_PLAN,
    "color_grade": COLOR_GRADE_PLAN,
}


def initial_stages(kind: str) -> list[dict[str, Any]]:
    return [
        {"name": s.name, "label": s.label, "status": "pending", "duration_ms": None}
        for s in PLANS[kind]
    ]


Persist = Callable[[str | None, float, list[dict[str, Any]]], None]


class ProgressTracker:
    """Marks stages running/done and persists each transition.

    ``start(name)`` closes whatever stage is open (recording its duration) and
    opens ``name``. Stages may be skipped — e.g. a job resumed after a crash
    starts mid-plan — and skipped ones are marked as such rather than left
    "pending" forever.
    """

    def __init__(self, kind: str, persist: Persist) -> None:
        self._specs = {s.name: s for s in PLANS[kind]}
        self._order = [s.name for s in PLANS[kind]]
        self._stages = initial_stages(kind)
        self._persist = persist
        self._current: str | None = None
        self._started_at = 0.0

    @property
    def stages(self) -> list[dict[str, Any]]:
        return [dict(s) for s in self._stages]

    def _entry(self, name: str) -> dict[str, Any]:
        return self._stages[self._order.index(name)]

    def _close_current(self, status: str) -> None:
        if self._current is None:
            return
        entry = self._entry(self._current)
        entry["status"] = status
        entry["duration_ms"] = round((time.perf_counter() - self._started_at) * 1000, 1)
        self._current = None

    def _fraction(self) -> float:
        done = sum(
            self._specs[s["name"]].weight
            for s in self._stages
            if s["status"] in ("done", "skipped")
        )
        total = sum(spec.weight for spec in self._specs.values()) or 1.0
        return round(min(1.0, done / total), 4)

    def start(self, name: str) -> None:
        if name not in self._specs:
            return  # a stage the pipeline reports but this plan doesn't track
        self._close_current("done")
        # Anything still pending before this stage was skipped.
        for earlier in self._order[: self._order.index(name)]:
            entry = self._entry(earlier)
            if entry["status"] == "pending":
                entry["status"] = "skipped"
        self._current = name
        self._started_at = time.perf_counter()
        self._entry(name)["status"] = "running"
        self._persist(name, self._fraction(), self.stages)

    def finish(self) -> list[dict[str, Any]]:
        self._close_current("done")
        for entry in self._stages:
            if entry["status"] == "pending":
                entry["status"] = "skipped"
        return self.stages

    def fail(self) -> list[dict[str, Any]]:
        self._close_current("failed")
        return self.stages
