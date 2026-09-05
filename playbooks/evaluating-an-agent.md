# Evaluating an Agent

**You hold the corpus, the blind, and the decision.** The candidate produces verdicts. The scorer
produces numbers. Neither decides which configuration runs in production.

The job is to decide, with a number, which configuration of a playbook or agent to run, and to move
when that number moves.

## What the number means

F1 measures whether a configuration finds the bugs this corpus knows about without filling the
verdict with other BLOCK and FIX findings. Precision, recall, and F1 are reported together so a
quiet reviewer and a noisy reviewer cannot hide behind the same count.

F1 does not say whether the reviewed work was worth doing. That unit belongs to
**principle-spend-on-the-outcome**. This bench fixes the unit at one review and reports tokens per
review; it does not turn token volume into a business outcome or a price.

## Build the corpus, then prune it

Extract draft items from follow-up fix PRs:

```bash
plumb-bench-extract --repo <owner/name> --out <corpus-directory>
```

The fix is only a draft label. Open every `truth.json`, delete hunks that are cleanup, docs, or not
part of the bug, and set `reviewed: true` on every hunk that remains. Then set `grade` in `pr.json`:

- `easy`: one obvious local error
- `medium`: a mismatch that crosses files
- `hard`: behavior that needs the surrounding system to see

Start with 10 items, split 3-4 per grade. On rerun, existing items are kept and new pairs are added;
`--refresh <id>` alone rewrites one, and refuses reviewed truth because the person's pruning outranks extraction (**principle-make-operations-idempotent**).

An unpruned corpus scores nothing. The scorer refuses a corpus in which no item has a reviewed truth
entry, and skips individual items that have not been pruned yet.

## Blind every run

Start a fresh session for each item and configuration. Give the candidate only `pr.json`'s `repo`,
`number`, and `sha`, and require the review to stay pinned to that SHA.
Truth ranges are line numbers in the tree at `pr.json.sha`, so findings and labels share coordinates.

The candidate must not see:

- `truth.json`
- the fixing PR or its number
- this playbook or any evaluation wording
- another candidate's verdict

The fix still exists in repository history after the pinned SHA. plumb cannot hide that history.
The run instruction therefore forbids reading commits, diffs, branches, or tags after the pinned
SHA. Discard a verdict that cites a later commit; do not score a run whose blind was broken.

## Run one review per cell

Name a run for the configuration, not for the candidate. Record what varied: depth, judge on or off,
and the relevant config-file values. Do not put implementation names in the run name.

Run each corpus item as one review in its own dedicated project directory, and save these artifacts:

```text
<run>/<id>/verdict.md
<run>/<id>/session.json
```

Save the `plumb:pr-review` return in `verdict.md`, then audit the whole dedicated project directory
beside it:

```bash
plumb-session-audit --transcripts <the dedicated project directory> --all --json > <run>/<id>/session.json
```

One dedicated directory per item keeps tokens per review attributable. A review that spawns teammates
is several sessions, so `--session` or `--last 1` would report only one of them. Reusing a directory
carries prior items and their hints into the next review, breaking both the cost unit and the blind.

## Score and decide

Compare runs in one command:

```bash
plumb-bench-score --corpus <corpus-directory> \
  --run depth-a=<run-directory> --run depth-b=<run-directory>
```

Read precision and recall before F1, then read the Pareto line. Move to a configuration on that
frontier: no other measured run gives it at least as much F1 for no more tokens per review.

Before proposing a lower-token replacement for the current configuration, apply the acceptance gate:

```bash
plumb-bench-score --corpus <corpus-directory> \
  --run current=<baseline-directory> --run proposed=<candidate-directory> \
  --baseline current --candidate proposed
```

**A cheaper candidate that loses quality is not accepted.** The gate checks precision, recall and F1
overall and per grade, complete verdict/cost coverage, and both mean and median token improvement.
Its exit status is the decision input; it never changes the configured role. The detailed contract is
`skills/pr-review/references/bench-format.md`.

Hold workload, truth revision, and scoring options fixed. Repeat blind runs and reserve holdout cases
before changing a default. Record completion failures and elapsed time alongside each run: the token
gate alone does not measure those dimensions. Optimize prompts, retrieval and verification only
against training examples; use held-out cases to reject overfitting. A new failure becomes a regression
case before its repair becomes a new default.

Record every move instead of overwriting the last choice:

```bash
plumb-decision-log <log> --header date run f1 tokens-per-review decision
plumb-decision-log <log> 2026-09-02 depth-a 0.71 184000 adopted
```

This is the multi-metric decision. For the one-change, one-measurement loop around it, use
`playbooks/hillclimb.md`; do not duplicate that loop here.

Keep moving. Rerun the corpus when the tools underneath a configuration change, when the corpus is
re-pruned, or when a new grade changes what it represents. The Pareto frontier is a measurement,
not a permanent ranking.

## How to tell

Can you name the configuration running today, its F1, its tokens per review, and the date those two
numbers were last measured on this corpus? If not, the configuration is a habit, not a decision.

**What you return:** the corpus revision, every run's precision / recall / F1 / tokens per review, the Pareto configurations, the chosen move, the decision-log path, and the next re-run trigger.
