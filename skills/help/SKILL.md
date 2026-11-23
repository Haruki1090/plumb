---
name: help
description: Answer a question about plumb itself - which playbook or skill fits a job, what to send to start it, what plumb does, or why it did not do something. Use when asked "how do I use plumb for X", "which playbook for X", "what does plumb do", "plumb isn't doing X", "why didn't the skill fire", or in Japanese "plumb de X wo suru ni wa", "dono playbook wo tsukau", "plumb ga X wo shite kurenai". Answers and hands back a prompt or command; never starts the work. Not for doing the job itself.
---

# Answer a question about plumb

**Answer, hand back the exact prompt to send or the command to run, and stop.** Starting the work
is a new request. If the person then wants it done, they say so, and that request routes on its own.

## Steps

1. **When the answer depends on what is configured here, run `plumb-doctor` and read it** (it takes
   a minute or two; skip it for a question about what a playbook says). What changes answers: no judge
   role (`role.judge`), no project contract, no pane driver (`pane.driver`), ledger export off. Say
   which part of your answer changed because of what it showed. A `--` line is "unset or cannot be
   checked", not a fault; an `NG` line is broken, and goes first in the answer.
2. **Map the question to one entry of the router index in the root `SKILL.md`.** Read the index; do
   not keep a second copy of it here, it would go stale (**principle-encode-lessons-in-structure**).
   Name the entry, and read the playbook or skill it points to before you describe it. If no entry
   fits, say plumb has no playbook for the job and what the index offers closest.
3. **Hand back the prompt**, written in the language the person used, ready to paste. One prompt per
   job. When the entry is a command, give the command with its arguments filled from what you know
   and say what each unknown is.

## What a good request carries

Five things:

- **The goal**, in one sentence of outcome, not method.
- **A done-condition** that can be checked true or false ("the login test passes with an empty email",
  not "works better").
- **The evidence wanted back**: a command's output, a SHA, a pull request number.
- **What is already known**: what was tried, what was ruled out, where the code lives.
- **Constraints**: what must not change, what may not be touched, a deadline that matters.

Two things to leave out:

- **The steps to take.** The playbook sets them; a request that dictates them overrides a playbook
  that would have done better.
- **A guess at the cause stated as fact.** An agent starts from it and confirms it. Write "I suspect
  X, unverified" or leave it out.

## When something went wrong

Find the symptom, run the command, read what it says. Say which command you ran and show its output.

| Symptom | Where to look |
|---|---|
| A skill did not fire | Read the skill's `description` and its cases in `evals/<skill>/triggers.csv`; hand back the `plumb-trigger-eval --cases ... --skill ... --out <dir>` command for the person to run (it starts sessions and writes to `<dir>`, so it is not run from here), and `plumb:failure-to-rule` for the change |
| Context filled early | `plumb-session-audit` for the sessions, `plumb-prompt-weight` for the fixed prompt you control |
| Cost is unknown | `plumb-ledger` (`docs/ledger.md`); the weekly view is `plumb:retro` |
| A lane went quiet | `plumb-run-view` for the lanes, `plumb-stalled` for what waits and on whom |
| It said done and it is not | `principles/gate-claims-on-evidence.md`: ask for the output of the run, not the claim |
| Verification says the repository has none | The project contract: `plumb-project --json`, schema in `docs/project-contract.md` |
| plumb itself looks broken or a pointer leads nowhere | `plumb-doctor`, then `plumb:doctor` for how to read a failure |
| A role runs on the wrong model or in the wrong place | `plumb-config <key>` for the value, `docs/role-map.md` for what each key does |

A symptom this table does not hold is a finding, not a gap to guess across: say what you checked and
what you could not.

## Do not

- Do not start the playbook, edit a file, or run anything beyond the commands above.
- Do not paraphrase a playbook from memory; open it and quote the line that answers.
- Do not answer "plumb does X" without checking X in this checkout. Another version may differ.
