# Replication package

**Methodological Harness in Agentic Software Engineering: An Empirical Study on
Mining Software Repositories**
Jessica Diaz, Jorge Perez, Sergio Gil-Borras — Universidad Politecnica de Madrid

---

## What this is

This package contains the instrument behind both halves of the study:

- **Quantitative (RQ1, adoption).** Code that decided which artifacts — rule files
  (e.g. `AGENTS.md`, `CLAUDE.md`), specifications, architectural decision records (ADRs),
  `CODEOWNERS`, and the like — counted as evidence that a given harness mechanism was
  present in a repository, and when it first appeared. Seven of the eight mechanisms
  are operationalized this way, mostly through deterministic file-path and lexical-pattern
  detectors run against a bare git clone, across 5,435 repositories.
- **Qualitative (RQ2, alignment).** The codebooks that told two human coders how to read
  a rule file's actual content — not just whether it exists, but whether it materializes
  the constructs the framework postulates — plus the protocol for coding independently,
  measuring agreement, and adjudicating disagreement, applied to 285 rule files from
  150 repositories. **The coders' labels are included**, so the reliability and
  prevalence figures for RQ2 can be recomputed here, offline.

## What this is NOT

**It does not contain the mined data.** No cloned repository, no rule-file text,
no per-repository mining output. That is deliberate, and not a shortcut:

- The repositories we mined belong to other people. Most of them declare no
  licence at all, which means all rights reserved. We may not hand out copies.
- The dataset we sampled from (AIDev) belongs to its own authors. It is better
  fetched from them, at the exact version we used, than copied by us.
- Mining the live web is not repeatable anyway. Repositories get deleted and
  renamed every day. Anyone who mines again gets a slightly different world, and
  we would rather say so than pretend otherwise.

So instead of the mined data, this package gives you **instructions for obtaining
it yourself**: see `GET-THE-DATA.md`. What it *does* ship is the small set of
files that are ours and that the scripts need: the human coding labels, the
validation sample for the consultation detector, and content-addressed pointers
to every coded rule file (so you can retrieve and verify the exact bytes we read
without us redistributing them).

## What is inside

```text
README.md              you are here
GET-THE-DATA.md        step by step, how to obtain the mined data
REPRODUCE.md           which table comes from which script, and what each needs
DATASET_VERSION.md     the exact version of AIDev we used
LICENSE.txt            MIT for the code, CC BY 4.0 for our data
requirements.txt       pinned Python dependencies

src/                   the scripts the paper cites, by pipeline stage
  ingest/                fetch and verify the pinned dataset
  mine/                  choose the sample, clone, extract artifacts
  features/              the deduplication rule
  describe/              prevalence, breadth, coverage, figures
  classify/              the structured-consultation detector and its validation
  qual/                  scoring of the human coding, corpus language

tests/                 proof that the detectors fire on known inputs

qual/                  the human-coding instrument and its output
  codebook_rulefiles.md      the labels for the rule-file coding, and the
                             rules that produce the reliability tables
  codebook_consultation.md   the label for the consultation coding
  HOWTO.md                   the coding protocol: independence, overlap,
                             gate, iterations, adjudication
  coding/                    the labels: two coders x two iterations, the
                             adjudicated labels, and the consultation labels

data/                  the files our scripts read that are ours to ship
  qual_sample_key.csv                   item id -> repository and stratum
  consultation_validation_sample_full.csv   the 536 items selected for human
                                            validation of the H6 classifier
  consultation_report_full.json         the H6 detector's block populations
  consultations_full.parquet            classifier features for all scanned
                                        comments and PR bodies; text omitted
  replication/
    pi2_corpus_pointers.csv             repository, path, commit, blob SHA of
                                        every coded rule file
    replication_report.json             licence composition of the sample
```

Each of these is described somewhere specific in the paper (`main_EMSE_final.tex`):

| Package path | Paper section |
|---|---|
| `src/ingest/` | 3.1.1 Data source |
| `src/mine/select_sample.py` | 3.1.2 Population and sample design |
| `src/mine/mine_harness.py` | 3.2.1 Artifact extraction |
| `src/features/` (deduplication) | 3.2.2 Deduplication (data cleansing) |
| `tests/test_detectors.py` | 3.2.3 Operationalization of harness mechanisms (Table "Operationalization") |
| `src/describe/prevalence.py` | 4.2.1 Prevalence, 4.2.3 Breadth, 4.2.4 Co-occurrence |
| `src/describe/coverage_e2.py` | 4.2.5 Temporal adoption (coverage of observed work, E2) |
| `src/describe/mechanism_breakdown.py` | 3.2.2 Deduplication (data cleansing) |
| `src/describe/plots.py` | 4.2 RQ1: Observable adoption (figures) |
| `src/classify/` (structured-consultation detector) | 3.3.6 Descriptive measure (H6); validated in 4.2.1 Prevalence |
| `src/qual/score_rulefiles.py`, `qual/coding/` | 4.3.1 Reliability, 4.3.2 Prevalence of categories |
| `src/qual/h5_language_sensitivity.py` | 3.2.8 Corpus language, and why it is measured |
| `qual/codebook_rulefiles.md`, `qual/HOWTO.md` | 3.3 Qualitative study: RQ2 — alignment with the framework |
| `data/replication/pi2_corpus_pointers.csv` | 3.4 Reproducibility and content handling |

