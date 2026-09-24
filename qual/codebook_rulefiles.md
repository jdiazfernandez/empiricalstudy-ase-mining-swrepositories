# Codebook — rule-file content (RQ2), condensed

What a reader needs to interpret the labels in `qual/coding/rulefiles_*.csv`.
The full codebooks — three versions with their iteration log, worked examples,
and the rationale behind each decision rule — are in the authors' repository;
this file keeps only the definitions the labels rest on.

**Unit of analysis:** one repository, coded over its *whole* rule-file corpus
(all its `CLAUDE.md` / `AGENTS.md` / `.cursor/rules/*` files together). A
category is present if *any* file realises it. Presence is about **content**,
never about file name: a file called `CLAUDE.md` is not automatically M1.

---

## The labels

### Mechanisms M1–M8 — `1` present, `0` absent

| | Category | Present when the text… |
|---|---|---|
| **M1** | Context engineering | orients the agent in the project: what lives where, how to build and run it, layout and naming conventions |
| **M2** | Persistent knowledge | records decisions **and their rationale**, or points to where they are recorded |
| **M3** | Executable specifications | **states** an acceptance criterion, behavioural contract, or API contract as an obligation a change must satisfy |
| **M5** | Normative specifications | states standing constraints that hold across tasks — modal obligations and prohibitions |
| **M6** | Structured consultation | tells the agent **when to stop and ask** a human, rather than decide |
| **M7** | Evidence-based acceptance | states what evidence must accompany a change: tests, checklists, CI output |
| **M8** | Graduated autonomy | distinguishes what the agent may do alone from what needs approval, by area, risk or blast radius |

M4 (N-version isolation) is not coded: it leaves no trace in a repository.

**Two boundaries that decide most hard cases:**

- **M5 vs M3.** A standing prohibition is M5; a checkable condition on one
  feature's behaviour is M3. *"Never log PII"* is M5. *"A refund above the
  unrefunded balance must be rejected with 422"* is M3.
- **M6 vs M8.** M8 says *who decides*; M6 says *the agent must stop and raise
  the question*. *"Billing needs a human reviewer"* is M8. *"Stop and ask before
  changing a public signature"* is M6. Text can be both.

### Decision rules added in v2

Iteration 1 failed reliability on M3, M6 and M8. These three tests were added,
stated as principles so they apply to unseen corpora:

- **M3 — state, do not mention.** *Could a reviewer quote this sentence to
  reject a change?* If it only says that specifications exist, or how to build
  or run them, it is M1, not M3. *"100 % test coverage is required"* constrains
  everything rather than one feature: M5 (and usually M7), not M3.
- **M6 — wait, do not merely warn.** *After doing what the sentence says, does
  the agent stop?* "Warn the user before proceeding" continues, so it is not M6;
  "stop and wait for confirmation" is.
- **M8 — who may act, not what must happen first.** An area-scoped prohibition
  ("do not edit `website/` unless asked") counts. A mechanical precondition
  ("never edit without first running the impact tool") is M5. File-system
  permissions (`chmod`) are not authorisation and are not M8.

### `orientation` — `NORM`, `MIXED` or `PROC`

The corpus as a whole, judged by weight, not by count:

| Code | Meaning |
|---|---|
| `NORM` | Predominantly normative: standing constraints that hold regardless of the task |
| `MIXED` | Substantial amounts of both, neither clearly dominant |
| `PROC` | Predominantly procedural: step-by-step recipes for particular tasks |

*The test:* does this passage constrain the agent no matter what it is doing,
or tell it how to carry out one kind of task? Orientation material (M1 content)
is neither and is counted on no side.

### `proc_substantial` — `1` or `0`

**Not coded directly.** Derived from `orientation` by a mapping fixed in
codebook v3 before recomputation: `MIXED` and `PROC` → `1`, `NORM` → `0`. The
three-way `orientation` failed the reliability gate in both iterations; the
binary is what the paper reports (column PS in Table 15), and Table 14's
caption says so. A derived binary is not the same measurement as one asked
directly.

### `addressed_to`

`generic` · `specific-tool` (names Claude, Cursor, Copilot, Gemini…) · `both`

### Structural columns

`item_id` (anonymous, `R000`–`R149`; `data/qual_sample_key.csv` maps it to
repository and stratum) · `coder` · `order_index` · `in_overlap` (`1` for the
30 items both coders labelled, on which reliability is measured).

---

## Scoring rules (codebook v3, fixed before recomputation)

- **Gate.** Cohen's κ ≥ 0.60 per category on the 30-item overlap.
- **Extreme prevalence.** When a category's base rate on the overlap exceeds
  85 %, κ is uninformative (two disagreements in thirty destroy it) and the
  category is judged by raw agreement ≥ 0.90 instead. This applies to M1 and
  M5. Prevalence-adjusted kappa (PABAK) is never used.
- **Two strikes.** A category that fails in two consecutive iterations, the
  second after an amendment aimed at it, is reported as not reliably codeable.
  No category is currently in that state.
- **Adjudication.** Where the two coders disagree on the overlap, a third
  author decides. The adjudicated labels (`rulefiles_resolved_it2.csv`) are the
  reference for results; κ is always computed on the coders' independent
  labels and never changes after adjudication.

---

## Versions, in one paragraph each

**v1** — the frozen codebook. Iteration 1 on `R000`–`R029`: M3, M6, M8 and
`orientation` below 0.60. Table 13.

**v2** — the three decision rules above, written as principles. Iteration 2 on
a fresh block, `R030`–`R059`: every category passes once nine transcription
errors in the overlap labels (five in M6/M8, four in `orientation`) were
corrected. Table 14.

**v3** — no change to any category; only the scoring rules above, plus the
`proc_substantial` derivation. Applied to the iteration-2 labels. No third
coding round was needed.
