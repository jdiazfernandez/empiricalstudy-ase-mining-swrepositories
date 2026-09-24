"""Language of the rule-file corpora (PI-2 §7.2, and a check on H5).

This is not a curiosity. The H5 detector in src/mine/mine_harness.py counts modal
clauses with an ENGLISH-ONLY pattern (MUST, NEVER, do not, should...). A rule
file written entirely in another language scores zero normative clauses, and if
it is also under 200 bytes the stub rule discards it outright. So the fraction of
non-English corpora bounds a false negative already sitting inside published
figures -- h5_given_h1 at 90.9% in stratum P, and the A2 deduplication counts.

Two precautions, neither theoretical in this material:

  * CODE IS STRIPPED BEFORE DETECTION. A Spanish CLAUDE.md full of `npm run
    build`, file paths and YAML fragments classifies as English on the sheer
    volume of ASCII technical tokens. Without this, non-English content is
    undercounted -- in exactly the direction that would make the problem look
    smaller than it is.
  * DETECTION IS PER PARAGRAPH, AND "MIXED" IS A CATEGORY. A corpus can be
    English prose with a Chinese section, and reporting one label per file would
    erase that. An item is MIXED when at least 10% of its non-empty paragraphs
    detect a language other than its dominant one.

langdetect is seeded (DetectorFactory.seed = 0), which it needs to be: unseeded
it is non-deterministic and the same file can be classified differently between
runs, which would make the figures irreproducible.

Usage:
    py -3.12 src/qual/detect_language.py                 # the 150-item sample
    py -3.12 src/qual/detect_language.py --scope all     # every mined rule file
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RULEFILES = ROOT / "data" / "rulefiles"
SAMPLE = ROOT / "data" / "qual_sample.csv"
KEY = ROOT / "data" / "qual_sample_key.csv"

# langdetect is imported normally (see requirements.txt). Where pip cannot build
# it -- on Windows accounts whose user name contains "$", setuptools expands it
# as a variable while computing install paths and the build aborts -- the wheel
# is unpacked into a directory instead. That fallback is opt-in via
# LANGDETECT_PATH, never a hard-coded path, so this module runs unchanged
# everywhere else.
_fallback = os.environ.get("LANGDETECT_PATH")
if _fallback:
    sys.path.insert(0, _fallback)
try:
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException
except ImportError:  # pragma: no cover
    print("langdetect not importable. Either:\n"
          "  pip install -r requirements.txt\n"
          "or, if pip cannot build it on this machine, unpack the wheel and set\n"
          "  LANGDETECT_PATH=<dir containing the langdetect package>\n"
          "  https://pypi.org/project/langdetect/#files", file=sys.stderr)
    raise
DetectorFactory.seed = 0

MIXED_THRESHOLD = 0.10   # share of paragraphs in a non-dominant language
MIN_PARA_CHARS = 25      # below this, detection is noise

# --- stripping ---------------------------------------------------------------
FENCED = re.compile(r"^```.*?^```", re.S | re.M)
FENCED2 = re.compile(r"^~~~.*?^~~~", re.S | re.M)
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
INDENTED = re.compile(r"^(?: {4,}|\t).*$", re.M)
INLINE = re.compile(r"`[^`\n]*`")
HTMLTAG = re.compile(r"<[^>\n]{1,120}>")
URL = re.compile(r"https?://\S+|www\.\S+")
# A path-like token: has a slash and no spaces, or a dotted filename.
PATHY = re.compile(r"\S*[/\\][^\s]*|\b[\w-]+\.(?:md|json|ya?ml|toml|js|ts|tsx|jsx|py|go|rs|java|sh|lock|cfg|ini|txt|xml|html|css)\b")
CLIFLAG = re.compile(r"(?<!\w)--?[a-zA-Z][\w-]*")
MDLINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")   # keep the label, drop the target
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
HEADING = re.compile(r"^#{1,6}\s*", re.M)
TABLEROW = re.compile(r"^\s*\|?[\s:|-]{6,}\|?\s*$", re.M)  # table rules |---|---|


def strip_code(text: str) -> str:
    t = FRONTMATTER.sub(" ", text)
    t = FENCED.sub(" ", t)
    t = FENCED2.sub(" ", t)
    t = INDENTED.sub(" ", t)
    t = MDLINK.sub(r"\1", t)
    t = URL.sub(" ", t)
    t = INLINE.sub(" ", t)
    t = HTMLTAG.sub(" ", t)
    t = PATHY.sub(" ", t)
    t = CLIFLAG.sub(" ", t)
    t = TABLEROW.sub(" ", t)
    t = HEADING.sub("", t)
    t = BULLET.sub("", t)
    return t


def paragraphs(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", strip_code(text)):
        p = re.sub(r"\s+", " ", block).strip()
        if len(p) >= MIN_PARA_CHARS:
            out.append(p)
    return out


def detect(p: str) -> str:
    try:
        return detect_langs(p)[0].lang
    except (LangDetectException, IndexError):
        return "unknown"


def classify(paras: list[str]) -> dict:
    """Dominant language weighted by characters, plus the mixed test."""
    if not paras:
        return {"dominant": "undetermined", "mixed": False, "n_paragraphs": 0,
                "distribution": {}}
    langs = [detect(p) for p in paras]
    by_chars: dict[str, int] = collections.Counter()
    for p, l in zip(paras, langs):
        by_chars[l] += len(p)
    dominant = max(by_chars, key=by_chars.get)
    counts = collections.Counter(langs)
    other = sum(v for k, v in counts.items() if k != dominant)
    return {
        "dominant": dominant,
        "mixed": other / len(paras) >= MIXED_THRESHOLD,
        "n_paragraphs": len(paras),
        "share_non_dominant": round(other / len(paras), 3),
        "distribution": dict(counts),
        "chars_by_lang": dict(by_chars),
    }


def sample_rows() -> list[dict]:
    rows = list(csv.DictReader(SAMPLE.open(encoding="utf-8")))
    key = {}
    if KEY.exists():
        key = {r["full_name"]: r for r in csv.DictReader(KEY.open(encoding="utf-8"))}
    out = []
    for r in rows:
        names = [n for n in (r["rulefiles"] or "").split("|") if n]
        paths = [p for p in (r["paths"] or "").split("|") if p]
        k = key.get(r["full_name"], {})
        out.append({"item_id": k.get("item_id", ""), "full_name": r["full_name"],
                    "stratum": r["stratum"], "files": list(zip(paths, names))})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["sample", "all"], default="sample")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    per_file, per_item = [], []
    if args.scope == "sample":
        rows = sample_rows()
        for r in rows:
            all_paras = []
            for path, name in r["files"]:
                fp = RULEFILES / name
                if not fp.exists():
                    continue
                txt = fp.read_text(encoding="utf-8", errors="replace")
                paras = paragraphs(txt)
                all_paras.extend(paras)
                c = classify(paras)
                per_file.append({"item_id": r["item_id"], "stratum": r["stratum"],
                                 "repository": r["full_name"], "path": path,
                                 "bytes": len(txt.encode("utf-8")), **c})
            c = classify(all_paras)
            per_item.append({"item_id": r["item_id"], "stratum": r["stratum"],
                             "repository": r["full_name"],
                             "n_files": len(r["files"]), **c})
    else:
        for fp in sorted(RULEFILES.glob("*")):
            if not fp.is_file():
                continue
            txt = fp.read_text(encoding="utf-8", errors="replace")
            c = classify(paragraphs(txt))
            per_file.append({"rulefile": fp.name,
                             "bytes": len(txt.encode("utf-8")), **c})

    # ---- report --------------------------------------------------------------
    print(f"scope: {args.scope}   files: {len(per_file)}"
          + (f"   items: {len(per_item)}" if per_item else ""))

    fl = collections.Counter(f["dominant"] for f in per_file)
    print(f"\n--- dominant language, per FILE (n={len(per_file)}) ---")
    for lang, n in fl.most_common():
        print(f"   {lang:<14}{n:>5}  {100*n/len(per_file):>5.1f}%")

    report: dict = {"scope": args.scope, "mixed_threshold": MIXED_THRESHOLD,
                    "min_paragraph_chars": MIN_PARA_CHARS,
                    "per_file_dominant": dict(fl)}

    if per_item:
        il = collections.Counter(i["dominant"] for i in per_item)
        n_mixed = sum(1 for i in per_item if i["mixed"])
        print(f"\n--- dominant language, per ITEM (n={len(per_item)}) ---")
        for lang, n in il.most_common():
            print(f"   {lang:<14}{n:>5}  {100*n/len(per_item):>5.1f}%")
        print(f"\nmixed items (>={int(100*MIXED_THRESHOLD)}% of paragraphs in a "
              f"non-dominant language): {n_mixed} of {len(per_item)}")

        print(f"\n--- by stratum ---")
        print(f"{'stratum':<9}{'n':>4}{'english':>9}{'non-eng':>9}{'mixed':>7}"
              f"{'undet.':>8}   languages present")
        print("-" * 78)
        by_st: dict[str, list[dict]] = collections.defaultdict(list)
        for i in per_item:
            by_st[i["stratum"]].append(i)
        strat: dict = {}
        for st in ["P", "G1", "G2", "G3"]:
            g = by_st.get(st, [])
            if not g:
                continue
            en = sum(1 for i in g if i["dominant"] == "en")
            und = sum(1 for i in g if i["dominant"] == "undetermined")
            non = len(g) - en - und
            mx = sum(1 for i in g if i["mixed"])
            langs = sorted({i["dominant"] for i in g if i["dominant"] not in ("en", "undetermined")})
            strat[st] = {"n": len(g), "english": en, "non_english": non,
                         "mixed": mx, "undetermined": und, "languages": langs}
            print(f"{st:<9}{len(g):>4}{en:>9}{non:>9}{mx:>7}{und:>8}   "
                  + (", ".join(langs) if langs else "-"))
        report["per_item_dominant"] = dict(il)
        report["mixed_items"] = n_mixed
        report["by_stratum"] = strat

        non_en = [i for i in per_item if i["dominant"] not in ("en", "undetermined")]
        if non_en:
            print(f"\n--- non-English items ({len(non_en)}) ---")
            for i in sorted(non_en, key=lambda x: x["item_id"]):
                print(f"   {i['item_id']}  {i['dominant']:<6} "
                      f"{i['stratum']:<3} {i['n_paragraphs']:>3} paras  "
                      f"{'MIXED' if i['mixed'] else ''}   {i['repository']}")
        report["non_english_items"] = [
            {k: i[k] for k in ("item_id", "repository", "stratum", "dominant",
                               "mixed", "n_paragraphs", "distribution")}
            for i in non_en]
        report["per_item"] = per_item

    report["per_file"] = per_file
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "data" / f"language_report_{args.scope}.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
