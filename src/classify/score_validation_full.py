"""Score the C6 human validation of the H6 classifier at FULL stratum-P scale
(spec 001 C6, D11) -- `score_validation.py`'s logic, pointed at the full-scale
report/sample/labels instead of the pilot's.

Reads qual/coding/labels_coder*_full.csv (one per coder; the coder id comes
from the CSV's own `coder` column, not the filename). Computes Cohen's kappa
on the reliability overlap when two or more coders are present, same
C6.1-as-amended-by-D3 decision rule as the pilot.

Refuses to report a final decision if any stratum in the sample has fewer
coded items than expected (INCOMPLETE_CODING) -- a partially-coded stratum
would otherwise drop out of the estimate silently rather than being counted
as missing, which can make an incomplete run look deceptively tight.
"""
from __future__ import annotations

import glob
import json
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "consultation_validation_sample_full.csv"
REPORT = ROOT / "data" / "consultation_report_full.json"
LABELS = ROOT / "qual" / "coding"
LABELS_GLOB = "labels_coder*_full.csv"
OUT = ROOT / "data" / "c6_validation_full.json"

ALPHA = 0.05  # one-sided 95%


def p_zero_given_k(N: int, n: int, K: int) -> float:
    """P(draw n from N, see none of the K positives) -- exact hypergeometric."""
    if K <= 0:
        return 1.0
    if N - K < n:
        return 0.0
    p = 1.0
    for i in range(n):
        p *= (N - K - i) / (N - i)
        if p == 0.0:
            return 0.0
    return p


def upper_bound_zero(N: int, n: int) -> int:
    """Largest K with P(observe 0 | K) > ALPHA. The 95% one-sided upper bound."""
    k = 0
    while k < N and p_zero_given_k(N, n, k + 1) > ALPHA:
        k += 1
    return k


def cohens_kappa(a: pd.Series, b: pd.Series) -> float | None:
    cats = sorted(set(a) | set(b))
    n = len(a)
    if n == 0 or len(cats) < 2:
        return None
    po = float((a.values == b.values).mean())
    pe = sum((a == c).mean() * (b == c).mean() for c in cats)
    return None if pe == 1.0 else round((po - pe) / (1 - pe), 3)


