---
name: failure-to-rule
description: Take one agent failure (an issue or pull request labelled agent-failure, a failed trial, a finding, a mistake an agent made) to the layer that should stop it next time, with a measurement and a draft change. Load this first, before reading the issue or the code, whenever asked to "turn this failure into a rule", "make sure this mistake doesn't happen again", "stop this from recurring", "work this agent-failure out" or "classify this failure", or when plumb:retro picked a failure to work. Not for fixing the defect itself (playbooks/fixing-a-bug.md) or for the weekly look back (plumb:retro).
---

# One failure to the layer that stops it

Decide where, next time, the same failure is stopped, and how you will know it was. The record
format, the codes C01–C15 and the layers are `docs/failure-taxonomy.md`; this skill cites them and
never restates them.

## Boundaries

- Investigate, write the analysis, and draft the change. A change to plumb or to a personal setting
  goes to a draft pull request or the owner; a **CI rule of the repository is proposed, never
  landed**: it stops everyone's work, so its owners decide, and you say so.
- A new rule never fixes all existing violations at once: it freezes today's count and blocks only
  increases (a ratchet).
- Never propose deleting, skipping or weakening a test or a check.

## Steps

1. **Read the record.** Its block (`<!-- plumb:failure v1 {...} -->`), the evidence it points to,
   the change in `origin` and the change that fixed it. If the evidence cannot be read, stop and say
   which pointer failed. If the record has no block or an unknown field, decide them now and write
   the block you would put on the record.
2. **Say what happened and why the agent did not notice**, in two or three lines. The reason is one
   of: no step told it to, no way to check existed, or it lacked the knowledge.
3. **Look for the same failure elsewhere.** The same code and the same files in the work ledger
   (`plumb-ledger changes`, `plumb-ledger failures`), and the same pattern left in the code (C06).
4. **Choose the layer**, trying the most deterministic first (`docs/failure-taxonomy.md`, "Layers"):
   - the failure can be recognised from the shape of the code or the change → a CI rule of the
     repository (`contract`): specify what it stops and what it does not, its false-positive cases,
     today's count and the ratchet;
   - it cannot, but a step or a check in how agents work would prevent it → plumb (`harness`): the
     skill, playbook or agent to change, and the step to add;
   - it is a fact only this repository knows → its contract or documents (`contract`);
   - it is one person's setup → `personal`.
   When unsure, take the higher row: a sentence alone is the hardest change to measure.
5. **Decide the measurement before the change.** A rule: today's count, and the rework of that code
   afterwards. A harness change: three to five small tasks that reproduce the failure, run with and
   without the change and graded in the judge role (`playbooks/evaluating-an-agent.md`); a routing
   change: trigger cases (`plumb-trigger-eval`). A trial that failed is rerun unchanged.
6. **Draft the change** in the owning layer, and log the decision with `plumb-decision-log`.

## Report

```
Failure: <record> (<code>, <kind>) — what happened, one line
Not noticed because: no step / no check / no knowledge — one line
Same pattern elsewhere: <n> (list)
Layer: <layer> — what changes
Measured by: <number>, before <value>, looked at again <when>
Drafted: <pull request, branch, or "proposal only" with why>
Owner's call: <always present for a CI rule>
```

## A worked example

`evals/improvement-loop/open-pr.md` takes one real failure through every step: a session trial
where "open a PR" never reached the rule that writes the `Fixes-PR:` line, fixed in the harness
layer and measured by trigger recall (0.20 → 1.00) and the rerun trial.
