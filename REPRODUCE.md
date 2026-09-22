# Where each result comes from

Every table and figure in the paper, traced to the script that builds it and
the data it reads. The last column says whether you can rebuild it from this
package alone, or whether you first need the mined data (`GET-THE-DATA.md`).

`D` = `data/`. Scripts live under `src/`, in the same layout as the authors'
repository, because every script locates its inputs relative to its own
position.

---

## Rebuildable from this package alone

| In the paper | Command | Reads | Writes |
|---|---|---|---|
| **Table 8** — H6 validation by classifier block | `python src/classify/score_validation_full.py` | `D/consultation_validation_sample_full.csv`, `D/consultation_report_full.json`, `qual/coding/labels_coder{1,2}_full.csv` | `D/c6_validation_full.json` |
| **Table 13** — inter-coder reliability, iteration 1 | `python src/qual/score_rulefiles.py --iteration 1` | `qual/coding/rulefiles_coder{1,2}_it1.csv`, `D/qual_sample_key.csv` | `D/pi2_report_it1.json` |
| **Table 14** — inter-coder reliability, iteration 2 | `python src/qual/score_rulefiles.py --iteration 2` | `qual/coding/rulefiles_coder{1,2}_it2.csv`, `qual/coding/rulefiles_resolved_it2.csv`, `D/qual_sample_key.csv` | `D/pi2_report_it2.json` |
| **Table 15** — prevalence of each RQ2 category, by stratum | same run as Table 14 | idem | idem, key `results_by_stratum` |

The reliability figures in Tables 13 and 14 are under `reliability` in the
report; Table 15 is `results_by_stratum`. `proc_share` is not in the shipped
labels, so its mean absolute difference (mentioned in the codebook) is not
recomputed; nothing in the paper's tables depends on it.

## Needs the mined data first

Run `GET-THE-DATA.md` steps 2–4 to obtain `D/harness_{P,G1,G2,G3}_raw.json`,
then:

| In the paper | Command | Reads | Writes |
|---|---|---|---|
| **Table 3** — sample disposition by stratum | `python src/describe/prevalence.py --raw D/harness_*_raw.json` | the four raw files | `D/prevalence_report.json`, key `attrition_by_stratum` |
| **Table 4** — artifacts per mechanism, raw vs deduplicated | `python src/describe/mechanism_breakdown.py` | idem | `D/mechanism_breakdown.json` |
| **Table 5** — prevalence by stratum (E1) | `prevalence.py` (same run as Table 3) | idem | `D/prevalence_report.json`, key `prevalence` |
| **Table 9** — breadth distribution | same run | idem | key `breadth_distribution` |
| **Table 11** — sensitivity to the stub filter | same run | idem | key `sensitivity_stubs_kept` |
| **Table 12** — sensitivity to single-PR projects | same run | idem | key `sensitivity_ge2_agentic_prs` |
| **Figure 3** — co-occurrence matrix | `python src/describe/plots.py` | `D/prevalence_report.json` | `figures/cooccurrence_heatmap.pdf` |
| **Figure 4** — monthly first appearances of H1 | same run | idem | `figures/h1_adoption_curve.pdf` |
| **Table 10** — E2 versus E1 | `python src/describe/coverage_e2.py` | `D/harness_P_raw.json`, `D/aidev/pull_request.parquet` (step 2) | `D/coverage_e2_report.json` |
| **Table 6** — normative clauses by corpus language | `python src/qual/h5_language_sensitivity.py` | the four raw files, `D/rulefiles/` (step 4), `D/h5_zero_candidates.json` | `D/h5_language_sensitivity.json` |
| **Table 7** — dominant language of the zero-clause files | same run | idem | idem |

Tables 3, 5, 9, 11 and 12 all come out of one `prevalence.py` run: they are
different views of one report, not five analyses. `prevalence.py` must be given
all four stratum files at once — it reweights each stratum by the share of the
population it represents, and cannot do that from one file.

**Expect these numbers to differ from the paper's.** They depend on cloning
live repositories, and repositories disappear; `GET-THE-DATA.md` step 4
quantifies how much and in which direction.

On `D/h5_zero_candidates.json`: no script in this package produces it. See the
*Known gap* note in `GET-THE-DATA.md`.

## Not produced by any script

| In the paper | Source |
|---|---|
| **Table 1** — sampling design | `src/mine/select_sample.py` → `D/sample_frame.csv`, plus the population counts from AIDev |
| **Table 2** — operationalization of the mechanisms | the detection patterns, published in full inside `src/mine/mine_harness.py` |
| **Table A.1** — AIDev scale by stratum | row counts from `DATASET_VERSION.md` and `src/ingest/step_zero.py` |
| **Table A.2** — composition of the H6 text corpus, by surface and authorship | `python src/classify/consultation_full.py` (needs the AIDev comment tables, step 2); the `surface` and `agent_authored` columns of its output |
| **Table B.1** — the same question under three readings | worked example; derived from Tables 5 and 10 |
| **Figures 1–2** — the harness, and the study design | drawn by the authors |

---

## The pinned dataset

AIDev, revision `68ed5f4b80d27a9e057fc57567f38bd322ac73ec`. `src/ingest/step_zero.py`
verifies the pin and the schema before anything downstream runs; if the dataset
has moved, it stops rather than silently analysing a different version.
