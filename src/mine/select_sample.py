"""Draw the study sample: pop census + stratified sample of the full tier.

Implements spec 001-v2 §4.3 (D-v2-2b). Replaces select_pilot.py, which drew a
10-repository smoke-test sample and is kept only for reproducing the pilot.

Four strata. P is a CENSUS defined by membership in the `repository` table --
NOT by recomputing `stars > 100`, which gives a different set (2,836 vs 2,807):
stars are a snapshot value and move, membership does not.

    P    pop tier, census                      weight 1
    G1   complement, >= 10 stars, n=1000
    G2   complement, 1-9 stars,   n=1000
    G3   complement, 0 stars,     n=1000

Sampling is deterministic: rows are ordered by md5(id || SEED) and the first n
taken. This is stable across DuckDB versions in a way that USING SAMPLE is not,
and it is reproducible from the pinned revision alone.

Writes data/sample_frame.csv (the input to mine_harness.py) and
data/sample_frame_report.json (exact populations, for AC-7 reweighting).
"""
from __future__ import annotations

import json
import pathlib
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[2]
AIDEV = ROOT / "data" / "aidev"
OUT = ROOT / "data" / "sample_frame.csv"
REPORT = ROOT / "data" / "sample_frame_report.json"

SHA = "68ed5f4b80d27a9e057fc57567f38bd322ac73ec"
BASE = f"https://huggingface.co/datasets/hao-li/AIDev/resolve/{SHA}/"

SEED = "001v2-20260817"   # recorded in the report; changing it changes the sample
N_PER_G = 1000

# Local (pop tier, already cached and manifest-checked by AC-1).
POP_REPO = f"read_parquet('{(AIDEV / 'repository.parquet').as_posix()}')"
POP_PR = f"read_parquet('{(AIDEV / 'pull_request.parquet').as_posix()}')"
# Remote (full tier, pinned revision).
ALL_REPO = f"read_parquet('{BASE}all_repository.parquet')"
ALL_PR = f"read_parquet('{BASE}all_pull_request.parquet')"

BANDS = {
    "G1": "a.stars >= 10",
    "G2": "a.stars >= 1 AND a.stars < 10",
    "G3": "a.stars = 0",
}


def main() -> int:
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false;")
    con.execute("INSTALL httpfs; LOAD httpfs;")

    print("stratum P (census, local pop tier) ...", flush=True)
    p = con.execute(f"""
        SELECT r.id AS repo_id, r.full_name, r.language, coalesce(r.stars, 0)::BIGINT AS stars,
               count(*) AS agentic_prs,
               count(DISTINCT pr.agent) AS n_agents,
               min(pr.created_at)::VARCHAR AS first_agentic_pr,
               max(pr.created_at)::VARCHAR AS last_agentic_pr
        FROM {POP_REPO} r JOIN {POP_PR} pr ON pr.repo_id = r.id
        GROUP BY 1,2,3,4
    """).fetchdf()
    p["stratum"] = "P"
    p["weight"] = 1.0
    print(f"  P: {len(p)} repositories (spec §4.3 expects 2,807)")

    # Complement = full tier minus pop membership. Population counts first: the
    # weights are N_h/n_h, so a wrong N silently corrupts every reweighted figure.
    print("full tier: populations per band (remote, ~1 min) ...", flush=True)
    pops = {}
    for band, cond in BANDS.items():
        pops[band] = int(con.execute(f"""
            SELECT count(*) FROM {ALL_REPO} a
            WHERE a.id NOT IN (SELECT id FROM {POP_REPO}) AND {cond}
        """).fetchone()[0])
        print(f"  {band}: population {pops[band]:,}")

    frames = [p]
    for band, cond in BANDS.items():
        print(f"sampling {band} (n={N_PER_G}, seed={SEED!r}) ...", flush=True)
        g = con.execute(f"""
            WITH cand AS (
              SELECT a.id AS repo_id, a.full_name, a.language,
                     coalesce(a.stars, 0)::BIGINT AS stars
              FROM {ALL_REPO} a
              WHERE a.id NOT IN (SELECT id FROM {POP_REPO}) AND {cond}
                AND a.full_name IS NOT NULL
              ORDER BY md5(a.id::VARCHAR || '{SEED}')
              LIMIT {N_PER_G}
            )
            SELECT c.repo_id, c.full_name, c.language, c.stars,
                   count(pr.id) AS agentic_prs,
                   count(DISTINCT pr.agent) AS n_agents,
                   min(pr.created_at)::VARCHAR AS first_agentic_pr,
                   max(pr.created_at)::VARCHAR AS last_agentic_pr
            FROM cand c LEFT JOIN {ALL_PR} pr ON pr.repo_id = c.repo_id
            GROUP BY 1,2,3,4
        """).fetchdf()
        g["stratum"] = band
        g["weight"] = round(pops[band] / len(g), 4) if len(g) else 0.0
        print(f"  {band}: sampled {len(g)}, weight {g.weight.iloc[0]}")
        frames.append(g)

    import pandas as pd
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["stratum", "full_name"]).reset_index(drop=True)
    df.to_csv(OUT, index=False)

    pop_total = len(p) + sum(pops.values())
    rep = {
        "spec": "001-v2 §4.3",
        "revision": SHA,
        "seed": SEED,
        "strata": [
            {"stratum": "P", "definition": "membership in `repository` (pop tier)",
             "population": len(p), "sampled": len(p), "weight": 1.0},
            *[{"stratum": b, "definition": f"complement, {BANDS[b]}",
               "population": pops[b],
               "sampled": int((df.stratum == b).sum()),
               "weight": float(df.loc[df.stratum == b, "weight"].iloc[0])}
              for b in BANDS],
        ],
        "population_total": pop_total,
        "sampled_total": int(len(df)),
        "reweight_formula": "p = sum_h(N_h * p_h) / sum_h(N_h)",
        "activity_filter_sensitivity": {
            "repos_with_ge2_agentic_prs_in_sample": int((df.agentic_prs >= 2).sum()),
            "note": "spec §7.1.1 — every headline figure is reported with and without this filter",
        },
    }
    REPORT.write_text(json.dumps(rep, indent=2), encoding="utf-8")

    print(f"\npopulation total: {pop_total:,}  (spec §4.3 expects 116,211)")
    print(df.groupby("stratum").agg(
        repos=("repo_id", "size"), weight=("weight", "first"),
        median_prs=("agentic_prs", "median"), median_stars=("stars", "median"),
    ).to_string())
    print(f"\nframe  -> {OUT.relative_to(ROOT)}  ({len(df):,} repositories)")
    print(f"report -> {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
