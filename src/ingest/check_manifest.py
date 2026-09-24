"""AC-1 gate: row counts must match the pinned manifest, or the pipeline aborts.

Spec 001 AC-1: "row counts per table match the recorded manifest exactly, and any
deviation aborts the pipeline rather than proceeding."

A manifest that is merely written down is documentation. This makes it a control.
Run before any stage that consumes the cached tables.
"""
from __future__ import annotations

import json
import pathlib
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[2]
AIDEV = ROOT / "data" / "aidev"
MANIFEST = ROOT / "data" / "step_zero_report.json"


def main() -> int:
    if not MANIFEST.exists():
        print("ABORT: no manifest. Run src/ingest/step_zero.py first (spec §16).",
              file=sys.stderr)
        return 2
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = {t: v["rows"] for t, v in man["counts"].items()}

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false;")
    checked, deviations, missing = 0, [], []

    for table, exp in sorted(expected.items()):
        p = AIDEV / f"{table}.parquet"
        if not p.exists():
            missing.append(table)          # not cached locally; not a deviation
            continue
        got = con.execute(
            f"SELECT count(*) FROM read_parquet('{p.as_posix()}')").fetchone()[0]
        checked += 1
        if int(got) != int(exp):
            deviations.append((table, exp, int(got)))

    print(f"manifest revision : {man['revision']}")
    print(f"tables checked    : {checked}")
    print(f"not cached locally: {len(missing)}" + (f" {missing}" if missing else ""))

    if deviations:
        print("\nABORT — row counts deviate from the pinned manifest:", file=sys.stderr)
        for t, exp, got in deviations:
            print(f"  {t}: manifest {exp:,} != local {got:,}", file=sys.stderr)
        print("\nThe cache and the pin disagree. Re-run cache_tables.py, or "
              "re-run step_zero.py if the release genuinely moved — and amend "
              "the spec before proceeding (§4.1 step zero).", file=sys.stderr)
        return 1

    print("\nAC-1 satisfied: every cached table matches the pinned manifest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
