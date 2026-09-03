---
name: pr-review
description: Review a large or irreversible PR as the person who holds the approval. Fires on a bare GitHub PR URL (https://github.com/<owner>/<repo>/pull/<n>). Use when asked to "review this PR", "is this safe to approve", "a review request came in", or "take a look at this PR" - cross-checks the body's claims against the facts of the diff, runs refuters and reproduction tests in parallel, and returns confidence and blocking separately.
---

# PR review v1.1

## The problem this playbook is for

A large PR cannot be read top to bottom. Even when it can, you cannot weight what matters. And
**the PR body is only a projection of what the author believes, and it goes stale before the diff does.**

So this playbook is not built around an order for reading the diff. It is built around
**leaving a record of what you decided not to look at.**

## Principles

1. **A finding you cannot refute is not a finding.** If you cannot name a concrete input or state → a
   wrong output or a loss, it does not become a finding. "Hard to read" and "this would be nicer" are outside this playbook.
2. **The body is a hypothesis. The diff is fact.** Never source a claim from the body.
3. **Split the role that finds from the role that confirms.** Tell the verifying role to *refute*, not to support.
4. **Precision over recall, by default.** A review carrying 40 nits stops being read. Raise the depth deliberately.
5. **Never wave through what you did not look at.** It is the gatekeeper's one real offence.
6. **The reviewer does not edit the code under review.** Fixing it is the author's job.

## What you do not call while this playbook is running

Review is neither creative work nor implementation, so **do not call the following even when their trigger
conditions appear to match**. Calling them turns the review into a different task.

| Do not call | Why |
|---|---|
| `plumb:graph` | Every trigger condition matches (several files, parallelism, alignment with a design doc, subagents), but it is a **pre-work design** skill. It converts the review into a design task |
| `/simplify` | "Clean this up" lands on it. It is quality-only and it applies fixes. Against principle 6 |
| plumb's `playbooks/shaping-the-work.md` | A design conversation starts. Review is not creative work |
| plumb's `playbooks/being-reviewed.md` | The **author's** playbook. Wearing both hats on one PR leaves a record of you judging your own diff. It is what the author reads after you return, not what you read |
| `/code-review --fix` / `--comment` | `--fix` is against principle 6. `--comment` sends findings that never passed stage 5's verdict straight to the author, cut loose from the approval decision (returning is concentrated in the one place that is stage 6) |

These, on the other hand, you **do pull in**.

- **principle-gate-claims-on-evidence** — it feeds directly into the CONFIRMED verdict in stage 5
- plumb's `playbooks/worktree-setup.md` — isolation for stage 3's reproduction tests
- plumb's `playbooks/fan-out.md` — stage 3's parallel execution

## Steps

### 0. Pin the revision

Start here when all you were handed is a PR URL.

1. Split the URL into `owner/repo` and the PR number
2. Clone the repo if it is not local; otherwise `git fetch origin pull/<n>/head:pr<n>`
3. Detect drift and branch protection

```bash
plumb-pr-drift <owner/repo> <PR number>
```

- Record the SHA under review. **Everything below is done against that SHA.**
- Read the protection warnings it prints. If `dismiss_stale_reviews_on_push` is false, a push after your
  approval turns the approval into a blank cheque. Decide whether to approve with that fact included.
- On a long-lived PR you are reviewing for the second time or later, re-run everything below against the
  diff from the SHA you read last time.

**Run stage 0 again immediately before you build what you return.** (a failure taken in real use)

The PR moves while you review it. Measured: 13 commits landed during a two-hour review, and:

- **5 of 9 findings had their anchor line shift** (GitHub draws the draft against the current diff, so an
  inline comment tied to an old SHA points at a different line)
- 3 findings were spent because **the document they targeted was deleted outright**
- 1 **changed shape when a fix landed**
- and those 13 commits had brought in **2 new BLOCK candidates**

Pinned at the start is not enough. **Take it again just before you submit, and if it moved, review the
difference before you return.**

**If the PR keeps moving, tell the author that fact itself.** Chasing a moving target keeps the review
permanently out of date. Treat it as a structural problem with the PR, the same as size or body drift.
- **Dump the diff to a file** (stage 1 uses it):
  `git diff <base>...<head> > <scratch>/pr<n>.diff`

### 1. Bidirectional inventory

Build **two independent** sets of claims.

**(a) From the body** — pull out of the PR body and the commit messages only the claims whose truth can be
decided. Do not verify them here.

**(b) From the diff** — hand the `pr-diff-reader` agent **only the diff file you dumped in stage 0**.
That agent holds nothing but `Read` / `Grep` / `Glob`, so **it cannot fetch the body**.
Tool permissions enforce this, not a polite instruction.

Then **take the set difference.**

| Gap | What it means | Severity |
|---|---|---|
| In the body, not in the diff | Unimplemented, or claimed and then taken back. It misleads the approver | Medium |
| **In the diff, not in the body** | **An undeclared change** | **Always high** |

`plumb-pr-drift`'s "commits after the body was last edited" is a mechanical lower bound on the second one.
Zero does not clear you (the body can have been incomplete from the start), but non-zero means something
is there for certain.

### 2. Weighting, and the cut

Sort every claim by ⟨irreversibility⟩ × ⟨money or data lost⟩ and draw the line at your time budget.

**Write out, right there, the list of what fell below the line.** Stage 6 returns it.
The quality of a review is decided less by what you looked at than by what you decided not to look at.

Irreversibility, high to low: production DB migration / a charge or invoice becoming final / state changed
in an external service / a deploy you cannot roll back / a deleted backward-compatibility path.

**The paths you settle on here are the arguments you pass to `/code-review` in 3-A.**

### 3. Refutation (parallel)

Run A through D **in parallel, in separate contexts**. Wherever two axes overlap goes first.
E is conditional: add it only when it lands.

| Axis | How it runs | Territory |
|---|---|---|
| **A. Line-level correctness** | `/code-review <effort> <the paths from stage 2>` | whether the code is correct |
| **B. Invariants** | `pr-invariant` agent | properties spanning several places |
| **C. The cutover path** | `pr-cutover` agent | procedure, operations, irreversibility |
| **D. Reproduction** | `pr-repro` agent (**worktree isolation required**) | promoting or killing a PLAUSIBLE |
| **E. Another family** (conditional) | `plumb:interrogate` | blind spots one family shares |

**On E.** A through D split the **roles**, but **every one of them runs inside the same model family**.
Diversity of role is not diversity of blind spot. So add one pass only when one of these holds.

- an irreversible change (a deletion, a migration, authn or authz, a production deploy)
- **a diff that writes the rules, the conventions or the procedure itself** (discipline you wrote yourself
  is discipline you cannot inspect yourself)
- a change carrying a design fork, where the approach itself has to be doubted
- stage 1's inventory turned up something **in the diff but not in the body**

**If none of them lands, do not add it. But leave the decision not to add it as `skip: <reason>`.**
Never drop it silently. `plumb:interrogate` holds the steps.
What comes back carries **confidence only, exactly as with A through D. You attach blocking in stage 5.**

**On A.** `/code-review` is a sensor, not a judge. It gives confidence (CONFIRMED / PLAUSIBLE) but
**it does not give blocking**: the human side attaches that in stage 5.
Point it only at paths that survived stage 2's line. Point it at everything and it returns findings from
the territory you decided not to look at, which leaves you **throwing away real findings you generated
yourself**. effort is medium by default, and high is the ceiling once you have narrowed the target.
Do not try to buy back the narrowing with effort.

What `/code-review` cannot find by construction: every finding is pinned to a file, so it misses
**a defect that appears in no single file's diff** (B), and **anything that is not a question of code
correctness at all** (C). A is not a substitute for B or C.

**Check four things before you recommend ultra.** (a procedure that actually failed three times)

1. **It bills separately.** The cost call is the user's. Do not assume it
2. **The ceiling is 500 files / 8,000 lines** (insertions+deletions). Measure it beforehand with
   `git diff --shortstat`. The number in the refusal message is the diff size, not the ceiling
3. **State the base.** With no argument it compares against the default branch, which is off by an order
   of magnitude in a repo running develop
4. **You cannot launch it yourself.** Put it in the playbook as a human step

To fit under the ceiling, **drop tests first**. Cutting product code drains the sensor of its meaning.
Whatever you dropped goes into stage 6's "what I did not look at", without exception.

**Record the "too large" refusal itself as a finding.** A diff too big for automated review is material
for the case that it should have been split.

**On D.** Of the PLAUSIBLE findings out of B and A, hand the reproducible kind to `pr-repro`.
They can be promoted to `CONFIRMED = a failing test was written and it actually failed`.

Keep the asymmetry of reach in view at all times.

- **Reproducible** — pure computation, boundary values, idempotency, reordering, state transitions
  (as far as a fake or a harness exists)
- **Not reproducible** — the irreversibility of a migration, how an external service really behaves in
  production, manual procedure, infrastructure configuration

So **axis C tops out at PLAUSIBLE by construction**. Do not let that invert into
"only what a test confirmed matters".
**On an irreversible change, axis C is usually the frightening one.**
What confidence cannot cover, cover by raising blocking.

**Put `pr-refuter` on every finding. On a BLOCK candidate, without exception.**
When in doubt, fall to the refuting side.
Each refuter has a 30-tool-call budget; `PLAUSIBLE - budget spent` counts as no refutation, so the finding keeps its confidence and the verdict's confidence section states that the refuter spent its budget.

**Name the most promising line of refutation for the refuter.** Say only "refute this" and it tries the
general case and comes back with "could not refute". Naming **the weakest point of your own finding,
yourself** is the condition for the refuter to work at all.

**Measured hit rate (one real run): 11 launched, 8 REFUTED.**
Six of seven BLOCK candidates were demoted, and one BLOCK was left at the end. Without the refutation
pass, a wrong Request changes would have gone back carrying six findings' worth of supporting material.
You run it not "to be careful" but **because most of it collapses.**

**A finding that survives refutation usually still gets its wording fixed.** All three survivors had the
timeline, the blast radius or the permanence wrong. One was corrected in the **heavier** direction
("cancellation blocked after 8 failures" → "cancellation blocked from the first failure").
Shipped as written, it would have been thrown out as factually wrong.
**Refutation is not only a process for killing things.**

**The refuter's output carries a section for "other things found along the way".** It is in
`agents/pr-refuter.md`'s output spec, so you do not have to ask for it. In real use a refuter turned
up, as a by-product, a finding none of the four axes produced (an alert log line with no monitoring
attached to it). Keep it purely on killing and that by-product gets discarded.

```
bad:  "Please refute this finding"
good: "The checklist may well name §6.2 as the source of truth. If that holds, this drops out of BLOCK"
good: "If the `git clean` instruction does not exist, say so outright"
good: "The only shape a refutation can take here is 'there is a path that recovers before it reaches blocked'"
```

### 3-x. Collecting the subagents (the caller's job)

**An agent's plain-text output does not reach the caller.** Writing "return it with SendMessage" in the
agent definition does not help: the harness tells the agent its final text is the return value, and that
wins.

**When you get an idle notification, ask for delivery with SendMessage.** Run this as a step.
When you ask, restate the headings of the output section and the individual questions you originally
asked — they get dropped otherwise.

### 4. Inspecting the blank space

Stand up one `pr-blindspot` agent. Ask it one thing only: what impact area does this PR body never once
touch?

### 5. The verdict

Classify the surviving findings on **two axes**. Do not collapse them into a single severity.

| Confidence | Definition |
|---|---|
| **CONFIRMED** | A failing test was written and it failed, or the code was followed all the way to a path that definitely breaks |
| **PLAUSIBLE** | The case for breakage stands, but something is left unconfirmed |

| Blocking | Definition |
|---|---|
| **BLOCK** | Stops the approval |
| **FIX** | Does not stop it, but gets fixed before merge |
| **NOTE** | Recorded only. Not fixed this time |

Before you write CONFIRMED, pass the gate of **principle-gate-claims-on-evidence**
— did you run the command that proves it, this turn? If not, it is PLAUSIBLE.

**But running the command is not enough.** Three of four BLOCK candidates actually fell to
"the command ran, the conclusion was wrong". On top of running it, check two things.

**(a) Did you read the output right?** One line out of grep reverses the conclusion depending on whether
it is the reading side's test or an UPDATE's WHERE clause. **Open what surrounds that line** and confirm
the context. Never raise confidence off a single grep line.

**(b) Did you drop a qualifier?** Read the agent's report and your own wording **side by side**.
This was the most common way it broke.

| How the agent put it | How you must not harden it |
|---|---|
| "if an operator who was told that types X" | "typing X as instructed" (that instruction did not exist) |
| "a re-run fails the same way" | "it **always** fails" (the first run passed) |
| "I do not see any" | "it does not exist" |

**Before you write "does not exist", grep the whole repository and confirm zero hits.**
"Confirming something is absent from the documents" turns into a false CONFIRMED whenever the search
was sloppy.

**(c) Did you confirm that the entry point of the chain exists?** The most painful error in real use.
Verify every link correctly, one at a time, and **the chain still may not hold**.

```
Real case: "a new tenant is stuck at one seat"
  seatLimit ?? 1                        ← verified, correct
  backfill pinned to headcount          ← verified, correct
  no subscription means no seat added   ← verified, correct
  the app cannot write seat_limit       ← verified, correct
  not in the GRANT column list          ← verified, correct
  → conclusion "a new tenant is stuck"  ← wrong
     no self-signup path existed (there was no entry point)
     and an admin could create the contract themselves (there was an exit)
```

When you assert a scenario, confirm **that the entry condition exists** and **that there is no exit along
the way**, before you verify the links.

### 6. Returning it

Return it in the shape of `references/report-template.md`. Four elements are required.
The structure is never translated: keep `Blockers (BLOCK)`, `Fix before merge (FIX)`, `Recorded only
(NOTE)`, `Residual risk accepted`, `What I did not look at`, the table columns `#`, `Confidence`,
`Where`, `How it breaks`, and confidence words `CONFIRMED` and `PLAUSIBLE` in English whatever
language the prose uses, because tools read the structure.

1. **The SHA under review** (write out "this approval is against `<sha>`")
2. **The approval decision**
3. **The residual risk you accept** (name it and write the first response. "Probably fine" is not a
   residual risk)
4. **What you did not look at** (the list you cut in stage 2)

**Write the unverified part inside each individual finding too.** Separately from stage 6's overall
"what I did not look at", state per finding what, if overturned, collapses it.
Leave the author room to push back, inside the finding itself.

```
good: "I have not confirmed against the live API that Stripe does not sweep pending items at cancel_at.
       If that is overturned the finding collapses, though then the contractEnded path has no reason to exist"
good: "I cannot say the JST side is wrong, nor that the UTC side is. The one certain thing is that
       not a single test checks which of them matches Stripe"
```

**Write a demoted finding together with how it got demoted.** Do not quietly drop something you once
treated as BLOCK down to FIX. Write "I first judged this to be X, and that was wrong."
Otherwise the weight of the finding does not carry, and you cannot vouch for the reliability of the
findings that remain.

**Write the confidence interval of the review itself.** Attach how many findings the refutation pass
demoted. Saying outright that "what remains can have the same property" comes from the same motive as
writing down what you did not look at. Do not state as certain what you cannot be certain of.

Delete the tests you wrote in stage 3 D **when you return** (their paths and contents go into the report).
Whether to adopt them is the author's call.

If you visualize it, read the `artifact-design` skill first and build it in HTML. The board to put up is
not a summary of the diff: it is **claim × verdict × residual risk**, and **the cutover timeline with its
break points**.

After you return it, you may tell the author that plumb's `playbooks/being-reviewed.md` applies to them
(verify before implementing; pushing back on technical grounds is allowed).

## What not to do

- Findings about style, naming or readability (linter and formatter territory)
- "While we are here" suggestions (YAGNI. Anything that does not serve this PR's purpose does not even
  become a NOTE)
- Performing coverage. Do not write in a way that makes territory you never read look read
