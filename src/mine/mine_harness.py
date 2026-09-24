"""Clone repositories and extract harness indicators with introduction dates.

Implements spec 001-v2 §4.2 (clone-first, D-v2-6) and §5 (operationalization).
Mechanisms covered: H1, H2, H3, H5, H7, H8.  H4 is excluded by decision.
H6 is handled separately by the rule-based classifier (D11) and is observable
only in stratum P, where PR comments exist (§4.1).

Every artifact is recorded with its FIRST-APPEARANCE date, which is what the
two estimands of §5.1 consume. Presence alone is never sufficient.

Scale changes over the pilot version, all forced by the 5,807-repository frame:

  * CLONES ARE DISCARDED after extraction (--keep-clones to opt out). At pilot
    sizes (median 38 MB, mean 69 MB, max 311 MB) keeping 2,807 of them would
    need ~100-200 GB, more than this machine has free. Peak disk is bounded by
    concurrency, not by sample size.
  * CLONES LIVE OUTSIDE THE REPOSITORY (tempfile.gettempdir(), not data/clones)
    because the repository lives inside a NextCloud tree, and the NextCloud
    desktop client watches that tree independently of git -- it does not read
    .gitignore, only its own sync-exclude list. A clone that is created and
    deleted in seconds is still visible to that watcher for the seconds it
    exists, and 5,807 of them is enough transient upload traffic to fill a
    server-side quota (~40 GB observed 2026-08-21) even though nothing persists
    locally. Discovered after the full run; data/clones/ itself was always
    empty on inspection, which is what made this easy to miss.
  * RULE-FILE TEXT IS SAVED to data/rulefiles/ before the clone is dropped, so
    the qualitative work (PI-2) never has to re-clone. Small: median 1.8 KB.
    Third-party content -> gitignored, never republished (C-v2-2).
  * PROGRESS IS CHECKPOINTED per repository to JSONL, so an interrupted run
    resumes instead of restarting. C-v2-1 requires resumable and idempotent;
    with clones discarded, the checkpoint is what provides both.

Usage:
    py -3.12 src/mine/mine_harness.py --stratum all
    py -3.12 src/mine/mine_harness.py --stratum P
    py -3.12 src/mine/mine_harness.py --stratum P --limit 20   # smoke test
    py -3.12 src/mine/mine_harness.py --frame data/pilot_repos.csv --out-prefix harness

No PR outcome is touched anywhere in this file.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRAME = ROOT / "data" / "sample_frame.csv"
# Outside ROOT deliberately: ROOT lives inside a synced NextCloud tree, and
# clones (unlike data/rulefiles) never survive past a single mine_one() call.
# See the module docstring for the incident that made this necessary.
CLONES = pathlib.Path(tempfile.gettempdir()) / "paper-sdd-emse-clones"
RULEFILES = ROOT / "data" / "rulefiles"

CLONE_TIMEOUT = 600
GIT_TIMEOUT = 180
WORKERS = 5

# Rule-file text kept for PI-2. Anything larger is a generated file, not a
# system specification, and storing it would not help the coders.
RULEFILE_MAX_BYTES = 512 * 1024

# Abort rather than fill the disk. The checkpoint makes an abort cheap.
MIN_FREE_GB = 15.0

_lock = threading.Lock()

# --- §5 operationalization: mechanism -> glob patterns (case-insensitive) ----
PATTERNS: dict[str, list[str]] = {
    "H1_context_engineering": [
        "AGENTS.md", "AGENT.md", "CLAUDE.md", "agent.md", "GEMINI.md",
        ".cursorrules", ".windsurfrules", ".clinerules", ".clinerules/*",
        ".cursor/rules/*", ".cursor/rules/**/*",
        ".github/copilot-instructions.md",
    ],
    "H2_persistent_knowledge": [
        "docs/adr/*", "docs/adr/**/*", "doc/adr/*", "doc/adr/**/*",
        "adr/*", "adr/**/*", "docs/decisions/*", "docs/decisions/**/*",
        "decisions/*", "decisions/**/*", ".specify/memory/*", ".specify/memory/**/*",
    ],
    "H3_executable_specs": [
        "specs/*", "specs/**/*", ".specify/specs/*", ".specify/specs/**/*",
        "*.feature", "**/*.feature",
        "openapi.yaml", "openapi.yml", "openapi.json",
        "**/openapi.yaml", "**/openapi.yml", "**/openapi.json",
    ],
    "H7_evidence_acceptance": [
        ".github/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/PULL_REQUEST_TEMPLATE/*", "pull_request_template.md",
        "docs/pull_request_template.md",
    ],
    # A1 (§5.0): `.github/workflows/*` was REMOVED. It flagged 88% of pilot PRs —
    # nearly every active repo has CI — saturating `harness_any` into a constant.
    # Do not add it back without a prevalence check.
    "H8_graduated_autonomy": [
        "CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS",
    ],
}

# Files whose *content* we read for H5 normative density.
RULE_FILE_MECHANISM = "H1_context_engineering"

# H5: modal imperatives marking a standing norm (spec §5, H5 row).
NORMATIVE_RE = re.compile(
    r"\b(MUST NOT|MUST|SHALL NOT|SHALL|NEVER|ALWAYS|REQUIRED|FORBIDDEN|"
    r"do not|don't|never|always|must not|must|should not|should)\b",
    re.IGNORECASE,
)
PROHIBITION_RE = re.compile(
    r"\b(MUST NOT|SHALL NOT|NEVER|FORBIDDEN|do not|don't|never|must not|should not)\b",
    re.IGNORECASE,
)


# Git must never wait for a human. A private or deleted repository otherwise
# parks Credential Manager on an interactive prompt that never gets an answer.
# That alone would be survivable, but on Windows killing a process does NOT kill
# its grandchildren: the timeout reaps `git clone` while `git credential-manager`
# lives on holding the inherited pipes, and subprocess.run() then blocks forever
# draining them. Three private repositories froze a 2,807-repository run for two
# hours this way -- the timeout meant to protect the run is what hung it.
# Strata G1-G3 are full of deleted and private repositories, so this path is the
# common case there, not an edge case.
GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",   # fail instead of prompting on the terminal
    "GIT_ASKPASS": "echo",        # ...and instead of opening a GUI prompt
    "SSH_ASKPASS": "echo",
    "GCM_INTERACTIVE": "never",
    "GIT_CONFIG_NOSYSTEM": "1",   # ignore any system-wide credential helper
}
# Belt and braces: clear the helper for this invocation regardless of config.
NO_CRED = ["-c", "credential.helper=", "-c", "core.askPass="]


def _kill_tree(pid: int) -> None:
    """Kill a process AND its descendants. Popen.kill() reaches only the direct
    child, which is exactly the gap that produced the hang described above."""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=30)
    except Exception:
        pass


def git(repo: pathlib.Path, *args: str, timeout: int = GIT_TIMEOUT) -> str | None:
    p = subprocess.Popen(
        ["git", "-C", str(repo), *NO_CRED, *args],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", env=GIT_ENV,
    )
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p.pid)
        try:
            out, _ = p.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            return None  # give up on this file rather than stall the run
    return out if p.returncode == 0 else None


def github_fallback(full_name: str) -> tuple[str, str | None, str | None]:
    """AC-2 fallback when the clone fails.

    Returns (status, resolved_full_name, detail). A rename is not a loss:
    `repository.full_name` is a snapshot value, so a 301 means "moved", and the
    repository is still in scope under its new name. Distinguishing that from a
    genuine deletion is the whole reason this path exists.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"https://api.github.com/repos/{full_name}",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "sdd-emse-mining-study"},
    )
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        new_name = data.get("full_name")
        if new_name and new_name.lower() != full_name.lower():
            return "api_fallback", new_name, "renamed"
        if data.get("archived"):
            return "api_fallback", new_name, "archived"
        return "api_fallback", new_name, "clone_failed_but_reachable"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "unavailable", None, "deleted_or_private"
        if e.code in (403, 429):
            return "unavailable", None, f"rate_limited_{e.code}"
        return "unavailable", None, f"http_{e.code}"
    except Exception as e:  # network/DNS/timeout
        return "unavailable", None, f"error_{type(e).__name__}"


