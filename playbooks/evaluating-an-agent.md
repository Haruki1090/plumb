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

## Evaluating a skill that runs a workflow

A review is scored by F1. A workflow skill such as `plumb:lead` is scored on four axes instead,
each with its own instrument. Build them before the first real run, not after it.

| Axis | Question | Instrument |
|---|---|---|
| Triggering | Does it fire on the asks it owns, and stay quiet on near misses? | `plumb-trigger-eval` over a case CSV |
| Process | Did it follow its own steps and keep out of forbidden actions? | `plumb-lead-grade` over the transcript and ledger |
| Spend | What did the coordinator carry, and what did one finished unit cost? | `plumb-session-audit` (both runtimes) |
| Input and output quality | Were the briefs good material, and was the result evidence? | The skill's rubric, graded in the judge role |

**Triggering.** A case CSV has `id,prompt,expect`; `expect` is the skill that must fire or `-`.
Mix the asks the skill owns with near misses that belong to a neighbour (a single PR URL, one
bug, a request only to list). Run it on every model that will hold the coordinator seat:

    plumb-trigger-eval --cases evals/lead/triggers.csv --skill plumb:lead \
      --model <model> --cwd <project> --out <run>/triggers

Each case starts one headless session in plan mode and stops at the first tool call that is not a
Skill call. The pass bar is zero false positives and zero false negatives. Keep private cases
(real repository names, the owner's language) under `bench.corpus`, not in this repository.

**Process and triage.** Before the run, **label the queue yourself**: one TSV row per item with
the state the skill should reach (`landed`, `ready`, `needs-ruling`, ...). That golden file is what
turns "garbage in" into a number. Then:

    plumb-lead-grade --transcript <session.jsonl> --golden <golden.tsv> --stop-line plan|ready-pr

**Stage it.** Triggering first. Then a dry run on the real queue with the stop line set to the
plan, once with the skill and once without it (the baseline): the difference in triage accuracy
and in coordinator tokens is what the skill buys. Only then a live run, capped at two lanes.
A change to the skill reruns all three; a shorter body that drops a trigger or a process check is
a regression, not a saving.

## How to tell

Can you name the configuration running today, its F1, its tokens per review, and the date those two
numbers were last measured on this corpus? If not, the configuration is a habit, not a decision.

**What you return:** the corpus revision, every run's precision / recall / F1 / tokens per review, the Pareto configurations, the chosen move, the decision-log path, and the next re-run trigger.
