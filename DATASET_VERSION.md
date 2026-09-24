# AIDev dataset pin and verification

**What this is.** A record of exactly which snapshot of the AIDev dataset this
study used, and a one-time check confirming that snapshot has the tables and
fields the study relies on, with the row counts stated here.

**When to read this.** Read it if you want to confirm you would be starting
from the same population the study started from — before running
`src/ingest/cache_tables.py` (Step 2 of `GET-THE-DATA.md`). You do not need it
to run any script; `cache_tables.py` already hard-codes the revision below.

---

## 1. The pin

- **Source:** https://huggingface.co/datasets/hao-li/AIDev
- **Revision (SHA):** `68ed5f4b80d27a9e057fc57567f38bd322ac73ec`
- **Pinned URL form used throughout:**
  `https://huggingface.co/datasets/hao-li/AIDev/resolve/68ed5f4b80d27a9e057fc57567f38bd322ac73ec/<table>.parquet`

Every count and every script in this study reads the dataset through that exact
URL pattern — never the "latest" version. Section 2 explains why that
distinction matters in practice.

## 2. Licence

`cc-by-4.0`. This covers AIDev's own tables (PRs, comments, reviews, etc.) and
permits redistributing a subset of them with attribution. It does **not** cover
the content of the mined repositories themselves (e.g. rule files): the dataset
card is explicit that AIDev's licence does not relicense that material ("do not
assume a universal re-license"). Each such file remains under its own
repository's licence, and 71.7 % of stratum G3 declares none at all — i.e. all
rights reserved by default. That is why this package ships no rule-file
content and instead points to `GET-THE-DATA.md` to regenerate it locally.

## 3. Why the exact revision matters: the dataset stopped growing before the repo did

| Tier | First PR `created_at` | Last PR `created_at` | Last `merged_at` |
|---|---|---|---|
| `pull_request` (popular tier) | 2024-12-24 | 2025-07-30 | 2025-07-30 |
| `all_pull_request` (full tier) | 2024-12-24 | 2025-07-30 | 2025-07-30 |

The Hugging Face repository shows a **last-modified date of 2026-05-10** — almost
a year after the last PR in it. This is metadata housekeeping, not new data: PR
coverage still ends 2025-07-30 in both tiers, matching the dataset card's stated
cutoff. Anyone re-cloning the dataset today would get the same ~7-month
observation window (2024-12-24 to 2025-07-30), not an extended one. That window
is what defines which repositories are in this study's sample — see the "Data
source" section of the paper.

## 4. What was checked, and what it confirmed

Before mining, the pinned snapshot was checked against the tables, fields, and
row counts the study's design assumes. Two things came out of that check that
matter for reproducing the study, and one that does not:

- **Everything the study needs is present.** All tables and fields the study
  reads exist in this revision, with compatible types, and the row counts are
  as listed below.
- **There are two review-comments tables; use the second one.** Both
  `pr_review_comments` (19,450 rows) and `pr_review_comments_v2` (26,868 rows)
  exist, with identical schemas — `v2` is a strict superset. This study reads
  only `pr_review_comments_v2`; any script that reads the `v1` table instead is
  a bug.
- **Timestamps in `pr_review_comments_v2` are strings, not dates.** The
  `created_at` / `updated_at` columns are stored as `VARCHAR`. Comparing them
  as strings instead of casting to a temporal type will silently "work" (string
  comparison succeeds) while giving the wrong answer for any date-ordering
  question. Cast before comparing.

The table below lists the tables whose row counts the paper cites or that the
H6 detector reads (e.g. "116,211 repositories"). The *popular* tier is the 2,807 repositories with more than 100 stars, for which AIDev additionally provides PR comments, reviews, and timelines ("33,596 agentic PRs in stratum P"). The *full* tier is metadata-only, across all 116,211 repositories.  Each
row is a direct check: if your own download of the pinned revision doesn't
match these counts, something about your download differs from what this
study used. See the paper's "Data
source" section for how these tiers map onto the sampling design.



| Table | Tier | Rows | Cited in the paper as |
|---|---|---|---|
| `all_repository` | full | 116,211 | the full population of repositories |
| `all_pull_request` | full | 932,791 | the full tier's agentic PRs |
| `repository` | popular | 2,807 | stratum P (>100 stars) |
| `pull_request` | popular | 33,596 | agentic PRs in stratum P |
| `pr_comments` | popular | 39,122 | PR comments; the same 39,122 appear as text units in Appendix Table A.2 |
| `pr_reviews` | popular | 28,875 | not cited: used only to join review comments to their PR, contributes no text |
| `pr_review_comments_v2` | popular | 26,868 | review comments; Table A.2 shows 26,867 after dropping one null-body row |



## 5. Scope of this check

This verification looked only at schema, row counts, and field presence — it
never reads or compares PR outcomes (merge rates, review latency, etc.). No
result in this study is derived from the checks recorded in this document.
