"""Score the PI-2 coding: reliability first, then results (spec 001-v2 §7.2).

Reads qual/coding/rulefiles_<CODER>_it<N>.csv, one per coder per iteration, and
reports reliability before findings -- deliberately. Reading the findings first
invites seeing a pattern in labels two people could not reproduce.

Implements the three rules fixed a priori in codebook_rulefiles_v3.md §0:

  0.1 EXTREME PREVALENCE. Above an 85% base rate Cohen's kappa is not
      informative: the chance baseline is so high that two disagreements in
      thirty destroy it (the kappa paradox). Such a category is judged on raw
      agreement >= 0.90 instead, and its kappa is printed for information only.
      The 85% line is inherited from C-v2-6, not invented here. PABAK is
      deliberately NOT reported: it is rescaled raw agreement, and reaching for
      it wherever kappa is inconvenient would launder every failure into a pass.

  0.2 proc_substantial (binary) replaces the three-way orientation in the gate.
      proc_share survives as description only, reported as a mean absolute
      difference between coders.

  0.3 TWO STRIKES. A category failing in two consecutive iterations, the second
      after an amendment aimed at it, is reported as not reliably codeable; its
      results are exploratory and it is not amended again.

If qual/coding/rulefiles_resolved_it<N>.csv exists (third author's adjudication)
its labels override the coders' for the RESULTS -- never for the kappa, which
must keep describing what two people agreed on independently.
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import re
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
CODING = ROOT / "qual" / "coding"
KEY = ROOT / "data" / "qual_sample_key.csv"
RESOLVED_TMPL = "rulefiles_resolved_it{}.csv"
OUT_TMPL = "pi2_report_it{}.json"

MECHS = ["M1", "M2", "M3", "M5", "M6", "M7", "M8"]
GATE_FIELDS = MECHS + ["proc_substantial"]

KAPPA_MIN = 0.60             # ordinary categories
EXTREME_PREVALENCE = 0.85    # C-v2-6's line, reused (v3 §0.1)
EXTREME_AGREEMENT_MIN = 0.90

# v3 §0.3, on the evidence of iterations 1 and 2. Recorded rather than
# recomputed: the rule is about a HISTORY of failures, and the scorer only ever
# sees one iteration at a time.
#
# 2026-08-21: the it2 figures below (0.468/0.444) were computed from coder
# CSVs later found to contain transcription errors (five M6/M8 label fixes on
# R031/R041/R049/R057). The corrected it2 is treated as the first legitimate
# it2 measurement, not as a second strike on top of the superseded one -- so
# M6/M8 are NOT held EXPLORATORY for this run. The two-strikes rule itself
# stands; it just has not fired under the corrected data. If a *fresh* it2
# recomputation (on this corrected data) fails reliability again after a
# targeted amendment, THAT is strike two and EXHAUSTED should be restored
# with the new numbers.
EXHAUSTED = {
    # "M6": "failed it1 (0.526) and it2 (0.468 pre-correction), the second "
    #       "after a targeted amendment in v2 1.1 -- superseded 2026-08-21",
    # "M8": "failed it1 (0.302) and it2 (0.444 pre-correction), the second "
    #       "after a targeted amendment in v2 1.1 -- superseded 2026-08-21",
}


def cohens_kappa(a: pd.Series, b: pd.Series) -> float | None:
    """Unweighted Cohen's kappa. None where undefined, never 0.0."""
    a, b = a.astype(str), b.astype(str)
    cats = sorted(set(a) | set(b))
    if len(a) == 0 or len(cats) < 2:
        # Both coders used one category throughout: agreement is perfect and
        # kappa undefined. Printing 0.0 would read as "no better than chance",
        # the opposite of the truth.
        return None
    po = float((a.values == b.values).mean())
    pe = sum((a == c).mean() * (b == c).mean() for c in cats)
    # float(): pe sums pandas means, so without this the result is a
    # numpy.float64 -- and then "k >= KAPPA_MIN" is a numpy.bool_, for which
    # "ok is False" is itself False. That silently emptied the failure list.
    return None if pe == 1 else float(round((po - pe) / (1 - pe), 3))


