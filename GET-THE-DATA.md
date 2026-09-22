# How to obtain the data

This package does not distribute the mined data — no cloned repository, no
rule-file text, no per-repository mining output. This document specifies the
procedure required to reconstruct all of it. None of the steps below is
technically complex, but two are time-consuming: downloading the source dataset
and cloning several thousand repositories.

What the package *does* ship — the coding labels, the consultation validation
sample, and the corpus pointers — is enough to recompute Tables 8, 13, 14 and 15
without any of these steps. See `REPRODUCE.md`.

---

## Step 1 — Install dependencies

Requires Python 3.12 and the following packages:

```bash
pip install duckdb pandas pyarrow numpy matplotlib huggingface_hub langdetect
```

---

## Step 2 — Retrieve the source dataset

The study is derived from **AIDev**, a public dataset of pull requests authored
by coding agents. It is a third-party resource and is not redistributed as part
of this package.

The **exact revision used in the study** must be retrieved, since dataset
versions change over time and the reported figures correspond to a specific one:

```text
AIDev, revision 68ed5f4b80d27a9e057fc57567f38bd322ac73ec
hosted on Hugging Face
```

The pinned revision is recorded in `DATASET_VERSION.md`. To fetch it:

```bash
python src/ingest/cache_tables.py
```

This downloads the corresponding tables into `data/aidev/` (approximately 117 MB).

> **Why the revision must match.** Using the current version of the dataset instead
> of the pinned revision may sample a different underlying population. Any
> discrepancy between the resulting figures and those reported in the paper would
> then be confounded with that difference, rather than attributable to the
> replication procedure itself.

---

## Step 3 — Reconstruct the sample

```bash
python src/mine/select_sample.py
```

This regenerates the list of repositories under study (`data/sample_frame.csv`).
The original list is not shipped, and reusing it would be unnecessary anyway,
since selection is deterministic: repositories are ordered by a hash of their
identifier concatenated with a fixed seed, and the first *N* per stratum are
retained. The seed is recorded in the script. Given the same dataset revision
and the same seed, the resulting sample is identical — which is a stronger
guarantee than a copied file, since a file can be edited and a hash cannot.

The design consists of a census of the highest-visibility stratum plus 1,000
repositories drawn from each of three lower-visibility strata.

---

## Step 4 — Mine the repositories

```bash
python src/mine/mine_harness.py
```

For each repository, this script performs a clone, detects the relevant
artifacts, records the first appearance date of each in the Git history, and
subsequently deletes the local clone. Execution takes on the order of hours and
requires 100–200 GB of transient disk space for the clones in flight.

The output is one JSON file per stratum:

- `data/harness_P_raw.json`
- `data/harness_G1_raw.json`
- `data/harness_G2_raw.json`
- `data/harness_G3_raw.json`

Each file lists, for every cloned repository in that stratum, which artifacts
were detected and when each first appeared in Git history — this is the *raw*,
per-repository mining output, before deduplication or aggregation. `prevalence.py`
and `mechanism_breakdown.py` read all four files directly; `coverage_e2.py`
reads only the stratum-P file, `data/harness_P_raw.json` (Section 6 below).

The same run also saves, alongside those four files, the full text of every
detected rule file (H1) to `data/rulefiles/`, so that the qualitative phase
(Step 5) and the language-sensitivity check (Step 6) do not need to re-clone
anything.

**Exact reproduction of the original results should not be expected.**
Repositories are continuously deleted, renamed, or made private. At the time of
data collection, 6.4 % of the sample was already unreachable, with substantially
higher attrition in lower-visibility strata: 2.7 % in the most visible stratum
versus 14.4 % in the least visible. Repeating the mining procedure at a later
date necessarily observes a different state of the population.

Two additional sources of divergence should be anticipated:

- **Apparent adoption will be higher.** This is specific to H1 (rule files, e.g.
  `AGENTS.md`, `CLAUDE.md`): of the 3,810 such artifacts with a determinable
  introduction date in the original study, 58.3 % first appeared *after* July 30,
  2025 — the closure of the PR-activity window that defines the sample — and
  *before* the original cloning date (August 2026). Repeating this step later
  extends that window further, so an even larger share of rule files will have
  appeared after the sample's defining activity.
- **First-appearance dates remain stable.** These are derived from Git history and
  therefore do not change for repositories that still exist.

---

## Step 5 — Retrieve the qualitative material

```bash
python src/mine/select_qual_sample.py
```

This draws the 150 repositories whose rule files were manually coded. The
underlying text corresponds to the files themselves, saved to `data/rulefiles/`
during Step 4; it is not republished here, as most of the source repositories
declare no license and their content is therefore not ours to redistribute.

