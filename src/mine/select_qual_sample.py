"""Draw the PI-2 qualitative sample (spec 001-v2 §7.2, decision D-v2-9 / D2).

150 repositories, 60/30/30/30 across strata. THE UNIT IS THE REPOSITORY, not the
rule file: a repository with 16 .cursor/rules/*.mdc files is one project, and
sampling files would let it supply 16 observations -- the same inflation that
A2 deduplication removes from the quantitative side (§5).

Allocation is roughly EQUAL across strata rather than proportional, because
comparing content BETWEEN visibility bands is one of the study's questions and a
proportional draw would leave G3 with about ten cases.

Implicit stratification: within each stratum the frame is sorted by corpus-size
tercile x adoption era, then sampled deterministically inside each cell, so the
draw is balanced on file size and on adoption date without a quota table.

NOT stratified by predominant agent, which §7.2 also lists. The agent label
lives in AIDev's PR tables; it is local for stratum P but would need a full
re-read of the remote all_pull_request parquet for G1-G3. Recorded as a
deviation rather than silently dropped -- see the report's `deviations` field.

Deterministic: same revision + same seed -> same 150 repositories.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "qual_sample.csv"
REPORT = ROOT / "data" / "qual_sample_report.json"

SEED = "pi2-150-20260817"
ALLOC = {"P": 60, "G1": 30, "G2": 30, "G3": 30}
CUTOFF = "2025-07-30"  # AIDev PR coverage ends here; splits the adoption eras
STUB_BYTES = 200


def rank(key: str) -> str:
    """Deterministic order, independent of file order and of dict iteration."""
    return hashlib.md5((key + SEED).encode("utf-8")).hexdigest()


def load_candidates() -> list[dict]:
    """One row per repository holding >=1 non-stub rule file."""
    rows = []
    for st in ALLOC:
        raw = ROOT / "data" / f"harness_{st}_raw.json"
        for r in json.loads(raw.read_text(encoding="utf-8")):
            if r["status"] != "cloned":
                continue
            files, seen = [], set()
            for a in r.get("artifacts", []):
                if a["mechanism"] != "H1_context_engineering" or a.get("is_symlink"):
                    continue
                sha = a.get("blob_sha")
                if sha and sha in seen:      # same A2 rule as the quantitative side
                    continue
                if sha:
                    seen.add(sha)
                nb = a.get("bytes") or 0
                if nb < STUB_BYTES and (a.get("normative_clauses") or 0) == 0:
                    continue                 # pointer file: nothing to code
                files.append(a)
            if not files:
                continue
            dates = [a["first_added"] for a in files if a.get("first_added")]
            rows.append({
                "repo_id": r["repo_id"], "full_name": r["full_name"],
                "stratum": st, "stars": r.get("stars"), "language": r.get("language"),
                "agentic_prs": r.get("agentic_prs"),
                "n_rulefiles": len(files),
                "corpus_bytes": sum(a.get("bytes") or 0 for a in files),
                "first_adoption": min(dates) if dates else None,
                "rulefiles": "|".join(a["rulefile"] for a in files if a.get("rulefile")),
                "paths": "|".join(a["path"] for a in files),
            })
    return rows


def draw(cands: list[dict]) -> tuple[list[dict], dict]:
    picked, cells_report = [], {}
    for st, n_target in ALLOC.items():
        pool = [c for c in cands if c["stratum"] == st]
        if len(pool) <= n_target:
            # Not enough material: take everything and say so. Per §7.2 a shortfall
            # is itself a finding about the gradient, never filled in from P.
            picked.extend(pool)
            cells_report[st] = {"pool": len(pool), "drawn": len(pool),
                                "shortfall": n_target - len(pool)}
            continue

        sizes = sorted(c["corpus_bytes"] for c in pool)
        t1, t2 = sizes[len(sizes) // 3], sizes[2 * len(sizes) // 3]

        def cell(c: dict) -> str:
            band = "S" if c["corpus_bytes"] <= t1 else ("M" if c["corpus_bytes"] <= t2 else "L")
            era = "post" if (c["first_adoption"] or "") > CUTOFF else "pre"
            return f"{band}-{era}"

        groups: dict[str, list[dict]] = collections.defaultdict(list)
        for c in pool:
            groups[cell(c)].append(c)

        # Proportional allocation across cells, largest-remainder so the total is
        # exactly n_target rather than n_target +/- rounding.
        exact = {k: n_target * len(v) / len(pool) for k, v in groups.items()}
        alloc = {k: int(v) for k, v in exact.items()}
        for k in sorted(groups, key=lambda k: (-(exact[k] - alloc[k]), k)):
            if sum(alloc.values()) >= n_target:
                break
            alloc[k] += 1

        cells = {}
        for k, members in sorted(groups.items()):
            take = min(alloc[k], len(members))
            chosen = sorted(members, key=lambda c: rank(str(c["repo_id"])))[:take]
            picked.extend(chosen)
            cells[k] = {"pool": len(members), "drawn": take}
        cells_report[st] = {"pool": len(pool), "drawn": sum(c["drawn"] for c in cells.values()),
                            "size_terciles_bytes": [t1, t2], "cells": cells}
    return picked, cells_report


def main() -> int:
    cands = load_candidates()
    picked, cells = draw(cands)
    picked.sort(key=lambda c: (c["stratum"], c["full_name"]))

    fields = ["stratum", "repo_id", "full_name", "stars", "language", "agentic_prs",
              "n_rulefiles", "corpus_bytes", "first_adoption", "paths", "rulefiles"]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(picked)

    by_st = collections.Counter(c["stratum"] for c in picked)
    kb = [c["corpus_bytes"] / 1024 for c in picked]
    report = {
        "spec": "001-v2 §7.2, D-v2-9 (D2)",
        "seed": SEED, "allocation": ALLOC,
        "unit": "repository (whole rule-file corpus is the coding material)",
        "candidates_by_stratum": dict(collections.Counter(c["stratum"] for c in cands)),
        "drawn_by_stratum": dict(by_st),
        "n_drawn": len(picked),
        "n_rulefiles_total": sum(c["n_rulefiles"] for c in picked),
        "corpus_kb": {"median": round(statistics.median(kb), 1),
                      "mean": round(statistics.mean(kb), 1),
                      "max": round(max(kb), 1), "total": round(sum(kb))},
        "cells": cells,
        "deviations": [
            "Not stratified by predominant agent (§7.2 lists it): the agent label "
            "requires a full re-read of the remote all_pull_request parquet for "
            "G1-G3. Implicit stratification covers corpus size and adoption era."
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"candidates: {report['candidates_by_stratum']}")
    print(f"drawn     : {dict(by_st)}  total {len(picked)}")
    print(f"rule files to code: {report['n_rulefiles_total']}   "
          f"corpus median {report['corpus_kb']['median']} KB, "
          f"total {report['corpus_kb']['total']} KB")
    for st, c in cells.items():
        if c.get("shortfall"):
            print(f"  !! {st}: pool {c['pool']} < target -- shortfall {c['shortfall']}, "
                  f"NOT filled from P (§7.2)")
    print(f"\n-> {OUT.relative_to(ROOT)}  /  {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
