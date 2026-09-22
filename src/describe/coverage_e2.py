"""PI-1, estimand E2: coverage of the observed agentic work (spec 001-v2 §5.1).

E1 asks "how many teams have adopted the mechanism, today?" and is answered per
repository by prevalence.py. E2 asks a different question -- "what fraction of
the recorded agentic work happened UNDER a harness?" -- and is answered per pull
request, evaluating each mechanism AS OF THAT PR'S created_at. An artifact
introduced after a PR was opened cannot mark that PR as harnessed.

The gap between the two is not an artifact to be reconciled away: it measures
how much adoption happened AFTER the observed work was done, which is the same
quantity the adoption curve reports from the other direction.

STRATUM P ONLY. AIDev ships PR-level tables for the pop tier alone; computing E2
for G1-G3 would require the remote all_pull_request table, and is not attempted
here. Reported as a scope limit, not as a missing number.

AC-3 is verified independently at the end: no E2 flag may derive from an
artifact whose first appearance post-dates the PR.
"""
from __future__ import annotations

import json
import pathlib
import sys

import duckdb
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "features"))
from build_matrix import dedupe  # noqa: E402  (shared A2 rule, single source)

PRS = ROOT / "data" / "aidev" / "pull_request.parquet"
RAW = ROOT / "data" / "harness_P_raw.json"
OUT = ROOT / "data" / "coverage_e2_report.json"

# Same five common mechanisms prevalence.py reports; H5 is excluded by D-v2-8
# (a property of H1's content, not an independent mechanism) and H6 is not an
# artifact at all.
MECHS = ["H1_context_engineering", "H2_persistent_knowledge",
         "H3_executable_specs", "H7_evidence_acceptance",
         "H8_graduated_autonomy"]


def main() -> int:
    recs = json.loads(RAW.read_text(encoding="utf-8"))
    arts, dropped = dedupe(recs)
    arts = arts[~arts.is_stub.astype(bool)]

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false;")
    con.register("arts_raw", arts)
    con.execute("""
        CREATE TABLE a AS
        SELECT CAST(repo_id AS BIGINT) AS repo_id, mechanism,
               CAST(first_added AS TIMESTAMP) AS first_added
        FROM arts_raw
    """)
    # C-v2-7: several AIDev columns are stored as VARCHAR. Cast explicitly.
    con.execute(f"""
        CREATE TABLE prs AS
        SELECT CAST(id AS VARCHAR) AS pr_id, CAST(repo_id AS BIGINT) AS repo_id,
               agent, CAST(created_at AS TIMESTAMP) AS created_at
        FROM read_parquet('{PRS.as_posix()}')
    """)

    sel = ",".join(f"""
        CASE WHEN EXISTS (SELECT 1 FROM a WHERE a.repo_id = prs.repo_id
               AND a.mechanism = '{m}' AND a.first_added <= prs.created_at)
             THEN 1 ELSE 0 END AS e2_{m[:2]},
        CASE WHEN EXISTS (SELECT 1 FROM a WHERE a.repo_id = prs.repo_id
               AND a.mechanism = '{m}') THEN 1 ELSE 0 END AS e1_{m[:2]}"""
        for m in MECHS)
    mat = con.execute(f"SELECT prs.*, {sel} FROM prs").fetchdf()

    e2c = [f"e2_{m[:2]}" for m in MECHS]
    e1c = [f"e1_{m[:2]}" for m in MECHS]
    mat["breadth_e2"] = mat[e2c].sum(axis=1)
    mat["breadth_e1"] = mat[e1c].sum(axis=1)
    mat["any_e2"] = (mat.breadth_e2 > 0).astype(int)
    mat["any_e1"] = (mat.breadth_e1 > 0).astype(int)

    n = len(mat)
    flips = int(((mat.any_e1 == 1) & (mat.any_e2 == 0)).sum())

    # AC-3, verified by INDEPENDENT RECOMPUTATION rather than by re-reading the
    # columns just built. The flags above use EXISTS; this uses a MIN() per
    # (repo, mechanism) and compares. Agreement is only informative because the
    # two formulations are different -- a check that restates its own definition
    # proves nothing.
    con.register("mat_raw", mat[["pr_id", "repo_id", "created_at"] + e2c])
    viol = 0
    for m in MECHS:
        viol += con.execute(f"""
            WITH earliest AS (
                SELECT repo_id, MIN(first_added) AS t0
                FROM a WHERE mechanism = '{m}' GROUP BY repo_id
            )
            SELECT count(*) FROM mat_raw
            LEFT JOIN earliest USING (repo_id)
            WHERE e2_{m[:2]} <> CASE
                WHEN t0 IS NOT NULL AND t0 <= mat_raw.created_at THEN 1 ELSE 0 END
        """).fetchone()[0]

    report = {
        "spec": "001-v2 §5.1 (estimand E2), stratum P only",
        "scope_limit": ("AIDev ships PR-level tables for the pop tier only; E2 "
                        "is not computed for G1-G3."),
        "n_prs": n,
        "n_repos": int(mat.repo_id.nunique()),
        "pr_window": [str(mat.created_at.min()), str(mat.created_at.max())],
        "artifacts_dropped_A2": dropped,
        "per_mechanism": {
            m[:2]: {
                "e2_pct": round(100 * float(mat[f"e2_{m[:2]}"].mean()), 2),
                "e1_pct": round(100 * float(mat[f"e1_{m[:2]}"].mean()), 2),
                "ratio_e1_over_e2": (
                    round(float(mat[f"e1_{m[:2]}"].mean() / mat[f"e2_{m[:2]}"].mean()), 2)
                    if mat[f"e2_{m[:2]}"].mean() else None),
            } for m in MECHS
        },
        "any": {"e2_pct": round(100 * float(mat.any_e2.mean()), 2),
                "e1_pct": round(100 * float(mat.any_e1.mean()), 2)},
        "mean_breadth": {"e2": round(float(mat.breadth_e2.mean()), 2),
                         "e1": round(float(mat.breadth_e1.mean()), 2)},
        "prs_counted_by_e1_but_not_e2": flips,
        "prs_counted_by_e1_but_not_e2_pct": round(100 * flips / n, 1) if n else 0.0,
        "ac3_violations": int(viol),
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"stratum P: {n:,} agentic PRs in {report['n_repos']:,} repositories")
    print(f"window {report['pr_window'][0]} .. {report['pr_window'][1]}\n")
    print(f"{'mech':<6}{'E2 (point-in-time)':>20}{'E1 (present today)':>20}{'ratio':>8}")
    print("-" * 54)
    for m in MECHS:
        d = report["per_mechanism"][m[:2]]
        print(f"{m[:2]:<6}{d['e2_pct']:>19.1f}%{d['e1_pct']:>19.1f}%{d['ratio_e1_over_e2'] or 0:>8.2f}")
    print("-" * 54)
    print(f"{'any':<6}{report['any']['e2_pct']:>19.1f}%{report['any']['e1_pct']:>19.1f}%")
    print(f"{'breadth':<6}{report['mean_breadth']['e2']:>19.2f} {report['mean_breadth']['e1']:>19.2f}")
    print(f"\n{flips:,} PRs ({report['prs_counted_by_e1_but_not_e2_pct']}%) would be "
          f"counted as harnessed by E1 but were NOT harnessed when they were opened.")
    if viol:
        print(f"!! AC-3 VIOLATION: {viol}", file=sys.stderr)
        return 1
    print("AC-3 satisfied: no E2 flag derives from a post-dated artifact.")
    print(f"\nreport -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
