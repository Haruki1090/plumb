# Fix a bug

**Get a repro first. Thinking of a fix comes after that.**

"It crashes." "It crashes sometimes." "It only misbehaves in this environment." "I fixed it and it
came back."

**The judgment of tracing a symptom back to its root cause belongs to principle-fix-root-causes**, so
it is not copied here (**principle-encode-lessons-in-structure**).
What this playbook holds is **the steps, and the places those steps actually break**.

Moving the structure without changing the behavior is `playbooks/refactoring.md`; slow but not
crashing is `playbooks/perf-issue.md`. **Neither of them comes here.**

## 1. Do not start from design

The fix that came to mind the moment you read the report: **write it down, and stop your hands.**
It is a hypothesis, and it holds not one piece of evidence yet.

**Take the shot and you are left with no way to judge whether it hit.**
The symptom goes away and you never learn whether that change is what removed it.

## 2. Pin the repro in a form a machine judges

**"I checked it by hand" is not a repro** (**principle-gate-claims-on-evidence**).
A failing test, a short failing script, an exit code that comes out every time from a fixed procedure.
**Build the thing that returns the same result for the same input before you fix anything.**

- **Read the failure output to the end.** Do not skip the line number, the path, the exit code.
  What you are hunting for is often written right there
- **If it does not reproduce, you do not have enough material yet.** Raise the count, put load on it,
  match the environment. **Fixing without a repro is deciding never to check whether it got fixed**
- **If it survives a restart or a deploy, suspect leftover state before you suspect the code.**
  Running again does not change the code, but caches, config, locks and saved partial progress do change
- **Look at when it started.** If a change landed recently, the suspect range shrinks to there

Do not throw the pinned repro away. **After the fix, keep it as a test**
(`playbooks/writing-tests.md`).

## 3. Trace back from where it fell to where it broke

**The line that fell first is usually not the culprit.** That is where the bad value *arrived*, not
where it was born.

Go up one level at a time. Repeat **who handed this value over** until you cannot go back further.
When you run out of trail, **put instruments in rather than guessing**: print the value and the call
path **immediately before** that operation. Print after the fall and the cause is already upstream.

**In a layered system, line up what goes in and what comes out at each boundary.**
Once you can see which boundary changed the shape, the range you read shrinks to one layer.
**Do not start reading from "probably this layer".**

**Line it up against an identically shaped path that is not broken.** If a similar flow works in the
same repository, the diff between the two is your list of suspects.

## 4. Fix one place, one thing at a time

- **Do not let "this looks like it might help too" ride along.**
  Step 3 of `playbooks/autonomous-run.md` holds the same discipline: **revert every change that did
  not move things forward.** Mixed together, the one that worked cannot be identified
- **A guard that silences the crash is not a fix.** If it dies on nil, fix the path that let nil through
- **If the same shape exists elsewhere, count those too.** Fix one and you will run the same
  investigation a second time

**Miss three times running and doubt the premise, not the fix.**
If every miss moves a new symptom somewhere else, that is not a failed hypothesis but a structural
problem. **Do not try a fourth one yourself.** Stop, and hand it to the judge role
(`docs/role-map.md`).

## 5. Show it is fixed with the same repro

**What failed before the fix passes after it.** Only the two together make a claim
(**principle-prove-it-works**). One alone shows nothing.

**Retake it whole.** Getting one to pass by dropping another is not a fix.

## 6. Do not plug the same hole twice

The moment it is fixed, think about the next one (**principle-encode-lessons-in-structure**).

- **Keep the repro as a test.** This is the floor. Leave it out and the same bug comes back
- **Tighten the boundary the bad value came in through.** If it can be rejected at the entrance, reject
  it at the entrance (**principle-boundary-discipline**: guards concentrate at the boundary.
  Scattering checks along the whole path is the inverse of that principle, and afterwards nobody can
  remove them)
- **Do not settle for "people will be careful".** If you have written the same warning twice, that is
  a missing check

## Do not wait on time

**A test you got to pass by adding `sleep` fails on a slow machine.**
What you wait on is not time but **a condition**: is it in that state, did that artifact appear, did it
reach that count. Always attach a ceiling, and when it is exceeded **fail with what you were waiting
for written out.**

**Wait on time only when time itself is the specification.**
Then **write into the code why that value.** If you cannot write it, it is a guess.

## When something next door is polluting you

It passes alone and fails when everything runs together. **That test is innocent.**
The cause is **state left behind by whoever ran earlier**, and where you look is not the side that fell.

    plumb-isolate-pollution '<command that detects the residue>' '<command that runs one>' <target>...

Run them one at a time and **stop at the first one where the residue appears.**
Once you find it, fix the cleanup on the side that left it. **Do not silence the side that fell by
adding a wait to it.**

## Isolation, and fanning out

To split off a workspace, `playbooks/worktree-setup.md`.
**Do not fan out failures whose causes are connected** — `playbooks/fan-out.md` already holds that.
Failures where fixing one makes the rest disappear finish sooner seen by one worker together.

The fixed diff goes to `playbooks/closing-a-branch.md`.

## How this breaks

| Failure | What to do |
|---|---|
| It was urgent so you skipped the steps | What you skipped comes back as round trips of guesswork. **The more urgent it is, the earlier you take the repro** |
| It is a simple bug so it needs no cause | A simple bug has an origin too. **Simple only means the distance back is short** |
| You added a guard on the failing line and it passed | What passed is the symptom. **The value's origin has not moved one line** |
| You put three likely fixes in at once | You cannot tell which one worked. **Revert, and go one at a time** |
| You spent hours tuning wait times | That time does not come back. **Delete every wait and start again from 2** |
| It does not reproduce, so fix it and watch | Watching is not verification. **With no repro you are not at the fixing stage yet** |
| It is fixed, so you reported the earlier failure output as it was | Retake the output (**principle-gate-claims-on-evidence**) |

**What you return:** the pinned repro (the command, and the output before the fix), the root cause you
traced back to, what you changed, the output of the same command after the fix, the structure you left
behind (the test, the boundary check), the hypotheses you dropped and on what grounds.
