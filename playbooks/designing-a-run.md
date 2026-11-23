# Designing a run

**You hold the shape of a run for work that fits no other playbook: its predicate, its verifier,
its loop and its log.** You design it before you start it, and you do not start it until the
verifier has been seen to fail.

This is a last resort, not a shortcut. Every other playbook already encodes a shape somebody paid to
learn. **Enter here only after you have read the router's index in `SKILL.md` and found no row that
fits.** Say which entries you considered and why each one missed ("bug fix: nothing is broken",
"hillclimb: there is no single number"). If one of them fits even in part, go there and bring this
playbook's framing to it.

## 1. Frame it before you touch anything

Four things, written down in this order. **Do not start work with any of them missing.**

1. **A done-predicate that could be false, and that a command can decide.** "The migration is
   finished" is a feeling. "`<command>` prints 0 rows with a stale schema and exits 0" is a
   predicate. If no command can decide it, you do not yet know what done means; find that out first
   (**principle-gate-claims-on-evidence**).
2. **The size, in numbers.** How many files, items, cases, repositories. "A large refactor" is an
   adjective; "212 call sites in 31 files" is a size, and it is what decides whether the work fans
   out, fits in one session, or needs to cross a night.
3. **The rigor level, in one line.** Choose it by what a wrong result costs and whether it can be
   undone. A throwaway analysis that can be rerun gets a spot check. A change that touches data or
   that other people build on gets an independent verifier and a rollback. Write the line down; it
   is what you are held to later.
4. **The unknowns, ordered from most to least uncertain.** **Work goes to the most uncertain one
   first**, because that is where the run is most likely to turn out to be a different run. Leaving
   the hard part for last is how a plan survives until the last day and then fails.

## 2. Build the verifier and take the baseline before the work

**The verifier is the tool that decides the predicate** (**principle-build-the-lever**). Build it
first, run it once on the untouched state, and keep that output as the baseline.

- **Show it can fail.** Break the target on purpose, or point it at a known-bad input, and watch it
  report the break. A verifier that has only ever printed green has not shown it checks anything
  (**principle-prove-it-works**).
- **Zero results is not green.** If it counted nothing, it probably looked at nothing.
- **Freeze it.** Change it mid-run and every earlier reading is void; if you must, say so and retake
  the baseline.
- If the predicate rests on a measured figure, the number is read under **principle-explain-the-number**.

## 3. Design the workflow from parts that already exist

Do not invent machinery a playbook already holds. Decide each of these and write the answer down.

- **Which steps fan out.** Only independent ones, with disjoint write targets (`playbooks/fan-out.md`).
  A step whose result feeds the next does not fan out.
- **Which steps need a dependency graph.** When ordering, shared resources or several writers make
  the order non-obvious, load `plumb:graph`. A short linear run needs none.
- **Which roles take which step** (`docs/role-map.md`). The implementer role writes; you review the
  diff.
- **Where the judge role looks.** Name the one place a different family would most plausibly find
  what you missed: the premise, the verifier, or the stop decision. An unset judge role is a visible
  skip, not an omission.

## 4. Run it as a loop: one unit, verify, record

1. Take one unit. The smallest piece the verifier can judge on its own
   (**principle-sequence-verifiable-units**).
2. Do it, then run the verifier on that unit.
3. **Close the unit as exactly one of three words.**
   - **VERIFIED**: the verifier ran and the result matched what the unit promised.
   - **NOT VERIFIED**: it ran and it did not match. Revert, or fix and run again.
   - **INCONCLUSIVE**: it could not decide. The verifier broke, the environment differed, the unit
     was too large to judge.
4. **INCONCLUSIVE is never rounded up.** It is reported as INCONCLUSIVE, with the question that went
   unanswered, at the end. A run with a pile of them is not nearly done.
5. **Two failures resting on the same assumption stop the loop.** Write the assumption as one
   sentence and test it before the next attempt (**principle-attack-the-premise**).

## 5. Keep the decision log

Open it before the first unit and keep it outside the tree, so a revert cannot take it with it.

```bash
plumb-decision-log <log> --header unit did result verdict notes
plumb-decision-log <log> --start "<label>"
plumb-decision-log <log> 1 "<what you did>" "<verifier output>" VERIFIED ""
```

Close with `plumb-decision-log <log> --audit` and carry every `missing` line into your report. A
commit, PR or file the log names that is not there is not evidence.

## 6. If it will run unattended

The discipline is `playbooks/autonomous-run.md`. Stack it on this one: the predicate from step 1
becomes its termination predicate, and the log from step 5 is its checkpoint. A predicate no machine
can judge does not run overnight.

## What not to do

- Do not start work and frame it afterwards. A predicate written after the result bends to fit it.
- Do not loosen the predicate to finish. Stopping short has the same four conditions as
  `playbooks/hillclimb.md`.
- Do not skip the baseline because "it obviously fails now". Obvious is a claim; the baseline is the
  observation.
- Do not build a new framework for this run. If the shape needs one, it should be a playbook; say so in what you return.

**What you return:** the predicate and its final value with the command output; what is VERIFIED,
what is NOT VERIFIED and what is INCONCLUSIVE; the path to the decision log; and, if this shape of
work will recur, a one-line proposal for the playbook that should exist.