def clone(full_name: str, dest: pathlib.Path) -> tuple[str, str | None, str | None]:
    """Return (status, resolved_name, detail) per AC-2:
    cloned | api_fallback | unavailable — every repository gets a terminal state."""
    if (dest / "HEAD").exists():
        return "cloned", full_name, "cached"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    def attempt(name: str) -> int:
        # DEVNULL, not PIPE: only the return code is used, and with no pipes to
        # drain there is no way for a surviving child to block the wait.
        p = subprocess.Popen(
            ["git", *NO_CRED, "clone", "--bare", "--filter=blob:limit=100k",
             "--quiet", f"https://github.com/{name}.git", str(dest)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=GIT_ENV,
        )
        try:
            return p.wait(timeout=CLONE_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_tree(p.pid)
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
            return 124

    if attempt(full_name) == 0:
        return "cloned", full_name, None

    status, resolved, detail = github_fallback(full_name)
    # A rename is recoverable: retry the clone under the resolved name.
    if status == "api_fallback" and resolved and resolved.lower() != full_name.lower():
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        if attempt(resolved) == 0:
            return "cloned", resolved, "recovered_after_rename"
    return status, resolved, detail


def match_mechanism(path: str) -> str | None:
    low = path.lower()
    for mech, globs in PATTERNS.items():
        for g in globs:
            if fnmatch.fnmatch(low, g.lower()):
                return mech
    return None


def addition_dates(repo: pathlib.Path, path: str) -> tuple[str | None, str | None, int]:
    """(first_added, last_added, n_additions) — ISO author dates, oldest last in git log."""
    out = git(repo, "log", "--diff-filter=A", "--format=%aI", "--", path)
    if not out:
        return None, None, 0
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return None, None, 0
    return lines[-1], lines[0], len(lines)


def force_rmtree(path: pathlib.Path) -> bool:
    """Delete a bare clone on Windows, where git's object files are read-only.

    `shutil.rmtree(ignore_errors=True)` silently leaves the whole tree behind:
    in the 20-repository smoke test it removed 2 of 20 and reported nothing,
    which at 2,807 repositories would have filled the disk mid-run. The retry
    below chmods the offending entry and tries again; the return value is
    checked by the caller, because a deletion that quietly fails is worse than
    one that fails loudly.
    """
    if not path.exists():
        return True

    def _retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_retry)
        else:
            shutil.rmtree(path, onerror=lambda f, p, e: _retry(f, p, e))
    except OSError:
        pass
    return not path.exists()


def save_rulefile(full_name: str, path: str, blob: str) -> str | None:
    """Persist rule-file text for PI-2 before the clone is discarded."""
    safe = full_name.replace("/", "__") + "__" + path.replace("/", "__")
    dest = RULEFILES / safe[:180]
    try:
        dest.write_text(blob, encoding="utf-8", errors="replace")
        return dest.name
    except OSError:
        return None


def mine_one(row: dict, keep_clones: bool) -> dict:
    full_name = row["full_name"]
    dest = CLONES / full_name.replace("/", "__")
    rec: dict = {
        "repo_id": int(float(row["repo_id"])), "full_name": full_name,
        "language": row.get("language"), "stars": int(float(row.get("stars") or 0)),
        "agentic_prs": int(float(row.get("agentic_prs") or 0)),
        "stratum": row.get("stratum"), "weight": float(row.get("weight") or 1.0),
        "status": None, "artifacts": [], "tree_size": None, "head_commit": None,
        "resolved_full_name": None, "status_detail": None,
    }
    try:
        return _mine_body(rec, row, dest, keep_clones)
    finally:
        # Bounded peak disk: the clone goes away as soon as it has been read.
        if not keep_clones:
            rec["clone_removed"] = force_rmtree(dest)


def _mine_body(rec: dict, row: dict, dest: pathlib.Path, keep_clones: bool) -> dict:
    full_name = row["full_name"]
    rec["status"], rec["resolved_full_name"], rec["status_detail"] = clone(full_name, dest)
    if rec["status"] != "cloned":
        return rec

    rec["head_commit"] = (git(dest, "rev-parse", "HEAD") or "").strip() or None
    tree = git(dest, "ls-tree", "-r", "HEAD")
    if tree is None:
        rec["status"] = "unavailable"
        return rec

    # "<mode> <type> <sha>\t<path>" — mode 120000 is a symlink; equal sha means
    # byte-identical content under two names. Both are duplication, not adoption.
    entries: list[tuple[str, str, str]] = []
    for line in tree.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 3:
            entries.append((parts[0], parts[2], path.strip()))
    rec["tree_size"] = len(entries)

    for mode, sha, p in entries:
        mech = match_mechanism(p)
        if not mech:
            continue
        first, last, n = addition_dates(dest, p)
        art = {"mechanism": mech, "path": p, "first_added": first,
               "last_added": last, "n_additions": n,
               "mode": mode, "blob_sha": sha, "is_symlink": mode == "120000"}
        if mech == RULE_FILE_MECHANISM:
            blob = git(dest, "show", f"HEAD:{p}")
            if blob is not None:
                nbytes = len(blob.encode("utf-8"))
                kb = max(nbytes / 1024.0, 0.001)
                art["bytes"] = nbytes
                art["normative_clauses"] = len(NORMATIVE_RE.findall(blob))
                art["prohibitions"] = len(PROHIBITION_RE.findall(blob))
                art["normative_density_per_kb"] = round(
                    len(NORMATIVE_RE.findall(blob)) / kb, 2)
                # PI-2 needs the text itself, and the clone is about to go away.
                if nbytes <= RULEFILE_MAX_BYTES:
                    art["rulefile"] = save_rulefile(rec["full_name"], p, blob)
        rec["artifacts"].append(art)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="Mine harness artifacts (spec 001-v2 §4.2)")
    ap.add_argument("--frame", default=str(FRAME), help="sample frame CSV")
    ap.add_argument(
        "--stratum",
        default="all",
        choices=("all", "P", "G1", "G2", "G3"),
        help="restrict to one stratum; 'all' mines the complete frame and writes one JSON per stratum",
    )
    ap.add_argument("--limit", type=int, default=None, help="first N repos only (smoke test)")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--keep-clones", action="store_true",
                    help="do not delete clones after extraction (needs ~100-200 GB at scale)")
    ap.add_argument("--out-prefix", default=None,
                    help="output basename; defaults to harness_<stratum>")
    args = ap.parse_args()

    rows = list(csv.DictReader(pathlib.Path(args.frame).open(encoding="utf-8")))
    stratum = args.stratum
    if stratum != "all":
        rows = [r for r in rows if r.get("stratum") == stratum]
        if not rows:
            print(f"no rows with stratum={stratum!r} in {args.frame}", file=sys.stderr)
            return 2
    if args.limit:
        rows = rows[: args.limit]

    prefix = args.out_prefix or f"harness_{stratum}"
    out_json = ROOT / "data" / f"{prefix}_raw.json"
    ledger = ROOT / "data" / f"{prefix}_ledger.csv"
    # One canonical checkpoint is shared by all invocations. This means a
    # run restricted to one stratum can reuse work completed by a previous
    # complete run (or by another stratum-specific invocation).
    ckpt = ROOT / "data" / "harness_all_checkpoint.jsonl"

    CLONES.mkdir(parents=True, exist_ok=True)
    RULEFILES.mkdir(parents=True, exist_ok=True)

    # Resume completed repositories from the shared checkpoint. Unavailable
    # repositories are deliberately retried on every invocation: this status
    # includes transient failures such as GitHub 403/429 rate limits.
    done: dict[str, dict] = {}
    if ckpt.exists():
        for line in ckpt.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    done[r["full_name"]] = r
                except json.JSONDecodeError:
                    continue  # truncated final line from an interrupted run
        completed = {
            name: record for name, record in done.items()
            if record.get("status") != "unavailable"
        }
        done_in_scope = sum(1 for r in rows if r["full_name"] in completed)
        retry_in_scope = sum(
            1 for r in rows
            if done.get(r["full_name"], {}).get("status") == "unavailable"
        )
        print(f"resuming: {done_in_scope:,}/{len(rows):,} repositories already done "
              f"in {ckpt.name}; retrying unavailable: {retry_in_scope:,}")
    else:
        completed = {}

    todo = [r for r in rows if r["full_name"] not in completed]
    rows_by_name = {r["full_name"]: r for r in rows}
    print(f"frame {pathlib.Path(args.frame).name} | stratum {stratum} | "
          f"{len(rows):,} repos | {len(todo):,} to mine | workers {args.workers} | "
          f"clones {'kept' if args.keep_clones else 'discarded after extraction'}",
          flush=True)

    # Only include records belonging to this invocation's frame/stratum in
    # its output. The shared checkpoint also contains other strata. Keep the
    # latest record per repository so retries do not duplicate output rows.
    results_by_name = {
        r["full_name"]: done[r["full_name"]]
        for r in rows if r["full_name"] in done
    }
    t0, n_done = time.time(), 0
    fh = ckpt.open("a", encoding="utf-8")
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(mine_one, r, args.keep_clones): r["full_name"] for r in todo}
            for f in as_completed(futs):
                try:
                    rec = f.result()
                except Exception as e:  # never let one repository kill a 3-hour run
                    name = futs[f]
                    rec = {"repo_id": -1, "full_name": name, "status": "unavailable",
                           "status_detail": f"exception_{type(e).__name__}", "artifacts": [],
                           "tree_size": None, "head_commit": None,
                           "resolved_full_name": None, "stratum": (
                               rows_by_name[name].get("stratum")
                           )}
                results_by_name[rec["full_name"]] = rec
                n_done += 1
                with _lock:
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                if n_done % 25 == 0 or n_done == len(todo):
                    el = time.time() - t0
                    rate = n_done / el if el else 0
                    eta = (len(todo) - n_done) / rate / 60 if rate else 0
                    free_gb = shutil.disk_usage(ROOT).free / 2**30
                    stuck = sum(1 for r in results_by_name.values()
                                if r.get("clone_removed") is False)
                    print(f"  [{n_done:>5}/{len(todo)}] {el/60:5.1f} min elapsed, "
                          f"{rate*60:5.1f} repos/min, ETA {eta:5.1f} min, "
                          f"{free_gb:5.1f} GB free"
                          + (f", {stuck} clones NOT removed" if stuck else ""),
                          flush=True)
                    # Stop cleanly rather than fill the disk. The checkpoint is
                    # already on disk, so a resumed run picks up from here.
                    if free_gb < MIN_FREE_GB:
                        print(f"\nABORT: free space {free_gb:.1f} GB below "
                              f"{MIN_FREE_GB} GB. Progress is checkpointed; "
                              f"free space and re-run the same command to resume.",
                              file=sys.stderr, flush=True)
                        for fu in futs:
                            fu.cancel()
                        break
    finally:
        fh.close()

    results = sorted(results_by_name.values(), key=lambda r: r["full_name"])
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # A complete run is consumed by downstream scripts as one file per
    # stratum. Keep the aggregate output for auditing, and also materialize
    # the four stratum files without requiring four separate mining runs.
    if stratum == "all":
        for st in ("P", "G1", "G2", "G3"):
            st_results = [r for r in results if r.get("stratum") == st]
            st_json = ROOT / "data" / f"harness_{st}_raw.json"
            st_json.write_text(json.dumps(st_results, indent=2), encoding="utf-8")
            print(f"wrote {st_json.relative_to(ROOT)}: {len(st_results):,} repositories")

    # AC-2: every repository ends in exactly one terminal state, and the ledger
    # is what the paper's sample-construction figure is built from.
    with ledger.open("w", newline="", encoding="utf-8") as lf:
        w = csv.writer(lf)
        w.writerow(["repo_id", "full_name", "resolved_full_name", "status",
                    "status_detail", "stratum", "tree_size", "head_commit", "n_artifacts"])
        for r in results:
            w.writerow([r["repo_id"], r["full_name"], r["resolved_full_name"],
                        r["status"], r["status_detail"], r.get("stratum"),
                        r["tree_size"], r["head_commit"], len(r["artifacts"])])

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    assert set(counts) <= {"cloned", "api_fallback", "unavailable"}, counts
    assert sum(counts.values()) == len(results), "AC-2: a repository has no terminal state"

    n_art = sum(len(r["artifacts"]) for r in results)
    print(f"\nAC-2 ledger: {counts}  -> {ledger.relative_to(ROOT)}")
    print(f"{n_art:,} artifacts (pre-dedup) -> {out_json.relative_to(ROOT)}")
    print(f"total wall clock: {(time.time() - t0)/60:.1f} min")
    unavailable = counts.get("unavailable", 0)
    if unavailable:
        print(
              "\nWARNING: ACQUISITION INCOMPLETE\n"
              f"{unavailable:,} repositories could not be acquired in this pass. "
              "Some may become available on a later run; others may remain unavailable "
              "if they have been deleted, made private, or are otherwise inaccessible on GitHub.\n"
              "Re-run the same command to retry them:\n"
              "  python src/mine/mine_harness.py --stratum all",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
