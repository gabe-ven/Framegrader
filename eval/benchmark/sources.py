"""Where every dataset comes from, pinned.

Each entry names the archive, the label files, and how they are verified:

- Label files are small and downloaded whole; their SHA-256 is pinned, so a
  silently changed upstream file fails the run instead of shifting the numbers.
- Image archives are large and read member-by-member over HTTP Range requests
  (remote_zip.py). zipfile checks each member's CRC-32 on extraction, and the
  committed manifest records the SHA-256 of every sampled image, so a rerun on
  another machine is verifiably the same images.

Sample sizes are fixed (see SAMPLES) and drawn with a fixed seed from each
dataset's *test* split, so models trained on a dataset's train split (several
pyiqa checkpoints are trained on KonIQ) are never scored on their own training
images. Sizes are chosen so the whole benchmark runs in roughly half an hour on
a laptop CPU; at n=500 the 95% CI on a Spearman correlation is about ±0.08.
"""

from __future__ import annotations

from dataclasses import dataclass

SEED = 20261022


@dataclass(frozen=True)
class Sample:
    split: str
    n: int


# dataset -> {purpose: Sample}
SAMPLES: dict[str, dict[str, Sample]] = {
    # Horizon detection + tilt. All of HLW's held-out test split is ~2k images.
    "hlw": {"test": Sample("test", 500)},
    # Subject localization. DUTS-TE is the standard 5,019-image test set.
    "duts": {"test": Sample("test", 500)},
    # Composition scoring. "train" fits the calibrated score; "test" (CADB's
    # official 1,000-image test split) is where every number is reported.
    "cadb": {"train": Sample("train", 1000), "test": Sample("test", 500)},
    # Overall quality. KonIQ-10k's official test split (2,015 images).
    "koniq": {"test": Sample("test", 500)},
}


DUTS = {
    # Byte-identical mirror of the official DUTS-TE.zip (same size and SHA-256
    # as http://saliencydetection.net/duts/download/DUTS-TE.zip, verified
    # 2026-10-22). The official host's TLS certificate has expired, so it can't
    # be fetched without disabling verification; the mirror can, and the
    # pinned hash makes the provenance checkable either way.
    "archive_url": (
        "https://huggingface.co/datasets/chitradrishti/duts/resolve/"
        "d608cfecc804f4c94c6cd1b0361528f8032fa2eb/DUTS-TE.zip"
    ),
    "archive_sha256": "d9905c33307e1d35c397604a701ed87f019acf060033076eec633f13a2eb8104",
    "image_dir": "DUTS-TE/DUTS-TE-Image/",
    "mask_dir": "DUTS-TE/DUTS-TE-Mask/",
    "license": "Research use; see http://saliencydetection.net/duts/",
}

CADB = {
    # Official distribution (Dropbox link from the CADB README).
    "archive_url": (
        "https://www.dropbox.com/scl/fi/fvlsnit7on6218szply4q/CADB_Dataset.zip"
        "?rlkey=mwt9eftdhmnawomv44x4deliw&dl=1"
    ),
    "image_dir": "CADB_Dataset/images/",
    "labels": {
        "composition_scores.json": "CADB_Dataset/composition_scores.json",
        "composition_attributes.json": "CADB_Dataset/composition_attributes.json",
        "split.json": "CADB_Dataset/split.json",
    },
    "license": "Research use; see https://github.com/bcmi/Image-Composition-Assessment-Dataset-CADB",
}

KONIQ = {
    # Official distribution: DaRUS (doi:10.18419/DARUS-2435), datafile 72286.
    "archive_url": "https://darus.uni-stuttgart.de/api/access/datafile/72286",
    "image_dir": "512x384/",
    # MOS + the official train/val/test split, from pyiqa's metainfo repo,
    # pinned to a commit. MOS here is KonIQ's MOS_zscore (0-100).
    "labels_url": (
        "https://huggingface.co/datasets/chaofengc/IQA-PyTorch-Datasets-metainfo/"
        "resolve/{rev}/meta_info_KonIQ10kDataset.csv"
    ),
    "labels_rev_api": "https://huggingface.co/api/datasets/chaofengc/IQA-PyTorch-Datasets-metainfo",
    "license": "CC BY 4.0 (images individually CC-licensed via YFCC100M)",
}

HLW = {
    # Horizon Lines in the Wild is distributed on request only: the MVRL lab's
    # data page (https://mvrl.cse.wustl.edu/data) says to contact them, and the
    # original project page asked for a form submission. There is no public
    # URL to script against, so this dataset is the one input the benchmark
    # cannot fetch for you. Point it at the archive you were given:
    #
    #   python -m benchmark.run --hlw-archive /path/to/hlw_1_0.zip
    #   (or HLW_ARCHIVE=/path/or/https-url)
    #
    # Expected layout (HLW 1.0): images/<name>, metadata.csv, split/test.txt.
    "archive_env": "HLW_ARCHIVE",
    "license": "Research use; request from the authors (Workman et al., BMVC 2016)",
}
