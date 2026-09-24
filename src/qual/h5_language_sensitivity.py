"""How much of H5's zero is a language artefact, not an absence (C-v2-6 adjacent).

H5 is measured by counting modal clauses with an ENGLISH-ONLY pattern. A rule
file written in Japanese states its obligations in Japanese, matches nothing, and
is recorded as carrying no normative content. The published figure -- 90.9% of
stratum-P repositories with a rule file carry a normative clause -- therefore
has a false-negative floor set by how much of the corpus is not in English.

Rather than detecting language across all 4,145 saved rule files, this targets
the set where the error can actually occur: repositories whose non-stub H1
artifacts ALL score zero normative clauses. An English file with zero modals is
a genuine zero; a non-English one is a measurement failure. The two are
indistinguishable in the published number, and this separates them.

Stub files are examined too. The stub rule discards H1 artifacts under 200 bytes
with zero normative clauses -- so a short non-English rule file is dropped from
the sample entirely, which is a harsher failure than being miscounted.

Run detect_language.py first; this reuses its stripping and classification so the
two reports cannot diverge.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from detect_language import classify, paragraphs  # noqa: E402

RULEFILES = ROOT / "data" / "rulefiles"
CANDS = ROOT / "data" / "h5_zero_candidates.json"
OUT = ROOT / "data" / "h5_language_sensitivity.json"

STUB_BYTES = 200


def stub_files() -> list[tuple[str, str, str, str, int]]:
    """H1 artifacts the stub rule discarded, which are dropped rather than
    miscounted -- the more damaging of the two failure modes."""
    out = []
    for st in ["P", "G1", "G2", "G3"]:
        raw = ROOT / "data" / f"harness_{st}_raw.json"
        for r in json.loads(raw.read_text(encoding="utf-8")):
            if r["status"] != "cloned":
                continue
            seen = set()
            for a in r.get("artifacts", []):
                if a["mechanism"] != "H1_context_engineering" or a.get("is_symlink"):
                    continue
                sha = a.get("blob_sha")
                if sha and sha in seen:
                    continue
                if sha:
                    seen.add(sha)
                if (a.get("bytes", 10**9) < STUB_BYTES
                        and (a.get("normative_clauses") or 0) == 0
                        and a.get("rulefile")):
                    out.append((st, r["full_name"], a["path"], a["rulefile"],
                                a.get("bytes") or 0))
    return out


def analyse(rows, label):
    by_repo: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    langs_file = collections.Counter()
    detail = []
    for st, repo, path, name, nbytes in rows:
        fp = RULEFILES / name
        if not fp.exists():
            continue
        txt = fp.read_text(encoding="utf-8", errors="replace")
        c = classify(paragraphs(txt))
        langs_file[c["dominant"]] += 1
        by_repo[(st, repo)].append(c["dominant"])
        detail.append({"stratum": st, "repository": repo, "path": path,
                       "bytes": nbytes, "dominant": c["dominant"],
                       "n_paragraphs": c["n_paragraphs"]})

    per_repo = {}
    for (st, repo), ls in by_repo.items():
        non_en = [l for l in ls if l not in ("en", "undetermined")]
        per_repo[(st, repo)] = "non_english" if non_en else (
            "undetermined" if all(l == "undetermined" for l in ls) else "english")

    by_st = collections.defaultdict(collections.Counter)
    for (st, repo), v in per_repo.items():
        by_st[st][v] += 1

    print(f"\n=== {label}: {len(detail)} files, {len(per_repo)} repositories ===")
    print("dominant language, per file: "
          + ", ".join(f"{k} {v}" for k, v in langs_file.most_common()))
    # "undetermined" gets its own column and is NOT folded into one "affected"
    # figure. In the zero-clause set it is negligible; in the stub set it
    # dominates, and there it means "too short to classify" -- which is what a
    # stub IS. Summing the two would report the stub rule working as designed as
    # though it were a language failure.
    print(f"\n{'stratum':<9}{'repos':>7}{'english':>9}{'non-eng':>9}{'undet.':>8}{'% non-eng':>11}")
    print("-" * 53)
    for st in ["P", "G1", "G2", "G3"]:
        c = by_st.get(st)
        if not c:
            continue
        n = sum(c.values())
        print(f"{st:<9}{n:>7}{c['english']:>9}{c['non_english']:>9}"
              f"{c['undetermined']:>8}{100*c['non_english']/n:>10.1f}%")
    return {"per_file_language": dict(langs_file),
            "by_stratum": {k: dict(v) for k, v in by_st.items()},
            "detail": detail}


def main() -> int:
    if not CANDS.exists():
        print(
            "ERROR: required candidate file is missing:\n"
            f"  {CANDS.relative_to(ROOT)}\n"
            "This analysis cannot run without the H1 zero-clause candidate "
            "list.\n"
            "No current script in this package generates that file. Create "
            "it first, then rerun:\n"
            "  python src/qual/h5_language_sensitivity.py",
            file=sys.stderr,
        )
        return 2

    try:
        zero = [tuple(x) for x in json.loads(CANDS.read_text(encoding="utf-8"))]
    except (json.JSONDecodeError, OSError) as exc:
        print(
            "ERROR: could not read the H1 zero-clause candidate file:\n"
            f"  {CANDS.relative_to(ROOT)}\n"
            f"Reason: {exc}\n"
            "Fix or regenerate the file, then rerun:\n"
            "  python src/qual/h5_language_sensitivity.py",
            file=sys.stderr,
        )
        return 2

    rep = {"zero_clause_repos": analyse(zero, "H1 present, ZERO normative clauses"),
           "stub_discarded": analyse(stub_files(), "discarded by the stub rule")}

    # --- what it does to h5_given_h1 -----------------------------------------
    # Published: repos with H1 that carry >=1 normative clause, over repos with H1.
    published = {"P": (1271, 1399), "G1": (299, 350), "G2": (194, 236), "G3": (80, 108)}
    print(f"\n=== h5_given_h1, published vs corrected ===")
    print(f"{'stratum':<9}{'published':>11}{'non-eng':>9}{'corrected':>11}"
          f"{'shift':>8}")
    print("-" * 48)
    corrected = {}
    for st, (k, n) in published.items():
        bad = rep["zero_clause_repos"]["by_stratum"].get(st, {})
        nonen = bad.get("non_english", 0) + bad.get("undetermined", 0)
        # Those repositories are not evidence of "no normative content"; the
        # instrument cannot see their clauses. Excluding them from the
        # denominator is the conservative correction -- it does not claim they
        # DO carry norms, only that we cannot say they do not.
        new = 100 * k / (n - nonen) if n - nonen else None
        corrected[st] = {"published_pct": round(100 * k / n, 2),
                         "excluded_non_english": nonen,
                         "corrected_pct": round(new, 2) if new else None}
        print(f"{st:<9}{100*k/n:>10.1f}%{nonen:>9}{new:>10.1f}%"
              f"{new - 100*k/n:>+7.1f}")
    rep["h5_given_h1"] = corrected
    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
