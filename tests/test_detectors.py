"""Detector tests (spec 001 §5, §5.0, §5.1).

H2 and H3 found zero artifacts in the pilot, so their matcher branches were never
exercised by real data. A detector that has never fired is indistinguishable from
a broken one — these tests build a synthetic repository that contains each
mechanism and assert it is found.

    py -3.12 tests/test_detectors.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src" / "mine"))
from mine_harness import (  # noqa: E402
    NORMATIVE_RE, PROHIBITION_RE, addition_dates, match_mechanism,
)

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(label)


def test_pattern_matching() -> None:
    print("\n[1] mechanism matching, per §5")
    cases = {
        # H1 — always-loaded rule files
        "AGENTS.md": "H1_context_engineering",
        "CLAUDE.md": "H1_context_engineering",
        ".cursorrules": "H1_context_engineering",
        ".cursor/rules/api.mdc": "H1_context_engineering",
        ".github/copilot-instructions.md": "H1_context_engineering",
        # H2 — persistent shared knowledge (zero in the pilot)
        "docs/adr/0001-record-architecture-decisions.md": "H2_persistent_knowledge",
        "doc/adr/0007-use-postgres.md": "H2_persistent_knowledge",
        "adr/0002-thing.md": "H2_persistent_knowledge",
        "docs/decisions/0003-caching.md": "H2_persistent_knowledge",
        ".specify/memory/session-2025-06-01.md": "H2_persistent_knowledge",
        # H3 — executable specifications (zero at PR time in the pilot)
        "specs/refund.md": "H3_executable_specs",
        "features/refund.feature": "H3_executable_specs",
        "openapi.yaml": "H3_executable_specs",
        "api/openapi.json": "H3_executable_specs",
        ".specify/specs/001-refund.md": "H3_executable_specs",
        # H7
        ".github/pull_request_template.md": "H7_evidence_acceptance",
        # H8 — workflows removed by amendment A1
        "CODEOWNERS": "H8_graduated_autonomy",
        ".github/CODEOWNERS": "H8_graduated_autonomy",
        ".github/workflows/ci.yml": None,
        # negatives
        "README.md": None,
        "src/main.py": None,
        "docs/guide.md": None,
    }
    for path, want in cases.items():
        check(path, match_mechanism(path), want)


def test_normative_regex() -> None:
    print("\n[2] H5 normative-clause detection")
    txt = ("Services MUST NOT catch Exception. You should map errors. "
           "Never return ORM entities. Always use UTC.")
    check("normative clauses >= 4", len(NORMATIVE_RE.findall(txt)) >= 4, True)
    check("prohibitions >= 2", len(PROHIBITION_RE.findall(txt)) >= 2, True)
    check("no false positive on prose",
          len(NORMATIVE_RE.findall("This module parses configuration files.")), 0)


def test_first_appearance_dates() -> None:
    """The point-in-time rule (§5.1) is only as good as this function."""
    print("\n[3] first-appearance dates on a synthetic repository")
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td) / "r"
        repo.mkdir()

        def git(*a: str, **kw) -> None:
            subprocess.run(["git", "-C", str(repo), *a], check=True,
                           capture_output=True, **kw)

        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")

        def commit(path: str, body: str, when: str) -> None:
            f = repo / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
            git("add", path)
            env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", path],
                           check=True, capture_output=True,
                           env={**dict(__import__("os").environ), **env})

        commit("README.md", "# r\n", "2025-01-01T00:00:00Z")
        commit("docs/adr/0001-x.md", "# ADR 1\n", "2025-03-15T00:00:00Z")
        commit("specs/refund.md", "Given a payment\n", "2025-05-20T00:00:00Z")
        commit("AGENTS.md", "Services MUST NOT log secrets.\n", "2025-06-10T00:00:00Z")

        for path, want_date, want_mech in (
            ("docs/adr/0001-x.md", "2025-03-15", "H2_persistent_knowledge"),
            ("specs/refund.md", "2025-05-20", "H3_executable_specs"),
            ("AGENTS.md", "2025-06-10", "H1_context_engineering"),
        ):
            first, _, n = addition_dates(repo, path)
            check(f"{path} mechanism", match_mechanism(path), want_mech)
            check(f"{path} first_added", (first or "")[:10], want_date)
            check(f"{path} n_additions", n, 1)

        # A file that does not exist must yield no date, never a silent default.
        first, last, n = addition_dates(repo, "does/not/exist.md")
        check("absent file -> (None, None, 0)", (first, last, n), (None, None, 0))


def main() -> int:
    test_pattern_matching()
    test_normative_regex()
    test_first_appearance_dates()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all detector tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
