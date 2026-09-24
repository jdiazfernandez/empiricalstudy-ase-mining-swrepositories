"""Rule-based structured-consultation classifier (H6) run over the FULL
stratum-P sample (2,807 repos / 33,596 PRs), not the 10-repo pilot.

Sampling design (fixed BEFORE any human coding, not adjusted after seeing
results): a stratum is read in FULL (census) if its population is small
enough that reading it entirely is feasible (<= CENSUS_MAX); otherwise it is
capped at TARGET_N. TARGET_N=150 is chosen so that, in the worst case (zero
confirmed positives observed), the exact-hypergeometric 95% upper bound on
that stratum stays around ~2% -- see score_validation_full.py's
upper_bound_zero() for the same method applied to compute it, and the study
spec for the full derivation. This replaces an earlier attempt where sample
sizes were chosen reactively after seeing an uninformative result; that
attempt (and its data) was discarded rather than patched further.

NO MODEL IS USED. Deterministic; identical inputs give identical outputs (D11).
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import duckdb
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
AIDEV = ROOT / "data" / "aidev"
SAMPLE_FRAME = ROOT / "data" / "sample_frame.csv"
OUT = ROOT / "data" / "consultations_full.parquet"
SAMPLE = ROOT / "data" / "consultation_validation_sample_full.csv"
REPORT = ROOT / "data" / "consultation_report_full.json"

CENSUS_MAX = 200   # strata this size or smaller are read in full
TARGET_N = 150     # cap for strata larger than CENSUS_MAX (see docstring)
OVERLAP = 0.20      # coder2 double-codes this leading fraction, for kappa

AGENT_BOTS = {"devin-ai-integration[bot]", "copilot", "cursoragent",
              "claude[bot]", "chatgpt-codex-connector[bot]"}

ASK_RE = re.compile(
    r"\b(which (approach|option|one|strategy|way|of these)|should i|shall i|"
    r"do you (want|prefer)|would you (like|prefer)|please (confirm|advise|clarify|choose)|"
    r"let me know (which|whether|if)|how would you like|"
    r"i need (you to )?(decide|confirm|clarify))\b",
    re.IGNORECASE,
)
QMARK_RE = re.compile(r"\?")
ANSWERING_RE = re.compile(
    r"^\s*[>*_#\s]*(great|good|excellent|fair|nice)\s+(question|catch|point)|"
    r"^\s*[>*_#\s]*(you'?re|you are)\s+(right|correct)|"
    r"^\s*[>*_#\s]*(thanks|thank you|got it|understood|makes sense)\b",
    re.IGNORECASE,
)
REPORT_RE = re.compile(
    r"(finished @\S+'?s? task|"
    r"^\s*[-*]\s*\[[ xX]\]|"
    r"###?\s*(review tasks?|todo list|checklist)|"
    r"\[view job\]|generated (by|with) )",
    re.IGNORECASE | re.MULTILINE,
)
CHECKLIST_LINE_RE = re.compile(r"^\s*[-*]\s*\[[ xX]\].*$", re.MULTILINE)
OPT_PATTERNS = [
    re.compile(r"\boption\s*(\d+|[a-d])\b", re.IGNORECASE),
    re.compile(r"^\s*(\d+)[.)]\s+\S", re.MULTILINE),
    re.compile(r"^\s*([a-d])[.)]\s+\S", re.MULTILINE),
    re.compile(r"\balternative\s*(\d+|[a-d])\b", re.IGNORECASE),
]
EITHER_RE = re.compile(r"\beither\b.{0,200}?\bor\b", re.IGNORECASE | re.DOTALL)
SPEC_RE = re.compile(
    r"\b(spec(ification)?\s*#?\d|AGENTS?\.md|CLAUDE\.md|\.cursorrules|"
    r"\bADR[- ]?\d|architecture decision|acceptance criteri|"
    r"per the (spec|specification|rules?)|as specified in)\b",
    re.IGNORECASE,
)
BLOCK_RE = re.compile(
    r"\b(blocked on|waiting (for|on) (a )?(decision|confirmation|input|guidance)|"
    r"before (i )?(proceed|continue)|need (a )?(decision|clarification|guidance)|"
    r"cannot (decide|determine)|unclear (from|which)|ambiguous)\b",
    re.IGNORECASE,
)
TRADEOFF_RE = re.compile(
    r"\b(trade[- ]?off|pros? and cons?|downside|advantage|disadvantage|"
    r"the cost is|at the cost of|however,|on the other hand|whereas)\b",
    re.IGNORECASE,
)
TEMPLATE_RE = re.compile(
    r"(##\s*(checklist|description|type of change)|"
    r"\[ \]\s*(i have|my code|tests)|generated (by|with) )",
    re.IGNORECASE,
)


def n_options(text: str) -> int:
    stripped = CHECKLIST_LINE_RE.sub("", text)
    best = 0
    for p in OPT_PATTERNS:
        best = max(best, len(set(m.group(1).lower() for m in p.finditer(stripped))))
    if EITHER_RE.search(stripped):
        best = max(best, 2)
    return best


def classify(text: str) -> dict:
    t = text or ""
    opts = n_options(t)
    s1 = bool(SPEC_RE.search(t))
    s2 = bool(BLOCK_RE.search(t))
    s3 = bool(TRADEOFF_RE.search(t))
    answering = bool(ANSWERING_RE.search(t))
    report = bool(REPORT_RE.search(t))
    boiler = bool(TEMPLATE_RE.search(t))
    r2 = bool(ASK_RE.search(t)) or (bool(QMARK_RE.search(t)) and s2)
    r3 = opts >= 2
    excluded = answering or report or boiler
    loose = r2 and r3 and not excluded
    strict = loose and (s1 or s2 or s3)
    return {"has_question": r2, "n_options": opts, "has_options": r3,
            "cites_spec": s1, "is_blocked": s2, "states_tradeoff": s3,
            "is_answering": answering, "is_report": report, "is_boilerplate": boiler,
            "consultation_loose": loose, "consultation_strict": strict}


def main() -> int:
    frame = pd.read_csv(SAMPLE_FRAME)
    repos = frame[frame.stratum == "P"].repo_id.tolist()
    print(f"stratum P: {len(repos)} repos")

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false;")
    ids = ",".join(str(r) for r in repos)
    PR = (AIDEV / "pull_request.parquet").as_posix()
    df = con.execute(f"""
        SELECT c.id AS comment_id, c.pr_id, c.user AS commenter, c.user_type,
               c.body, p.agent, p.user AS pr_author, p.repo_id, 'comment' AS surface
        FROM read_parquet('{(AIDEV / "pr_comments.parquet").as_posix()}') c
        JOIN read_parquet('{PR}') p ON p.id = c.pr_id
        WHERE p.repo_id IN ({ids}) AND c.body IS NOT NULL

        UNION ALL
        SELECT p.id AS comment_id, p.id AS pr_id, p.user AS commenter, 'User' AS user_type,
               p.body, p.agent, p.user AS pr_author, p.repo_id, 'pr_body' AS surface
        FROM read_parquet('{PR}') p
        WHERE p.repo_id IN ({ids}) AND p.body IS NOT NULL

        UNION ALL
        SELECT rc.id AS comment_id, r.pr_id, rc.user AS commenter, rc.user_type,
               rc.body, p.agent, p.user AS pr_author, p.repo_id, 'review_comment' AS surface
        FROM read_parquet('{(AIDEV / "pr_review_comments_v2.parquet").as_posix()}') rc
        JOIN read_parquet('{(AIDEV / "pr_reviews.parquet").as_posix()}') r
          ON r.id = rc.pull_request_review_id
        JOIN read_parquet('{PR}') p ON p.id = r.pr_id
        WHERE p.repo_id IN ({ids}) AND rc.body IS NOT NULL
    """).fetchdf()

    df["agent_authored"] = (
        df.commenter.str.lower().isin(AGENT_BOTS)
        | (df.commenter.str.lower() == df.pr_author.str.lower())
    )
    feats = pd.DataFrame([classify(b) for b in df.body])
    df = pd.concat([df.reset_index(drop=True), feats], axis=1)
    for col in ("consultation_loose", "consultation_strict"):
        df[col] = df[col] & df.agent_authored

    df["body_len"] = df.body.str.len()
    df.drop(columns=["body"]).to_parquet(OUT, index=False)

    pr_level = df.groupby("pr_id").agg(
        H6_loose=("consultation_loose", "max"),
        H6_strict=("consultation_strict", "max")).reset_index()

    rep = {
        "scope": "stratum P full (data/sample_frame.csv, stratum=='P')",
        "n_repos": len(repos),
        "comments_scanned": int(len(df)),
        "agent_authored": int(df.agent_authored.sum()),
        "consultations_loose": int(df.consultation_loose.sum()),
        "consultations_strict": int(df.consultation_strict.sum()),
        "prs_with_consultation_loose": int(pr_level.H6_loose.sum()),
        "prs_with_consultation_strict": int(pr_level.H6_strict.sum()),
        "prs_total": int(pr_level.shape[0]),
        "by_agent": df[df.agent_authored].groupby("agent").agg(
            comments=("comment_id", "size"),
            loose=("consultation_loose", "sum"),
            strict=("consultation_strict", "sum")).astype(int).to_dict("index"),
    }
    print(json.dumps(rep, indent=2))

    # --- sampling design, fixed before any coding --------------------------
    strata_masks = {
        "strict": df.consultation_strict,
        "loose_only": df.consultation_loose & ~df.consultation_strict,
        "agent_options_no_ask": df.agent_authored & df.has_options & ~df.has_question,
        "agent_ask_no_options": df.agent_authored & df.has_question & ~df.has_options,
        "agent_other": df.agent_authored & ~df.has_question & ~df.has_options,
    }

    strata, parts = [], []
    for name, mask in strata_masks.items():
        sub = df[mask]
        pop = len(sub)
        n = pop if pop <= CENSUS_MAX else min(TARGET_N, pop)
        design = "census" if pop <= CENSUS_MAX else f"capped at {TARGET_N}"
        take = sub.sample(n=n, random_state=20260817) if n < pop else sub
        take = take.assign(stratum=name)
        parts.append(take)
        strata.append({"stratum": name, "population": pop, "sampled": n, "design": design})
        print(f"{name}: population={pop}  sampled={n}  ({design})")

    rep["strata_pop"] = {d["stratum"]: d["population"] for d in strata}
    rep["strata_sampled"] = {d["stratum"]: d["sampled"] for d in strata}
    rep["sampling_design"] = strata
    REPORT.write_text(json.dumps(rep, indent=2), encoding="utf-8")

    s = pd.concat(parts)[
        ["stratum", "comment_id", "pr_id", "agent", "commenter", "n_options",
         "has_question", "cites_spec", "is_blocked", "states_tradeoff",
         "consultation_loose", "consultation_strict", "body"]]
    s.insert(0, "human_label_BLANK", "")
    s.to_csv(SAMPLE, index=False, encoding="utf-8")
    print(f"\n{len(s)} items -> {SAMPLE.relative_to(ROOT)}  "
          f"(fill human_label_BLANK: 1/0/? -- use make_coding_form_full.py instead)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
