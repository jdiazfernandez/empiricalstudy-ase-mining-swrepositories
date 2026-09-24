"""Download the pinned AIDev tables once into data/aidev/ (spec 001 §4.1).

Pinned to the revision recorded in data/DATASET_VERSION.md. Re-running is a no-op.
"""
from __future__ import annotations

import pathlib
import sys

from huggingface_hub import hf_hub_download

REPO = "hao-li/AIDev"
REVISION = "68ed5f4b80d27a9e057fc57567f38bd322ac73ec"
ROOT = pathlib.Path(__file__).resolve().parents[2]
DEST = ROOT / "data" / "aidev"

TABLES = [
    "pull_request", "repository", "pr_reviews", "pr_comments",
    "pr_review_comments_v2", "pr_timeline", "pr_task_type",
    "pr_commits", "related_issue",
]


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    for t in TABLES:
        p = hf_hub_download(
            repo_id=REPO, repo_type="dataset", revision=REVISION,
            filename=f"{t}.parquet", local_dir=str(DEST),
        )
        size = pathlib.Path(p).stat().st_size / 1e6
        print(f"  {t:<24} {size:8.1f} MB")
    print(f"\ncached under {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
