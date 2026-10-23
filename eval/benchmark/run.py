"""Run the benchmark and write eval/results/.

    cd eval
    python -m benchmark.fetch                    # once: datasets -> eval/data/
    python -m benchmark.run                      # all tasks
    python -m benchmark.run --tasks subject      # just one
    python -m benchmark.run --hlw-archive PATH   # include horizon (HLW is gated)

Writes one JSON per task to eval/results/<task>.json and a combined
eval/results/RESULTS.md. The composition task also refits
backend/app/services/scoring/calibration.json — the model the app serves —
unless --no-write-calibration is given.

The VLM subject tier is a paid Claude call per image and is excluded unless
--with-vlm is passed (and ANTHROPIC_API_KEY is set).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from benchmark import aesthetic, calibrate, metrics, tasks
from benchmark.fetch import fetch_hlw

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
ALL_TASKS = ("subject", "aesthetic", "composition", "horizon")


def _env() -> dict[str, Any]:
    import cv2

    info: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "opencv": cv2.__version__,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        import torch

        info["torch"] = torch.__version__
    except ImportError:
        info["torch"] = None
    return info


def _save(name: str, result: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{name}.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------


def run_aesthetic(models: list[str], threads: int) -> dict[str, Any]:
    targets = [("koniq", "test"), ("cadb", "test"), ("cadb", "train")]
    aesthetic.ensure_scores(models, targets, threads)
    koniq_mos = tasks.koniq_labels()
    cadb_comp, cadb_aes = tasks.cadb_labels()
    test_ids = json.loads((Path(__file__).parent / "manifests" / "cadb.json").read_text(encoding="utf-8"))["splits"]["test"]
    koniq_ids = json.loads((Path(__file__).parent / "manifests" / "koniq.json").read_text(encoding="utf-8"))["splits"]["test"]
    resources = aesthetic.load_resources()
    out: dict[str, Any] = {"models": {}}
    for model in models:
        k = aesthetic.load_scores(model, "koniq")
        c = aesthetic.load_scores(model, "cadb")
        out["models"][model] = {
            **aesthetic.CANDIDATES[model],
            "koniq_test_mos": metrics.correlation([k[i] for i in koniq_ids], [koniq_mos[i] for i in koniq_ids]),
            "cadb_test_composition": metrics.correlation(
                [c[i] for i in test_ids], [cadb_comp[i] for i in test_ids]
            ),
            "cadb_test_aadb_aesthetic": metrics.correlation(
                [c[i] for i in test_ids], [cadb_aes[i] for i in test_ids]
            ),
            "resources": resources.get(model),
        }
    return out


def run_composition(workers: int, aesthetic_model: str | None, write: bool) -> dict[str, Any]:
    from app.services.scoring import composition_score as cs

    train = tasks.composition_results("train", workers)
    test = tasks.composition_results("test", workers)
    comp_mean, _ = tasks.cadb_labels()
    y_train = np.array([comp_mean[i] for i in train])
    y_test = [comp_mean[i] for i in test]

    out: dict[str, Any] = {
        "dataset": "CADB", "n_train": len(train), "n_test": len(test),
        "target": "mean of 5 expert composition ratings (1-5)",
        "subject_tiers": "detector + saliency (VLM off)",
        "ms_per_image": round(float(np.mean([r["_ms"] for r in test.values()])), 1),
    }
    heuristic = [cs.heuristic_score(test[i]) for i in test]
    out["heuristic_mean_score"] = metrics.correlation(heuristic, y_test)
    out["per_axis"] = {}
    for axis in cs.AXES:
        values = [cs.profile(test[i])[axis][0] for i in test]
        out["per_axis"][axis] = metrics.correlation(values, y_test)

    geo_rows_train = calibrate.build_rows(train, None)
    geo_rows_test = calibrate.build_rows(test, None)
    geo_names = sorted(geo_rows_train[0])
    geo = calibrate.fit_model("ridge-cadb-geometry-v1", geo_rows_train, y_train, geo_names)
    out["calibrated_geometry"] = {
        **metrics.correlation(calibrate.predict(geo, geo_rows_test).tolist(), y_test),
        "alpha": geo["alpha"],
    }
    models = [geo]

    if aesthetic_model:
        aes = aesthetic.load_scores(aesthetic_model, "cadb")
        # Model outputs live on different native scales; put them on 0-100
        # with the train split's own range so the feature means the same thing
        # at inference time (the app applies the same mapping, stored below).
        train_vals = np.array([aes[i] for i in train])
        lo, hi = float(np.percentile(train_vals, 1)), float(np.percentile(train_vals, 99))

        def to100(v: float) -> float:
            return float(np.clip((v - lo) / (hi - lo), 0, 1) * 100)

        aes100 = {i: to100(aes[i]) for i in [*train, *test]}
        out["aesthetic_alone"] = metrics.correlation([aes100[i] for i in test], y_test)
        full_train = calibrate.build_rows(train, {i: aes100[i] for i in train})
        full_test = calibrate.build_rows(test, {i: aes100[i] for i in test})
        full = calibrate.fit_model(
            f"ridge-cadb-geometry+{aesthetic_model}-v1", full_train, y_train, sorted(full_train[0])
        )
        full["aesthetic_model"] = aesthetic_model
        full["aesthetic_raw_range"] = [round(lo, 6), round(hi, 6)]
        out["calibrated_geometry_plus_aesthetic"] = {
            **metrics.correlation(calibrate.predict(full, full_test).tolist(), y_test),
            "alpha": full["alpha"],
        }
        models = [full, geo]

    out["coefficients"] = {m["name"]: dict(zip(m["features"], m["coef"])) for m in models}
    if write:
        calibrate.write_calibration(
            models,
            {
                "test_metrics": {
                    m["name"]: out["calibrated_geometry_plus_aesthetic" if "+" in m["name"] else "calibrated_geometry"]
                    for m in models
                },
                "heuristic_test_metrics": out["heuristic_mean_score"],
            },
        )
        out["calibration_written_to"] = str(calibrate.CALIBRATION_OUT.relative_to(calibrate.REPO))
    return out


# ---------------------------------------------------------------------------


def _fmt(corr: dict[str, Any] | None, key: str = "spearman") -> str:
    if not corr or corr.get(key) is None:
        return "—"
    lo, hi = corr.get(f"{key}_ci95") or (None, None)
    return f"{corr[key]:.3f} [{lo:.2f}, {hi:.2f}]" if lo is not None else f"{corr[key]:.3f}"


def _mean(m: dict[str, Any] | None, digits: int = 3) -> str:
    if not m or m.get("mean") is None:
        return "—"
    lo, hi = m["ci95"]
    return f"{m['mean']:.{digits}f} [{lo:.{digits - 1}f}, {hi:.{digits - 1}f}]"


def write_markdown(results: dict[str, Any]) -> None:
    lines = [
        "# Frame Grader benchmark results",
        "",
        "Generated by `python -m benchmark.run` (eval/benchmark/). Numbers in brackets are",
        "bootstrap 95% CIs. Samples are fixed and listed in eval/benchmark/manifests/.",
        "Correlations are Spearman (SRCC) and Pearson (PLCC, raw scores, no logistic fit).",
        "",
        f"Environment: {json.dumps(results.get('env', {}))}",
        "",
    ]

    hz = results.get("horizon")
    lines += ["## Horizon detection + tilt — HLW", ""]
    if hz and "detection" in hz:
        d = hz["detection"]
        lines += [
            f"n = {hz['n']} (HLW test); a detection counts when the line is within "
            f"{hz['tolerance_frac_height']:.0%} of image height of ground truth at both edges.",
            "",
            "| Precision | Recall | F1 | Tilt MAE ° (reliable only) | Tilt reported on | Tilt MAE ° (all correct, unreliable = 0°) | ms/img |",
            "|---|---|---|---|---|---|---|",
            f"| {d['precision']:.3f} | {d['recall']:.3f} | {d['f1']:.3f} | {_mean(hz['tilt_mae_deg_reliable'], 2)} "
            f"| {hz['tilt_reported_fraction']:.0%} | {_mean(hz['tilt_mae_deg_all_correct_detections'], 2)} | {hz['ms_per_image']} |",
            "",
        ]
    else:
        lines += [
            "**Not run.** HLW is distributed on request only (no public download URL), so it",
            "cannot be fetched by script. Request access from the authors (Workman, Zhai,",
            "Jacobs — https://mvrl.cse.wustl.edu/data), then run",
            "`python -m benchmark.run --tasks horizon --hlw-archive /path/to/hlw_1_0.zip`.",
            "",
        ]

    sub = results.get("subject")
    if sub:
        lines += [
            "## Subject localization — DUTS-TE",
            "",
            f"n = {sub['n']}. Ground truth = bounding box of the salient-object mask. "
            "`box IoU (all)` scores a missing box as 0; `centroid in mask` needs no box.",
            "",
            "| Tier | Box IoU (all) | Box IoU (when boxed) | Has box | IoU ≥ 0.5 | Centroid in mask | ms/img |",
            "|---|---|---|---|---|---|---|",
        ]
        for tier, t in sub["tiers"].items():
            lines.append(
                f"| {tier} | {_mean(t['box_iou_all'])} | {_mean(t['box_iou_when_boxed'])} | "
                f"{t['box_coverage']:.0%} | {t['iou_at_0.5_rate']:.0%} | {_mean(t['centroid_in_mask_rate'])} | {t['ms_per_image']} |"
            )
        lines += ["", f"Composite tier mix: {sub.get('composite_tier_mix')}", ""]

    aes = results.get("aesthetic")
    if aes:
        lines += [
            "## Learned quality / aesthetic models",
            "",
            "SRCC vs. KonIQ-10k MOS (official test split, n=500) and vs. CADB (test, n=500):",
            "composition rating and the AADB aesthetic score CADB inherits. Cost measured on",
            "this machine's CPU at a 512px input, each model in its own process.",
            "",
            "| Model | Trained on | KonIQ SRCC | CADB composition SRCC | CADB aesthetic SRCC | Params (M) | Load (MB) | Peak RSS (MB) | ms/img |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for name, m in aes["models"].items():
            r = m.get("resources") or {}
            lines.append(
                f"| {name} | {m['trained_on']} | {_fmt(m['koniq_test_mos'])} | {_fmt(m['cadb_test_composition'])} | "
                f"{_fmt(m['cadb_test_aadb_aesthetic'])} | {r.get('params_m', '—')} | {r.get('model_load_mb', '—')} | "
                f"{r.get('peak_rss_mb', '—')} | {r.get('ms_per_image', '—')} |"
            )
        if aes.get("deployed"):
            lines += ["", "**Deployed:** " + aes["deployed"], ""]
        lines.append("")

    comp = results.get("composition")
    if comp:
        lines += [
            "## Overall composition score — CADB",
            "",
            f"Fitted on CADB train (n={comp['n_train']}), reported on CADB test (n={comp['n_test']}).",
            "",
            "| Scorer | SRCC | PLCC |",
            "|---|---|---|",
            f"| Hand-weighted mean (previous app score) | {_fmt(comp['heuristic_mean_score'])} | {_fmt(comp['heuristic_mean_score'], 'pearson')} |",
            f"| Calibrated ridge, geometry only | {_fmt(comp['calibrated_geometry'])} | {_fmt(comp['calibrated_geometry'], 'pearson')} |",
        ]
        if "aesthetic_alone" in comp:
            lines += [
                f"| Learned aesthetic model alone | {_fmt(comp['aesthetic_alone'])} | {_fmt(comp['aesthetic_alone'], 'pearson')} |",
                f"| Calibrated ridge, geometry + aesthetic | {_fmt(comp['calibrated_geometry_plus_aesthetic'])} | {_fmt(comp['calibrated_geometry_plus_aesthetic'], 'pearson')} |",
            ]
        lines += ["", "Per-axis SRCC vs. the human composition rating:", "", "| Axis | SRCC |", "|---|---|"]
        for axis, corr in comp["per_axis"].items():
            lines.append(f"| {axis} | {_fmt(corr)} |")
        lines.append("")

    (RESULTS_DIR / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", nargs="*", choices=ALL_TASKS, default=list(ALL_TASKS))
    parser.add_argument("--workers", type=int, default=3, help="processes for the CV passes")
    parser.add_argument("--threads", type=int, default=4, help="torch threads for model scoring")
    parser.add_argument("--models", nargs="*", default=list(aesthetic.CANDIDATES))
    parser.add_argument("--deploy-model", default=None, help="aesthetic model used as a calibration feature")
    parser.add_argument("--hlw-archive")
    parser.add_argument("--hlw-coords", default="center-up", choices=["center-up", "center-down", "topleft"])
    parser.add_argument("--with-vlm", action="store_true")
    parser.add_argument("--no-write-calibration", action="store_true")
    args = parser.parse_args(argv)

    os.environ["BENCH_WORKERS"] = str(args.workers)
    if args.with_vlm:
        os.environ["BENCH_WITH_VLM"] = "1"

    summary_path = RESULTS_DIR / "summary.json"
    results: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    results["env"] = _env()

    for task in args.tasks:
        print(f"[{task}]", flush=True)
        start = time.perf_counter()
        if task == "horizon":
            if not fetch_hlw(args.hlw_archive):
                results["horizon"] = {"status": "skipped: HLW requires an access request"}
                continue
            result = tasks.run_horizon(args.workers, args.hlw_coords)
        elif task == "subject":
            result = tasks.run_subject(args.workers)
        elif task == "aesthetic":
            result = run_aesthetic(args.models, args.threads)
            if args.deploy_model:
                result["deployed"] = args.deploy_model
        else:
            result = run_composition(args.workers, args.deploy_model, not args.no_write_calibration)
        result["wall_seconds"] = round(time.perf_counter() - start, 1)
        results[task] = result
        _save(task, result)
        print(f"  done in {result['wall_seconds']}s", flush=True)

    summary_path.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    write_markdown(results)
    print(f"wrote {RESULTS_DIR / 'RESULTS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
