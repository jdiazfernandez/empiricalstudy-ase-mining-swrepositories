"""Per-mechanism artifact counts, raw vs. deduplicated (companion to prevalence.py).

prevalence_report.json already reports the aggregate artifacts_kept (35,749)
and artifacts_dropped_A2 (symlink/duplicate_blob/stub/no_date) that main_EMSE.tex
cites in Sec. 4 ("Construccion de la muestra"). Those numbers pool all eight
mechanisms together, which is exactly what caused Res. 4's "35.749 artefactos"
to read as if it meant rule files (H1) specifically -- it doesn't; the count is
dominated by H3 (executable specs / Gherkin *.feature files, which a single
repository can hold hundreds of).

This script reuses build_matrix.dedupe() directly (the same "single source"
A2 rule prevalence.py imports) rather than reimplementing it, so the
per-mechanism breakdown is guaranteed consistent with the already-published
aggregate figures. Reported "kept" counts follow dedupe()'s own semantics:
stub artifacts are flagged (is_stub=True) but not removed from the returned
frame, matching how artifacts_kept is computed upstream.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "features"))
from build_matrix import dedupe  # noqa: E402  (shared A2 dedup rule, single source)

RAW_FILES = [ROOT / "data" / f"harness_{s}_raw.json" for s in ("P", "G1", "G2", "G3")]
OUT = ROOT / "data" / "mechanism_breakdown.json"


def main() -> int:
    recs: list[dict] = []
    for p in RAW_FILES:
        recs.extend(json.loads(p.read_text(encoding="utf-8")))

    raw_by_mech: collections.Counter = collections.Counter()
    for r in recs:
        if r["status"] != "cloned":
            continue
        for a in r["artifacts"]:
            raw_by_mech[a["mechanism"]] += 1

    arts, dropped = dedupe(recs)
    kept_by_mech = arts.groupby("mechanism").size().to_dict()

    mechs = sorted(raw_by_mech, key=lambda m: -raw_by_mech[m])
    report = {
        "raw_by_mechanism": {m: int(raw_by_mech[m]) for m in mechs},
        "kept_by_mechanism": {m: int(kept_by_mech.get(m, 0)) for m in mechs},
        "raw_total": int(sum(raw_by_mech.values())),
        "kept_total": int(len(arts)),
        "dropped": dropped,
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"{report['raw_total']:,} raw -> {report['kept_total']:,} kept "
          f"(dropped: {dropped})")
    for m in mechs:
        print(f"  {m}: {raw_by_mech[m]:,} -> {kept_by_mech.get(m, 0):,}")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
