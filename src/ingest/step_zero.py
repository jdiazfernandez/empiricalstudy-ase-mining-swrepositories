"""Step zero (spec 001 §16): pin the AIDev release and verify it against spec §4.1.

Reads parquet over HTTPS at a pinned revision. Downloads nothing.
Emits data/DATASET_VERSION.md.

C7 compliance: schema, counts and marginal distributions only.
No treatment-outcome crossing is computed anywhere in this file.
"""
from __future__ import annotations

import json
import pathlib
import sys

import duckdb
from huggingface_hub import HfApi

REPO = "hao-li/AIDev"
ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "DATASET_VERSION.md"

# Tables the spec depends on (§4.1), by tier.
TIERS = {
    "full": ["all_pull_request", "all_repository", "all_user"],
    "pop": [
        "pull_request", "repository", "pr_timeline", "pr_comments", "pr_reviews",
        "pr_review_comments", "pr_review_comments_v2", "pr_commits",
        "pr_commit_details", "pr_task_type", "issue", "related_issue", "user",
    ],
    "human": ["human_pull_request", "human_pr_task_type"],
}

# Fields §4.1 claims to use, per table.
SPEC_FIELDS = {
    "pull_request": ["id", "number", "title", "body", "agent", "user_id", "user",
                     "state", "created_at", "closed_at", "merged_at", "repo_id", "html_url"],
    "repository": ["id", "full_name", "license", "language", "forks", "stars"],
    "pr_reviews": ["id", "pr_id", "user", "user_type", "state", "submitted_at", "body"],
    "pr_comments": ["id", "pr_id", "user", "user_type", "created_at", "body"],
    "pr_review_comments_v2": ["id", "pull_request_review_id", "user", "user_type",
                              "path", "body", "created_at"],
    "pr_commits": ["sha", "pr_id", "author", "message"],
    "pr_commit_details": ["sha", "pr_id", "commit_stats_additions",
                          "commit_stats_deletions", "filename", "changes"],
    "pr_timeline": ["pr_id", "event", "created_at", "actor", "label", "message"],
    "pr_task_type": ["id", "agent", "type", "reason"],
    "related_issue": ["pr_id", "issue_id", "source"],
}


def url(sha: str, table: str) -> str:
    return f"https://huggingface.co/datasets/{REPO}/resolve/{sha}/{table}.parquet"


def main() -> int:
    api = HfApi()
    info = api.dataset_info(REPO)
    sha = info.sha
    files = {f.rfilename for f in info.siblings}

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")

    report: dict = {
        "revision": sha,
        "last_modified": str(info.last_modified),
        "counts": {},
        "schemas": {},
        "missing_tables": [],
        "missing_fields": {},
    }

    # --- Task 2: row counts + schema, per table -------------------------------
    for tier, tables in TIERS.items():
        for t in tables:
            if f"{t}.parquet" not in files:
                report["missing_tables"].append(t)
                continue
            u = url(sha, t)
            n = con.execute(f"SELECT count(*) FROM read_parquet('{u}')").fetchone()[0]
            cols = con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{u}')"
            ).fetchdf()
            report["counts"][t] = {"tier": tier, "rows": int(n)}
            report["schemas"][t] = dict(zip(cols.column_name, cols.column_type))
            print(f"  {t:<24} {n:>12,}  ({len(cols)} cols)", flush=True)

            expected = SPEC_FIELDS.get(t)
            if expected:
                absent = [c for c in expected if c not in set(cols.column_name)]
                if absent:
                    report["missing_fields"][t] = absent

    # --- Task 3: true cutoff --------------------------------------------------
    for t in ("pull_request", "all_pull_request"):
        u = url(sha, t)
        row = con.execute(f"""
            SELECT min(created_at)::VARCHAR, max(created_at)::VARCHAR,
                   max(merged_at)::VARCHAR, count(*) FILTER (WHERE merged_at IS NOT NULL)
            FROM read_parquet('{u}')
        """).fetchone()
        report[f"coverage_{t}"] = {
            "first_created_at": row[0], "last_created_at": row[1],
            "last_merged_at": row[2], "merged_rows": int(row[3]),
        }

    # --- Task 4: AIDev-pop parameters ----------------------------------------
    u = url(sha, "repository")
    row = con.execute(f"""
        SELECT count(*), min(stars), max(stars),
               count(*) FILTER (WHERE full_name IS NULL),
               count(*) FILTER (WHERE license IS NULL),
               count(DISTINCT language)
        FROM read_parquet('{u}')
    """).fetchone()
    report["pop_params"] = {
        "repositories": int(row[0]), "min_stars": int(row[1]), "max_stars": int(row[2]),
        "missing_full_name": int(row[3]), "missing_license": int(row[4]),
        "distinct_languages": int(row[5]),
    }

    # --- Task 5: agent distribution (marginal only) ---------------------------
    for t in ("pull_request", "all_pull_request"):
        u = url(sha, t)
        df = con.execute(f"""
            SELECT agent, count(*) AS prs FROM read_parquet('{u}')
            GROUP BY agent ORDER BY prs DESC
        """).fetchdf()
        total = df.prs.sum()
        report[f"agents_{t}"] = [
            {"agent": r.agent, "prs": int(r.prs), "share": round(100 * r.prs / total, 1)}
            for r in df.itertuples()
        ]

    # --- the two review-comment variants -------------------------------------
    if "pr_review_comments" in report["counts"] and "pr_review_comments_v2" in report["counts"]:
        report["review_comments_variants"] = {
            "pr_review_comments": report["counts"]["pr_review_comments"]["rows"],
            "pr_review_comments_v2": report["counts"]["pr_review_comments_v2"]["rows"],
            "cols_v1": sorted(report["schemas"]["pr_review_comments"]),
            "cols_v2": sorted(report["schemas"]["pr_review_comments_v2"]),
        }

    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "step_zero_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print("\nwrote data/step_zero_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