You do not need to re-mine to know *which* files were coded:
`data/replication/pi2_corpus_pointers.csv` lists all 285, each with the
repository, path, commit, and git blob SHA, so any one of them can be fetched
and verified by content hash (see `README.md`). `data/qual_sample_key.csv` maps
each item id to its repository and stratum.

To replicate the coding procedure itself, use `qual/codebook_rulefiles.md` in
conjunction with the protocol described in `qual/HOWTO.md`. This is a manual,
human step: two independent coders label every item, following the codebook's
decision procedures, and record one row per repository with the codebook's
categories as columns — the format of the CSVs in `qual/coding/`. The authors
coded through a self-contained HTML instrument that presents each item blind;
the instrument is a convenience, not part of the method, and is not shipped
because it embeds the rule-file text.

---

## Step 6 — Compute the results

Each script is self-contained and may be executed independently, as required.
None writes tables directly into the manuscript; each produces a JSON/CSV report
plus (where noted) a figure, from which the corresponding numbers in
article are read. Three scripts answer RQ1 (observable adoption),
two answer RQ2 (correspondence with the framework):

| Script | Input | Reads results into (paper Section) | Answers |
|---|---|---|---|
| `src/describe/prevalence.py` | `data/harness_{P,G1,G2,G3}_raw.json` | Section 4.2.1 Prevalence, 4.2.3 Breadth, 4.2.4 Co-occurrence, 4.2.5 Temporal adoption | For each mechanism (H1–H8 minus H4), what fraction of repositories have it, how many mechanisms co-occur per repository, and when each was first adopted. |
| `src/describe/mechanism_breakdown.py` | same raw mining output | Section 3.2.2 Deduplication (data cleansing) | Raw artifact counts before and after removing symlinks, undateable artifacts, and byte-identical duplicates. |
| `src/describe/coverage_e2.py` | `data/harness_P_raw.json` (stratum P only) + `data/aidev/pull_request.parquet` | Section 4.2.5 Temporal adoption, "Coverage of observed work (E2)" | Of the agentic PRs actually recorded, what proportion were opened *while* the repository already had the mechanism (E2), versus simply having it now (E1, at cloning). |
| `src/describe/plots.py` | `data/prevalence_report.json` (output of `prevalence.py`) | Figures in Section 4.2 (e.g. the monthly first-appearance histogram) | Renders the two figures cited in the Results section. |
| `src/qual/h5_language_sensitivity.py` | `data/rulefiles/` (Step 4) restricted to a candidate list, `data/h5_zero_candidates.json`, of H1 artifacts with zero detected normative clauses | Section 3.2.8 Corpus language, and why it is measured | What fraction of rule files are not in English, which bounds how many H5 (normative-content) zeros could be a detection error rather than a true absence. |
| `src/qual/score_rulefiles.py` | the coder CSVs exported from `qual/coding/rulefile_coding_it*.html` (Step 5), named `qual/coding/rulefiles_<coder>_it<N>.csv` | Section 4.3.1 Reliability (Cohen's κ per category) | Whether the two human coders agreed enough, per RQ2 category (M1–M8), to trust the coding as the measurement instrument for RQ2. |

> **Known gap.** No script in this package generates `data/h5_zero_candidates.json`.
> It has to be produced before `h5_language_sensitivity.py` can run: the list of
> repositories whose only H1 artifacts are non-stub rule files scoring zero
> normative clauses in `data/harness_{P,G1,G2,G3}_raw.json` (field
> `normative_clauses == 0`, `mechanism == "H1_context_engineering"`, excluding
> symlinks and stub files as in Step 4's deduplication). This package does not
> yet ship that extraction step.

To run them:

`prevalence.py` takes a single `--raw` flag followed by *all four* stratum files
at once — not one call per stratum. This is required, not a convenience: the
script computes prevalence *jointly* across P, G1, G2, and G3, re-weighting each
stratum by how much of the population it represents (Section 3.2.6,
"Descriptive measures"); it cannot produce a correct reweighted figure from a
single stratum's file. 

```bash
python src/describe/prevalence.py --raw data/harness_P_raw.json \
    data/harness_G1_raw.json data/harness_G2_raw.json data/harness_G3_raw.json
python src/describe/mechanism_breakdown.py
python src/describe/coverage_e2.py
python src/describe/plots.py
python src/qual/h5_language_sensitivity.py
python src/qual/score_rulefiles.py
```

The consultation detector, `src/classify/consultation_full.py`, is not in the
table above because it reads the AIDev PR-comment tables (fetched in Step 2)
rather than the mining output; its human validation,
`src/classify/score_validation_full.py`, runs from this package alone. Both are
mapped in `REPRODUCE.md`.

No orchestration script is provided, by design: this package is intended for
inspection and verification of each step, not for one-command execution.




