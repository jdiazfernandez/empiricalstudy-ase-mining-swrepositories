"""PI-1: prevalence, co-occurrence and adoption curves (spec 001-v2 §7.1).

Estimand E1 -- "the artifact exists in the repository's current HEAD" -- which
§5.1 makes the headline figure for PI-1. E2 (presence at PR creation time) is
PR-level and stays in src/features/build_matrix.py.

Reporting rules this file enforces, because they are easy to get wrong:

  * AC-7: any figure spanning more than one stratum is REWEIGHTED by N_h/n_h.
    An unweighted pooled mean would treat 1,000 zero-star repositories as if
    they represented 93,798.
  * The per-stratum table is the primary result, not the pooled estimate: the
    comparison across star bands IS the finding (HYP-D).
  * §7.1.1: every headline figure is also reported restricted to repositories
    with >= 2 agentic PRs, so the long tail of single-PR projects is visible
    rather than silently included.
  * AC-6: a mechanism that returns zero is reported as a measured zero only
    because tests/test_detectors.py proves the detector fires on synthetic data.

C7 is moot in v2 -- there are no outcome variables in this study at all.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "features"))
from build_matrix import dedupe  # noqa: E402  (shared A2 dedup rule, single source)

FRAME = ROOT / "data" / "sample_frame.csv"
OUT = ROOT / "data" / "prevalence_report.json"

# Artifact-bearing mechanisms. H5 is content-derived (below) and H6 comes from
# the consultation classifier, which needs PR comments and so exists only in
# stratum P (§4.1). Breadth is therefore 0-6 in G and 0-7 in P.
ARTIFACT_MECHS = [
    "H1_context_engineering", "H2_persistent_knowledge", "H3_executable_specs",
    "H7_evidence_acceptance", "H8_graduated_autonomy",
]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Correct near 0, which is where several of these
    proportions live; the normal approximation is not."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(100 * max(0.0, (c - r) / d), 2), round(100 * min(1.0, (c + r) / d), 2))


def repo_table(recs: list[dict], arts: pd.DataFrame, keep_stubs: bool) -> pd.DataFrame:
    """One row per successfully cloned repository, one column per mechanism."""
    if arts.empty:  # a stratum can legitimately yield no artifacts at all
        arts = pd.DataFrame(columns=["repo_id", "mechanism", "is_stub",
                                     "normative_clauses", "first_added"])
    a = arts if keep_stubs else arts[~arts.is_stub.astype(bool)]
    present = collections.defaultdict(set)
    for repo_id, mech in zip(a.repo_id, a.mechanism):
        present[int(repo_id)].add(mech)

    # H5 (normative specifications) is a property of rule-file CONTENT, not of a
    # path: a repository has it when at least one non-stub rule file carries a
    # standing norm. Counting H1 twice would inflate breadth for free.
    h1 = a[(a.mechanism == "H1_context_engineering") & (a.normative_clauses.fillna(0) > 0)]
    h5_repos = set(int(x) for x in h1.repo_id)

    rows = []
    for r in recs:
        if r["status"] != "cloned":
            continue
        rid = int(r["repo_id"])
        row = {
            "repo_id": rid, "full_name": r["full_name"], "stratum": r.get("stratum"),
            "weight": float(r.get("weight") or 1.0), "stars": r.get("stars"),
            "language": r.get("language"), "agentic_prs": int(r.get("agentic_prs") or 0),
        }
        for m in ARTIFACT_MECHS:
            row[m[:2]] = int(m in present[rid])
        row["H5"] = int(rid in h5_repos)
        row["breadth"] = sum(row[m] for m in MECHS)
        rows.append(row)
    return pd.DataFrame(rows)


# D-v2-8: H5 is NOT here. Measured on the P census, cooccurrence(H1,H5) == k(H5)
# exactly -- H5 is derived from the content of H1 artifacts, so it cannot occur
# without H1. It is a property of H1, not an independent mechanism, and counting
# it in breadth adds the same artifact twice. Reported instead as h5_given_h1.
MECHS = ["H1", "H2", "H3", "H7", "H8"]


def prevalence_block(df: pd.DataFrame, populations: dict[str, int]) -> dict:
    """Per-stratum prevalence plus the AC-7 reweighted pooled estimate."""
    out: dict = {"by_stratum": {}, "pooled_weighted": {}, "n_repos": int(len(df))}
    for st, g in df.groupby("stratum", dropna=False):
        h1 = g[g.H1 == 1]  # D-v2-8: H5 is only meaningful conditioned on H1
        out["by_stratum"][str(st)] = {
            "n": int(len(g)),
            "population": populations.get(str(st)),
            **{m: {"k": int(g[m].sum()),
                   "pct": round(100 * g[m].mean(), 2),
                   "ci95": wilson(int(g[m].sum()), len(g))} for m in MECHS},
            "mean_breadth": round(float(g.breadth.mean()), 2),
            "any": round(100 * float((g.breadth > 0).mean()), 2),
            "h5_given_h1": {
                "n_h1": int(len(h1)), "k": int(h1.H5.sum()),
                "pct": round(100 * float(h1.H5.mean()), 2) if len(h1) else None,
                "ci95": wilson(int(h1.H5.sum()), len(h1)),
            },
        }
    # p = sum_h(N_h * p_h) / sum_h(N_h)  -- §4.3
    tot_N = sum(populations.get(str(st), 0) for st in df.stratum.unique())
    if tot_N:
        for m in MECHS + ["_any"]:
            num = 0.0
            for st, g in df.groupby("stratum", dropna=False):
                N = populations.get(str(st), 0)
                p = float((g.breadth > 0).mean()) if m == "_any" else float(g[m].mean())
                num += N * p
            out["pooled_weighted"][m] = round(100 * num / tot_N, 2)
        num = sum(populations.get(str(st), 0) * float(g.breadth.mean())
                  for st, g in df.groupby("stratum", dropna=False))
        out["pooled_weighted"]["mean_breadth"] = round(num / tot_N, 2)
        out["population_total"] = tot_N
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", nargs="+", required=True,
                    help="harness_<stratum>_raw.json files")
    args = ap.parse_args()

    recs: list[dict] = []
    for p in args.raw:
        text = pathlib.Path(p).read_text(encoding="utf-8")
        if p.endswith(".jsonl"):
            # Partial results from a run still in flight: the checkpoint is
            # append-only, so reading it mid-run is safe apart from a possibly
            # truncated last line. Useful precisely during a multi-hour mine.
            for line in text.splitlines():
                if line.strip():
                    try:
                        recs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        else:
            recs.extend(json.loads(text))

    # Stratum/weight live in the frame; the raw records carry them too, but the
    # frame is authoritative because it is what the sampling design wrote.
    if FRAME.exists():
        frame = pd.read_csv(FRAME).set_index("full_name")
        for r in recs:
            if r["full_name"] in frame.index:
                r["stratum"] = frame.loc[r["full_name"], "stratum"]
                r["weight"] = float(frame.loc[r["full_name"], "weight"])

    populations = {}
    rep_path = ROOT / "data" / "sample_frame_report.json"
    if rep_path.exists():
        for s in json.loads(rep_path.read_text(encoding="utf-8"))["strata"]:
            populations[s["stratum"]] = s["population"]

    # --- AC-2 attrition, per stratum (never aggregated: §12) -----------------
    attrition: dict = {}
    for r in recs:
        st = str(r.get("stratum"))
        attrition.setdefault(st, collections.Counter())[r["status"]] += 1
    attrition = {k: dict(v) for k, v in attrition.items()}

    arts, dropped = dedupe(recs)
    df = repo_table(recs, arts, keep_stubs=False)

    report = {
        "spec": "001-v2 §7.1 (PI-1, estimand E1)",
        "inputs": args.raw,
        "attrition_by_stratum": attrition,
        "artifacts_kept": int(len(arts)),
        "artifacts_dropped_A2": dropped,
        "prevalence": prevalence_block(df, populations),
        "sensitivity_stubs_kept": prevalence_block(
            repo_table(recs, arts, keep_stubs=True), populations),
        "sensitivity_ge2_agentic_prs": prevalence_block(
            df[df.agentic_prs >= 2], populations),
        "breadth_distribution": {
            str(st): g.breadth.value_counts().sort_index().to_dict()
            for st, g in df.groupby("stratum", dropna=False)
        },
        # H5 is kept in the matrix even though it left the table: the identity
        # cooccurrence(H1,H5) == k(H5) is the audit trail for D-v2-8, and the
        # same check is what should be run on any future mechanism.
        "cooccurrence": {
            f"{a}&{b}": int(((df[a] == 1) & (df[b] == 1)).sum())
            for i, a in enumerate(MECHS + ["H5"])
            for b in (MECHS + ["H5"])[i + 1:]
        },
        "d_v2_8_check": {
            "k_H5": int(df.H5.sum()),
            "cooc_H1_H5": int(((df.H1 == 1) & (df.H5 == 1)).sum()),
            "h5_without_h1": int(((df.H1 == 0) & (df.H5 == 1)).sum()),
            "note": "h5_without_h1 must be 0: H5 is derived from H1 content.",
        },
    }

    # --- adoption curve: month of first appearance, per mechanism (HYP-C) ----
    if len(arts):
        ad = arts.copy()
        ad["month"] = (pd.to_datetime(ad.first_added, utc=True, format="mixed")
                       .dt.tz_convert(None).dt.to_period("M"))
        curve = (ad[ad.mechanism == "H1_context_engineering"]
                 .groupby("month").size().sort_index())
        report["h1_first_appearance_by_month"] = {str(k): int(v) for k, v in curve.items()}
        cutoff = pd.Timestamp("2025-07-30T19:36:13Z")
        post = pd.to_datetime(ad[ad.mechanism == "H1_context_engineering"].first_added,
                              utc=True, format="mixed") > cutoff
        report["hyp_c_h1_after_aidev_cutoff"] = {
            "n_after": int(post.sum()), "n_total": int(len(post)),
            "pct": round(100 * float(post.mean()), 1) if len(post) else None,
            "note": "spec §3 HYP-C; pilot value was 55.6%",
        }

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    # --- console summary -----------------------------------------------------
    print(f"repos cloned: {len(df):,}   artifacts kept: {len(arts):,}   dropped: {dropped}")
    print(f"attrition by stratum: {attrition}\n")
    hdr = f"{'stratum':<8}{'n':>7}  " + "".join(f"{m:>9}" for m in MECHS) + f"{'any':>9}{'breadth':>9}"
    print(hdr); print("-" * len(hdr))
    for st, b in report["prevalence"]["by_stratum"].items():
        print(f"{st:<8}{b['n']:>7}  " + "".join(f"{b[m]['pct']:>8.1f}%" for m in MECHS)
              + f"{b['any']:>8.1f}%{b['mean_breadth']:>9.2f}")
    pw = report["prevalence"].get("pooled_weighted")
    if pw:
        print("-" * len(hdr))
        print(f"{'pooled':<8}{'(wtd)':>7}  " + "".join(f"{pw[m]:>8.1f}%" for m in MECHS)
              + f"{pw['_any']:>8.1f}%{pw['mean_breadth']:>9.2f}")
    print("\nH5 (D-v2-8), conditioned on H1 -- not a row above:")
    for st, b in report["prevalence"]["by_stratum"].items():
        h = b["h5_given_h1"]
        print(f"  {st}: {h['k']}/{h['n_h1']} repos with a rule file carry a "
              f"normative clause = {h['pct']}%  CI95 {h['ci95']}")
    chk = report["d_v2_8_check"]
    if chk["h5_without_h1"]:
        print(f"  !! {chk['h5_without_h1']} repos have H5 without H1 -- "
              f"D-v2-8's premise no longer holds, revisit the decision",
              file=sys.stderr)
    if "hyp_c_h1_after_aidev_cutoff" in report:
        h = report["hyp_c_h1_after_aidev_cutoff"]
        print(f"\nHYP-C: {h['n_after']}/{h['n_total']} ({h['pct']}%) H1 artifacts "
              f"first appear AFTER the AIDev cutoff")
    print(f"\nreport -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
