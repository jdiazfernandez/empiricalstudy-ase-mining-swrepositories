# Coding protocol, condensed

How the two human codings were run. The operational checklist the coders
followed (keystrokes, instrument pages, timings) is in the authors' repository;
this keeps the rules that make the labels in `qual/coding/` interpretable.

| | Coding | Codebook | Unit | Items | Labels |
|---|---|---|---|---|---|
| **A** | H6 — structured consultation | `codebook_consultation.md` | one agent-authored text | 536 | `labels_coder{1,2}_full.csv` |
| **B** | RQ2 — rule-file content | `codebook_rulefiles.md` | one repository, whole corpus | 150 | `rulefiles_coder{1,2}_it{1,2}.csv` |

## Independence

- Two coders, labelling **independently**, with no discussion of items during
  coding. Disagreements are left standing; they are data.
- The instrument is **blind**: the coder sees an opaque item id, the file paths
  and the text. Repository name, stratum, star count and the mining stage's
  modal-clause count are withheld. The mapping back to repositories
  (`data/qual_sample_key.csv`) is used at analysis time only.
- The calibration warm-up used five items from **outside** the sample, so the
  reliability block was never discussed before it was coded.

## Reliability overlap

- **B:** the second coder labels a block of **30 items** (20 % of 150), the
  first 30 in the instrument's order. The block is **fresh in each iteration**
  — `R000`–`R029` in iteration 1, `R030`–`R059` in iteration 2 — so an amended
  codebook is never validated on the items whose disagreements prompted the
  amendment. Column `in_overlap` marks it.
- **A:** the second coder labels the first 20 % of items (107 of 536).
- Cohen's κ is computed on the overlap, per category. **Gate: κ ≥ 0.60.**
  Categories with a base rate above 85 % are judged by raw agreement ≥ 0.90
  instead (`codebook_rulefiles.md`, scoring rules).

## Iterations (coding B)

One iteration is: both coders label the overlap → `src/qual/score_rulefiles.py`
→ if every category clears the gate, adjudicate and stop; otherwise amend the
codebook **with a dated amendment, never a silent edit**, bump its version, and
run another iteration on a fresh block. Two iterations were run; a third was
prepared and not needed. The scorer exits non-zero when a category fails, so a
failure cannot pass unnoticed.

## Adjudication (coding B)

Where the two coders disagree on the overlap, a **third author** decides,
shown the two readings in random order without knowing which coder chose
which. The resolved labels (`rulefiles_resolved_it2.csv`) are the reference for
the results; **κ is never recomputed on them** — it must keep describing what
two people agreed on independently.

Adjudication touches the overlap only. The other 120 items rest on the lead
coder alone, and the paper says so.

## Running the scorers

```bash
python src/qual/score_rulefiles.py --iteration 1     # Table 13
python src/qual/score_rulefiles.py --iteration 2     # Tables 14 and 15
python src/classify/score_validation_full.py          # Table 8
```

Both print reliability first and results second, deliberately.