def main() -> int:
    files = sorted(glob.glob(str(LABELS / LABELS_GLOB)))
    if not files:
        print(f"No coder files. Expected qual/coding/{LABELS_GLOB}", file=sys.stderr)
        return 2

    coders = {}
    for f in files:
        d = pd.read_csv(f, dtype={"human_label": str})
        cid = str(d.coder.iloc[0])
        coders[cid] = d.set_index("comment_id")
    print(f"coders: {list(coders)}  ({', '.join(pathlib.Path(f).name for f in files)})")

    smp = pd.read_csv(SAMPLE).set_index("comment_id")

    # --- reliability on the overlap, restricted to items in the sample ------
    kappa, overlap_n = None, 0
    ids = list(coders)
    if len(ids) >= 2:
        a, b = coders[ids[0]], coders[ids[1]]
        ov = (a[a.in_overlap == 1].index
              .intersection(b[b.in_overlap == 1].index)
              .intersection(smp.index))
        pair = pd.DataFrame({"a": a.loc[ov, "human_label"], "b": b.loc[ov, "human_label"]}).dropna()
        overlap_n = len(pair)
        if overlap_n:
            kappa = cohens_kappa(pair.a, pair.b)
            print(f"overlap n={overlap_n}  agreement="
                  f"{(pair.a.values == pair.b.values).mean():.3f}  kappa={kappa}")
    else:
        print("WARNING: one coder only. No reliability figure can be reported; "
              "§7.4 commits to two coders.", file=sys.stderr)

    # Gold standard: primary coder, overridden by resolved labels if present.
    gold = coders[ids[0]][["human_label"]].rename(columns={"human_label": "gold"})
    resolved = LABELS / "resolved_full.csv"
    if resolved.exists():
        r = pd.read_csv(resolved, dtype={"human_label": str}).set_index("comment_id")
        gold.loc[gold.index.intersection(r.index), "gold"] = r["human_label"]
        print(f"applied {len(r)} adjudicated labels from resolved_full.csv")

    j_all = smp.join(gold, how="inner")
    j = j_all[j_all.gold.isin(["0", "1"])]  # '?' excluded, reported separately
    unclear = int((j_all.gold == "?").sum())

    # Guard against silently under-counting a stratum: if a stratum has fewer
    # coded items than the sample expects, it either drops out of the
    # groupby below entirely (0 coded) or under-weights the estimate --
    # either way the result is not final. Flag it instead of reporting a
    # number that looks tight but is actually incomplete.
    expected_counts = smp.stratum.value_counts()
    coded_counts = j.stratum.value_counts()
    incomplete_strata = {
        name: {"expected": int(expected_counts[name]), "coded": int(coded_counts.get(name, 0))}
        for name in expected_counts.index
        if coded_counts.get(name, 0) < expected_counts[name]
    }
    if incomplete_strata:
        print(f"\nWARNING: coding incomplete for {list(incomplete_strata)} "
              f"-- {incomplete_strata}. The figures below are NOT final.", file=sys.stderr)

    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    populations = {
        "agent_options_no_ask": int(rep.get("strata_pop", {}).get("agent_options_no_ask", 0)),
        "agent_ask_no_options": int(rep.get("strata_pop", {}).get("agent_ask_no_options", 0)),
        "agent_other": int(rep.get("strata_pop", {}).get("agent_other", 0)),
        "strict": int(rep.get("strata_pop", {}).get("strict", rep["consultations_strict"])),
        "loose_only": int(rep.get("strata_pop", {}).get(
            "loose_only", rep["consultations_loose"] - rep["consultations_strict"])),
    }

    strata, est_total, ub_total = [], 0.0, 0
    for name, grp in j.groupby("stratum"):
        N = populations.get(name, len(grp))
        n = len(grp)
        x = int((grp.gold == "1").sum())
        w = N / n if n else 0.0
        est = x * w
        ub = upper_bound_zero(N, n) if x == 0 else None
        est_total += est
        ub_total += ub if ub is not None else est
        strata.append({"stratum": name, "population": N, "coded": n,
                       "true_consultations": x, "weight": round(w, 2),
                       "estimated_in_stratum": round(est, 1),
                       "upper_bound_95_if_zero": ub})

    pop_total = sum(populations.values())
    tp = int(((j.gold == "1") & (j.consultation_loose == True)).sum())   # noqa: E712
    fp = int(((j.gold == "0") & (j.consultation_loose == True)).sum())   # noqa: E712
    fn = int(((j.gold == "1") & (j.consultation_loose != True)).sum())

    out = {
        "coders": list(coders), "overlap_n": overlap_n, "cohens_kappa": kappa,
        "coded_items": int(len(j)), "unclear_excluded": unclear,
        "classifier_positives": int(rep["consultations_loose"]),
        "confusion_on_coded_sample": {"tp": tp, "fp": fp, "fn": fn},
        "precision": None if (tp + fp) == 0 else round(tp / (tp + fp), 3),
        "recall": None if (tp + fn) == 0 else round(tp / (tp + fn), 3),
        "strata": strata,
        "agent_authored_population": pop_total,
        "estimated_true_consultations": round(est_total, 1),
        "estimated_prevalence_pct": round(100 * est_total / pop_total, 2) if pop_total else None,
        "upper_bound_95_consultations": ub_total,
        "upper_bound_95_prevalence_pct": round(100 * ub_total / pop_total, 2) if pop_total else None,
        "incomplete_strata": incomplete_strata or None,
    }

    # --- C6.1 decision rule, AS AMENDED BY D3 (spec 001-v2 §14) --------------
    MIN_POSITIVES = 10
    KAPPA_MIN, RECALL_MIN = 0.60, 0.70

    k_pos = int((j.gold == "1").sum())
    out["confirmed_positives"] = k_pos
    out["rule"] = (f"C6.1 as amended by D3: branch on confirmed positives "
                   f"(<{MIN_POSITIVES} => recall not estimable)")

    if incomplete_strata:
        decision = "INCOMPLETE_CODING"
        note = (f"Coding is not finished: {incomplete_strata}. The figures above "
                f"omit or under-weight these strata -- they are NOT a valid "
                f"estimate and must not be read as one. Finish coding, then rerun.")
    elif kappa is not None and kappa < KAPPA_MIN:
        decision = "RECODE"
        note = (f"Cohen's kappa {kappa} is below {KAPPA_MIN}: the coding is not "
                f"reliable enough to score. Clarify the codebook, record the "
                f"amendment with its date, and recode the overlap. Do not score.")
    elif k_pos < MIN_POSITIVES:
        decision = "NEAR_ZERO_RECALL_UNESTIMABLE"
        note = (f"{k_pos} confirmed consultation(s) in {len(j)} coded items. "
                f"Below {MIN_POSITIVES} positives, recall cannot be estimated with "
                f"any useful precision and is NOT computed.\n"
                f"Report: prevalence {out['estimated_prevalence_pct']}% with its "
                f"interval (upper bound {out['upper_bound_95_prevalence_pct']}%), "
                f"and state explicitly that the classifier's recall is UNESTIMABLE "
                f"at this prevalence.\n"
                f"Do NOT write that the classifier is adequate: a broken detector "
                f"and an absent phenomenon produce identical output, and this "
                f"design cannot tell them apart.")
    elif out["recall"] is not None and out["recall"] < RECALL_MIN:
        decision = "DROP_H6"
        note = (f"{k_pos} positives, recall {out['recall']} < {RECALL_MIN}. The "
                f"mechanism is real and the rules miss it. Per D11, H6 is DROPPED "
                f"from the study and is NOT replaced by a model -- switching method "
                f"precisely where the construct resists measurement is an "
                f"outcome-contingent change.")
    else:
        decision = "RETAIN_H6"
        note = (f"{k_pos} positives, recall {out['recall']} >= {RECALL_MIN}. H6 "
                f"enters the quantitative work, reported with precision, recall "
                f"and the validation sample size.")

    out["decision"] = decision
    out["decision_note"] = note
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\n" + json.dumps(out, indent=2))

    print("\n--- C6.1 (amended by D3) ---")
    if out["precision"] is None:
        print("Precision is UNDEFINED: the classifier returned no positives. Report it "
              "as undefined; do not print 0.0, which would read as 'always wrong'.\n")
    print(f"decision: {decision}\n{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
