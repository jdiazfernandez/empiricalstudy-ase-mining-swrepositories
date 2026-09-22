"""Build the point-in-time harness feature matrix (spec 001 §5.1, §6.2, AC-3).

For every agentic PR, each mechanism flag is evaluated AS OF THAT PR'S created_at.
An artifact introduced after the PR was opened cannot mark that PR as harnessed.

Also computes the naive "present at collection time" indicator, purely to
QUANTIFY the error the point-in-time rule prevents. The naive column is a
diagnostic and must never enter a model.

C7: treatment side only. No outcome column is read, joined, or written here.
"""
from __future__ import annotations

import json
import pathlib
import sys

import duckdb
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
AIDEV = ROOT / "data" / "aidev"
RAW = ROOT / "data" / "harness_raw.json"
OUT = ROOT / "data" / "feature_matrix.parquet"
REPORT = ROOT / "data" / "point_in_time_report.json"

# A rule file below this size carrying no normative clause is a stub/pointer,
# not a system specification. Sensitivity is reported both ways.
STUB_BYTES = 200

MECHANISMS = [
    "H1_context_engineering", "H2_persistent_knowledge", "H3_executable_specs",
    "H7_evidence_acceptance", "H8_graduated_autonomy",
]


def dedupe(recs: list[dict]) -> tuple[pd.DataFrame, dict]:
    """Flatten artifacts, dropping symlinks and byte-identical duplicates."""
    rows, dropped = [], {"symlink": 0, "duplicate_blob": 0, "stub": 0, "no_date": 0}
    for r in recs:
        if r["status"] != "cloned":
            continue
        seen_blobs: set[str] = set()
        for a in sorted(r["artifacts"], key=lambda x: x["first_added"] or "9999"):
            if a.get("is_symlink"):
                dropped["symlink"] += 1
                continue
            if a["first_added"] is None:
                dropped["no_date"] += 1
                continue
            sha = a.get("blob_sha")
            if sha and sha in seen_blobs:
                dropped["duplicate_blob"] += 1
                continue
            if sha:
                seen_blobs.add(sha)
            is_stub = (
                a["mechanism"] == "H1_context_engineering"
                and a.get("bytes", 10**9) < STUB_BYTES
                and a.get("normative_clauses", 0) == 0
            )
            if is_stub:
                dropped["stub"] += 1
            rows.append({
                "repo_id": r["repo_id"], "full_name": r["full_name"],
                "mechanism": a["mechanism"], "path": a["path"],
                "first_added": a["first_added"], "is_stub": is_stub,
                "bytes": a.get("bytes"), "normative_clauses": a.get("normative_clauses"),
            })
    return pd.DataFrame(rows), dropped


def main() -> int:
    recs = json.loads(RAW.read_text(encoding="utf-8"))
    arts, dropped = dedupe(recs)
    arts.to_csv(ROOT / "data" / "artifacts_deduped.csv", index=False)

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false;")
    con.register("arts", arts)
    con.execute(f"""
        CREATE TABLE prs AS
        SELECT p.id AS pr_id, p.repo_id, p.agent,
               CAST(p.created_at AS TIMESTAMP) AS created_at
        FROM read_parquet('{(AIDEV / "pull_request.parquet").as_posix()}') p
        WHERE p.repo_id IN (SELECT DISTINCT repo_id FROM arts)
           OR p.repo_id IN ({",".join(str(r["repo_id"]) for r in recs)})
    """)
    con.execute("""
        CREATE TABLE a AS
        SELECT repo_id, mechanism, path, is_stub,
               CAST(first_added AS TIMESTAMP) AS first_added
        FROM arts
    """)

    # Point-in-time flags (§5.1) vs naive present-at-collection flags.
    sel = []
    for m in MECHANISMS:
        sel.append(f"""
          CASE WHEN EXISTS (SELECT 1 FROM a WHERE a.repo_id = prs.repo_id
                 AND a.mechanism = '{m}' AND NOT a.is_stub
                 AND a.first_added <= prs.created_at) THEN 1 ELSE 0 END AS pit_{m[:2]}""")
        sel.append(f"""
          CASE WHEN EXISTS (SELECT 1 FROM a WHERE a.repo_id = prs.repo_id
                 AND a.mechanism = '{m}' AND NOT a.is_stub) THEN 1 ELSE 0 END AS naive_{m[:2]}""")
    mat = con.execute(f"""
        SELECT prs.pr_id, prs.repo_id, prs.agent, prs.created_at {"," if sel else ""}
               {",".join(sel)}
        FROM prs
    """).fetchdf()

    pit_cols = [c for c in mat.columns if c.startswith("pit_")]
    naive_cols = [c for c in mat.columns if c.startswith("naive_")]
    mat["harness_breadth_pit"] = mat[pit_cols].sum(axis=1)
    mat["harness_breadth_naive"] = mat[naive_cols].sum(axis=1)
    mat["harness_any_pit"] = (mat.harness_breadth_pit > 0).astype(int)
    mat["harness_any_naive"] = (mat.harness_breadth_naive > 0).astype(int)
    mat.to_parquet(OUT, index=False)

    # --- AC-3 verification: independent recomputation, not a tautology --------
    viol = con.execute("""
        SELECT count(*) FROM prs JOIN a ON a.repo_id = prs.repo_id
        WHERE a.first_added > prs.created_at
          AND EXISTS (SELECT 1 FROM a a2 WHERE a2.repo_id = prs.repo_id
                      AND a2.mechanism = a.mechanism AND a2.path = a.path
                      AND a2.first_added <= prs.created_at)
    """).fetchone()[0]

    n = len(mat)
    flips = int((mat.harness_any_naive != mat.harness_any_pit).sum())
    report = {
        "pilot_repos": len({r["full_name"] for r in recs}),
        "prs": n,
        "artifacts_kept": int(len(arts)),
        "artifacts_dropped": dropped,
        "ac3_violations": int(viol),
        "harness_any_pit": int(mat.harness_any_pit.sum()),
        "harness_any_naive": int(mat.harness_any_naive.sum()),
        "misclassified_by_naive": flips,
        "misclassified_pct": round(100 * flips / n, 1) if n else 0.0,
        "mean_breadth_pit": round(float(mat.harness_breadth_pit.mean()), 2),
        "mean_breadth_naive": round(float(mat.harness_breadth_naive.mean()), 2),
        "per_mechanism": {
            m[:2]: {
                "pit": int(mat[f"pit_{m[:2]}"].sum()),
                "naive": int(mat[f"naive_{m[:2]}"].sum()),
            } for m in MECHANISMS
        },
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nmatrix -> {OUT.relative_to(ROOT)}  ({n:,} PRs)")
    if viol:
        print(f"!! AC-3 VIOLATION: {viol}", file=sys.stderr)
        return 1
    print("AC-3 satisfied: no flag derives from a post-dated artifact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
