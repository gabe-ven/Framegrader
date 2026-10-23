# Evaluation

Two harnesses:

| | What it measures | Data |
|---|---|---|
| `run_eval.py` | the pipeline against *your* judgments on *your* photos | `eval/photos/` + `ground_truth.json` (local, gitignored) |
| `benchmark/` | the pipeline against public, human-labelled datasets | downloaded by script into `eval/data/` (gitignored) |

Results of the public benchmark are committed in [`results/`](results/RESULTS.md).

## Public benchmark

```bash
# from the repo root
pip install -r backend/requirements.lock -r eval/requirements.txt
cd eval
python -m benchmark.fetch     # ~1 GB transferred, ~15 min; images never committed
python -m benchmark.run       # ~30-45 min on a laptop CPU; writes eval/results/
```

| Task | Dataset (split, n) | What is scored | Metrics |
|---|---|---|---|
| Horizon | HLW (test, 500) | `detect_horizon` | detection precision/recall/F1 at 5% of image height; tilt MAE (°) |
| Subject | DUTS-TE (test, 500) | each locator tier + the production composite | box IoU, IoU ≥ 0.5 rate, centroid-in-mask rate |
| Composition | CADB (train 1000 / test 500) | old hand-weighted score, each axis, calibrated score | Spearman, Pearson vs. mean expert rating |
| Quality | KonIQ-10k (official test, 500) and CADB test | candidate learned models | Spearman, Pearson; params, memory, ms/img |

Every metric carries a bootstrap 95% CI. At n=500 a correlation is good to about
±0.08, which is the right lens for comparing two rows of the table.

### Reproducibility

- **Fixed samples.** Each sample is drawn once with a fixed seed from the
  dataset's test split (KonIQ: the official split, so models trained on KonIQ's
  train split are never scored on their own training images). The sampled IDs
  and the SHA-256 of every image and label file are committed in
  `benchmark/manifests/`. Later fetches reuse those IDs and fail if any hash
  differs, so upstream drift is detected, not absorbed.
- **Partial downloads.** The CADB and KonIQ archives (2.1 GB and 0.8 GB) are
  read over HTTP Range requests: the zip directory, then exactly the sampled
  members, each CRC-checked. See `benchmark/remote_zip.py`.
- **Sources.** All pinned in `benchmark/sources.py`. DUTS-TE comes from a
  Hugging Face mirror byte-identical to the official archive (same SHA-256,
  verified 2026-10-22) because the official host's TLS certificate has expired.
- **Production code paths.** Tasks call the same functions the API calls. The
  calibrated composition score is fitted here and written to
  `backend/app/services/scoring/calibration.json`, which the app loads.
- **Paid tiers off.** The Claude VLM subject tier costs a call per image and is
  excluded unless `--with-vlm` is passed.

### HLW needs an access request

Horizon Lines in the Wild is not publicly downloadable: the authors' lab
([MVRL data page](https://mvrl.cse.wustl.edu/data)) distributes it on request,
and no archive URL has ever been public. Everything else is scripted. Once you
have the archive:

```bash
python -m benchmark.run --tasks horizon --hlw-archive /path/to/hlw_1_0.zip
```

HLW's `metadata.csv` gives two points on the horizon per image. The loader
assumes HLW 1.0's convention (pixel coordinates relative to the image centre,
y up); `--hlw-coords center-down|topleft` overrides it. Check a handful of
overlays the first time you run it.

### Useful flags

```
--tasks subject aesthetic composition horizon
--workers 3                 CV processes (each loads YOLO-World, ~0.5 GB)
--models nima musiq-ava …   aesthetic candidates to score
--deploy-model nima         aesthetic model used as a calibration feature
--no-write-calibration      evaluate without touching the app's calibration
```
