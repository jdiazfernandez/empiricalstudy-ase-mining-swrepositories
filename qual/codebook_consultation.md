# Codebook — structured consultation (H6), condensed

What a reader needs to interpret `human_label` in `qual/coding/labels_*.csv`.

**Unit of analysis:** one agent-authored text — a PR body, a comment, or a
review comment. **Label:** `1` = structured consultation · `0` = not · `?` =
cannot decide (reported separately, never coerced to 0 or 1).

## The construct

> The agent **suspends execution** when it encounters a decision it cannot or
> should not resolve, and raises a **scoped consultation request**.

Two words do all the work: *suspends*, and *scoped*.

## The decisive question

> **Did the agent stop and wait for a human to decide — or did it decide, act,
> and then narrate?**

Consultation happens *before* the fact; a rationale happens *after*. An agent
that explains the alternatives it weighed after implementing one is not
consulting, however thorough the explanation.

## Label `1` — all four must hold

| | Criterion |
|---|---|
| **C1** | **Agent-authored.** Pre-filtered; flag it if wrong. |
| **C2** | **Seeks a decision.** Asks a human to choose or confirm — not reporting, explaining, answering or announcing. |
| **C3** | **Scoped.** A specific bounded question. *"Offset or cursor pagination?"* qualifies; *"what should I do next?"* does not. |
| **C4** | **Genuinely open.** The agent has *not* already implemented its preference. Recommending is fine; the choice must still be the human's. |

Partial forms count: an agent that stops and asks a scoped question with two
options but cites no specification is still consulting. The framework's full
ideal (question + options + spec clause + consequences) is a target, not the
coding bar.

## Label `0` — the recurring patterns

| Pattern | Fails | Typical opener |
|---|---|---|
| Completion or review report | C2 | `Claude finished @X's task`, `- [x] …` |
| Answering a human | C2 | `Great question!`, `You're right` |
| **Post-hoc rationale** — the most common near-miss | C4 | `I chose X because…`, `Alternatives considered:` |
| Explanation of the codebase | C2 | `These aren't two definitions — package A is…` |
| PR template boilerplate | C1/C2 | `## Description`, `- [ ] I have…` |
| Announcing next steps | C2 | `Next I'll implement…` |

*"Let me know if you want changes"* is `0`: a closing courtesy is not a scoped
question.

## `?`

Only for genuine indeterminacy — truncated text, a language the coder cannot
read. "Probably not" is `0`.

## Reliability

The second coder labels the first 20 % of items in the same order. Cohen's κ on
that overlap; disagreements adjudicated by a third author. The classifier's own
verdict is hidden from the coders while they code.