---

## What you can recompute right now, without any download

Three of the paper's results depend only on what is in this package:

```bash
pip install -r requirements.txt
python src/qual/score_rulefiles.py --iteration 1     # Table 13
python src/qual/score_rulefiles.py --iteration 2     # Tables 14 and 15
python src/classify/score_validation_full.py          # Table 8
python tests/test_detectors.py                        # the detectors fire
```

Each writes a JSON report under `data/`; the numbers in it are the ones in the
corresponding table. Everything else in the paper — prevalence, breadth,
co-occurrence, the temporal estimands — needs the mined data, and
`GET-THE-DATA.md` explains how to obtain it and what to expect when you do.

---

## Where to look, depending on what you want to check

### "Am I even starting from the same data?"

Read **`DATASET_VERSION.md`** before anything else in `GET-THE-DATA.md`. It
pins the exact AIDev revision this study used, explains why that revision
matters (the source repository was edited long after data collection ended,
but no new PRs were added), and records what was verified about its schema and
row counts before mining began.

### "How did you decide a repository has mechanism X?"

Open **`src/mine/mine_harness.py`**. The detection patterns are written out in
full, in the source, not summarised. Every file name and *glob* — a wildcard
path pattern, e.g. `.cursor/rules/*.mdc` matching any file in that folder — we
looked for is there to be disagreed with.

Then open **`tests/test_detectors.py`**. It builds small synthetic repositories
where the answer is known in advance and checks the detectors find them. This
matters more than it looks: without it, a mechanism reported as *absent* could
equally mean *our detector was broken*. The test is what lets a zero be read as
a measurement.

Run it — it needs no data:

```bash
python tests/test_detectors.py
```

### "How did two people agree on what a rule file says?"

Read **`qual/codebook_rulefiles.md`**. It gives each category, the boundary
tests that decide the hard cases, and the scoring rules that turn two coders'
labels into the reliability tables. It is condensed on purpose: the labels and
the rules, not the worked examples. Coding ran in numbered rounds — code
independently, measure agreement, and either accept it or amend the codebook
and start a fresh round — and the codebook's last section records what each
round changed and why.

**`qual/HOWTO.md`** is the protocol: how independence was protected, how the
reliability overlap was chosen, what the gate is, and how disagreements were
adjudicated.

**`src/qual/score_rulefiles.py`** computes the agreement. Two rules in it are
worth reading, both fixed before seeing results: what to do when a category is
so common that the usual agreement statistic stops being meaningful, and what
happens to a category that fails twice.

**`qual/coding/`** holds what the coders produced: one CSV per coder per
iteration, the adjudicated labels for iteration 2, and the labels for the
consultation validation. Each row is one repository (or one comment); the
columns are the codebook's categories. Run the scorer on them and you get the
paper's reliability tables.

### "Which files did you actually code?"

**`data/replication/pi2_corpus_pointers.csv`** — one row per coded file, 285
rows across the 150 sampled repositories, with the repository, path, the commit
we read it at, and its git **blob SHA**. That last column is a content hash: you
can retrieve exactly the bytes we coded and prove they are the same bytes.

```bash
git clone --bare https://github.com/<repository>.git repo.git
git --git-dir=repo.git cat-file blob <blob_sha>
```

This is stronger than shipping the text would be. A copy in an archive could
drift from what we actually read; a content hash cannot.

### "Where do the numbers in each table come from?"

See **`REPRODUCE.md`**, which maps every table and figure to the script that
builds it and the data it reads, and marks which ones you can rebuild from this
package alone.

### "How was the sample chosen?"

**`src/mine/select_sample.py`**. The selection is deterministic: repositories
are ordered by a hash of their id combined with a fixed seed, and the first N
are taken. The seed is in the file. Run it on the same dataset version and you
get the same sample, every time — no randomness to argue about.

---

## One thing worth knowing before you judge the numbers

The study measures **adoption**, not effect. It reports how many repositories
have each mechanism, not whether having it made anything better. There are no
outcome variables anywhere in this code, and that is by design: you cannot
sensibly ask whether something helps before establishing that it exists.

If you go looking for the regression that tests whether the harness works, it is
not here, and not because it was hidden.

---

## Contact

Corresponding author: Jessica Diaz, Universidad Politecnica de Madrid.
If a detector looks wrong to you, or a recomputed table does not match the
paper, that is a useful thing to tell us. Please include your Python version and
the output of `pip freeze`.