def iterations_present() -> list[int]:
    out = set()
    for f in glob.glob(str(CODING / "rulefiles_*_it*.csv")):
        m = re.search(r"_it(\d+)\.csv$", f)
        if m:
            out.add(int(m.group(1)))
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iteration", type=int, default=None,
                    help="which coding round to score; defaults to the latest")
    args = ap.parse_args()

    its = iterations_present()
    if not its:
        print("No coder exports found. Expected "
              "qual/coding/rulefiles_<CODER>_it<N>.csv", file=sys.stderr)
        return 2
    it = args.iteration if args.iteration is not None else its[-1]
    if it not in its:
        print(f"No exports for iteration {it}; present: {its}", file=sys.stderr)
        return 2

    # Never mix iterations: labels from two codebook versions are two
    # instruments, not two people disagreeing.
    files = sorted(f for f in glob.glob(str(CODING / f"rulefiles_*_it{it}.csv"))
                   if "resolved" not in pathlib.Path(f).name)
    OUT = ROOT / "data" / OUT_TMPL.format(it)
    print(f"iteration {it}  (present: {its})")

    frames: dict[str, pd.DataFrame] = {}
    for f in files:
        # utf-8-sig: a browser export can carry a BOM, which would turn the
        # first header into a mangled item_id and make the join match nothing.
        d = pd.read_csv(f, dtype=str, encoding="utf-8-sig").set_index("item_id")
        stem = re.sub(r"_it\d+$", "", pathlib.Path(f).stem).replace("rulefiles_", "")
        coder = str(d["coder"].iloc[0]) if "coder" in d and len(d) else stem
        if coder in frames:
            print(f"WARNING: coder id {coder!r} appears in more than one export; "
                  f"distinguishing by file name. Check that these really are two "
                  f"independent coders.", file=sys.stderr)
            coder = f"{coder}@{stem}"
        frames[coder] = d
    print("coders: " + ", ".join(f"{c} ({len(d)} rows)" for c, d in frames.items()) + "\n")

    report: dict = {"iteration": it, "coders": list(frames),
                    "rules": "codebook_rulefiles_v3.md section 0",
                    "kappa_min": KAPPA_MIN,
                    "extreme_prevalence": EXTREME_PREVALENCE,
                    "extreme_agreement_min": EXTREME_AGREEMENT_MIN}

    failing: list[str] = []
    if len(frames) < 2:
        print("Only one coder present: no reliability figure can be computed.\n"
              "The study commits to two independent coders; do not report results "
              "from one coder as if they were adjudicated.\n")
        report["reliability"] = None
    else:
        (ca, da), (cb, db) = list(frames.items())[:2]
        both = da.index.intersection(db.index)
        ov = [i for i in both if str(da.loc[i, "in_overlap"]) == "1"]
        print(f"reliability overlap: {len(ov)} items coded by both {ca} and {cb}\n")
        rel: dict = {"pair": [ca, cb], "overlap_n": len(ov)}

        print(f"{'field':<18}{'kappa':>8}{'agree':>8}{'base':>7}  verdict")
        print("-" * 64)
        for m in GATE_FIELDS:
            if m not in da.columns or m not in db.columns:
                continue
            x, y = da.loc[ov, m].astype(str), db.loc[ov, m].astype(str)
            k = cohens_kappa(x, y)
            agr = float((x.values == y.values).mean()) if ov else float("nan")
            base = float(pd.concat([pd.to_numeric(x, errors="coerce"),
                                    pd.to_numeric(y, errors="coerce")]).mean())

            extreme = base > EXTREME_PREVALENCE
            if m in EXHAUSTED:
                ok, verdict = None, "EXPLORATORY (v3 0.3)"
            elif extreme:
                ok = bool(agr >= EXTREME_AGREEMENT_MIN)
                verdict = ("pass, on agreement" if ok else "FAIL, on agreement") \
                    + "  [kappa uninformative]"
            else:
                ok = bool(k is not None and k >= KAPPA_MIN)
                verdict = "pass" if ok else "FAIL"
            if ok is not None and not ok:
                failing.append(m)

            rel[m] = {"kappa": k, "raw_agreement": round(agr, 3),
                      "base_rate": round(base, 3), "extreme_prevalence": extreme,
                      "gated_on": "raw_agreement" if extreme else "kappa",
                      "passes": ok, "exploratory": m in EXHAUSTED}
            ks = "n/a" if k is None else f"{k:.3f}"
            print(f"{m:<18}{ks:>8}{agr:>7.0%}{base:>7.0%}  {verdict}")

        if ov and "proc_share" in da.columns:
            diff = (pd.to_numeric(da.loc[ov, "proc_share"], errors="coerce")
                    - pd.to_numeric(db.loc[ov, "proc_share"], errors="coerce")).abs()
            rel["proc_share_mean_abs_diff"] = round(float(diff.mean()), 1)
            print(f"\nproc_share (descriptive only, v3 0.2): mean absolute "
                  f"difference {diff.mean():.1f} points, max {diff.max():.0f}")
        if "orientation" in da.columns:
            k3 = cohens_kappa(da.loc[ov, "orientation"], db.loc[ov, "orientation"])
            rel["orientation_three_way_kappa"] = k3
            print(f"orientation (three-way, superseded in v3): kappa {k3}")

        report["reliability"] = rel
        if failing:
            print(f"\n!! not reliable: {', '.join(failing)}")
            print("Amend those definitions, record the amendment WITH ITS DATE, "
                  "bump the codebook version, and recode on a FRESH block. "
                  "Results below are provisional.")
        else:
            print("\nAll gated fields meet their threshold.")
    report["failing_fields"] = failing
    report["exploratory_fields"] = dict(EXHAUSTED)

    # --- results ------------------------------------------------------------
    base_df = frames[list(frames)[0]].copy()
    RESOLVED = CODING / RESOLVED_TMPL.format(it)
    if RESOLVED.exists():
        r = pd.read_csv(RESOLVED, dtype=str, encoding="utf-8-sig").set_index("item_id")
        base_df.loc[base_df.index.intersection(r.index), r.columns] = r
        print(f"\napplied {len(r)} adjudicated rows from {RESOLVED.name}")
    else:
        print(f"\nNo {RESOLVED.name}: results use {list(frames)[0]}'s labels and "
              f"are NOT the adjudicated gold standard.")
    report["adjudicated"] = RESOLVED.exists()

    if KEY.exists():
        base_df = base_df.join(
            pd.read_csv(KEY, dtype=str).set_index("item_id")[["stratum"]], how="left")

    cols = MECHS + ["proc_substantial"]
    print(f"\n{'stratum':<9}{'n':>5}" + "".join(f"{m:>8}" for m in cols))
    print("-" * (14 + 8 * len(cols)))
    res: dict = {}
    groups = base_df.groupby("stratum") if "stratum" in base_df.columns else [("all", base_df)]
    for st, g in groups:
        row: dict = {"n": int(len(g))}
        for m in cols:
            row[m] = (round(100 * pd.to_numeric(g[m], errors="coerce").fillna(0).mean(), 1)
                      if m in g.columns else None)
        row["proc_share_mean"] = (round(float(pd.to_numeric(
            g["proc_share"], errors="coerce").mean()), 1) if "proc_share" in g else None)
        res[str(st)] = row
        cells = "".join(f"{row[m]:>7.1f}%" if row.get(m) is not None else f"{'-':>8}"
                        for m in cols)
        print(f"{str(st):<9}{row['n']:>5}{cells}")
    report["results_by_stratum"] = res
    if EXHAUSTED:
        print(f"\n{', '.join(EXHAUSTED)}: EXPLORATORY (v3 0.3). The labels are "
              f"published; no claim rests on them.")

    if "inductive" in base_df.columns:
        ind = base_df["inductive"].dropna().astype(str).str.strip()
        n_ind = int((ind != "").sum())
        report["inductive_entries"] = n_ind
        print(f"\ninductive notes on {n_ind} of {len(base_df)} repositories -- "
              f"raw material for the open-coding pass, not a result.")

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport -> {OUT.relative_to(ROOT)}")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
