# Running a plan

**The plan is executed by someone who has not read this conversation. The one running it stands
that someone up fresh every time.**

Land the plan that came out of `playbooks/writing-a-plan.md`, one task at a time.
**This is not where you re-decide the shape** — when a flaw surfaces, rule on it, record it,
and move (see "Where you stop" below).

If it runs overnight, layer `playbooks/autonomous-run.md` on top. **The termination predicate,
the wake-up mechanism and the per-iteration record belong to that playbook** and are not
copied here (**principle-encode-lessons-in-structure**).

## 0. Hand it out, or slice it in the main session

**The handoff table in step 7 of `playbooks/writing-a-plan.md` is the source of truth** and is
not copied here. If the choice has not been made, read it there, decide, and come back. The
default is **hand it out** — one role per task keeps **the bulky material off the main
session** (**principle-guard-the-context-window**). Slice it in the main session when there
are three tasks or fewer, or when they are tightly entangled.

**Do not hand tasks out at the same time.** Tasks in a plan write to the same surfaces of the
same tree, so the test in step 1 of `playbooks/fan-out.md` says no on its own
(**principle-separate-before-serializing-shared-state**).
If it says yes, they are independent enough that this is not plan execution but a fan-out. Go
there. What follows is the handing-out path, but **the main session slicing it still walks the
gates in 2 through 6** — not handing out is no reason to skip a gate.

## 1. Before you hand out task 1

**Create the ledger first.**

    log="$(plumb-path run --mkdir)/$(basename <plan path> .md).tsv"
    plumb-decision-log "$log" --header task state from to findings ruling
    plumb-decision-log "$log" 0 start "$(git rev-parse --short HEAD)" - - "<plan path>"

**Do not invent machinery.** `plumb-decision-log` is the ledger and `plumb-path run` is where
it goes (**principle-subtract-before-you-add**). **Take the file name from the plan** — read
another plan's ledger as your own progress and **you hand out a finished task again**.
**Compaction erases memory; the ledger and `git log` survive it.** On resume, trust those, not
what you remember.

**Read the plan once.** Note the global constraints and open a todo per task. If it names a
spec path, read the spec too — **the spec wins a ruling.**

**Then hunt the contradictions inside the plan before you start.** Line up the task pairs that
touch the same file or the same surface, cross-check what one produces against what the other
consumes, and **write one line per pair.** "I read it and it was clean" is not a written line
(**principle-gate-claims-on-evidence**). Rule on the contradictions you find here and record
them in the ledger. **Fix one after execution starts and everything up to that point shifts.**

## 2. Hand out one task

**Record the starting commit before you hand it out. It goes in the ledger, not in a shell
variable** — a variable does not survive compaction; the ledger does.

    plumb-decision-log "$log" 3 dispatch "$(git rev-parse --short HEAD)" - - -

**Do not use `HEAD~1` as the start afterwards.** The moment a task runs to two commits or
more, the first one never reaches the gate. **And it falls through without turning anything
red.**

You hand over three things, **all of them as files**
(**principle-guard-the-context-window**).

- **The brief.** One page carrying only that task's body. **Do not let them read the whole
  plan file** — an implementer who reads the neighboring task starts the neighboring job
- **Where to write the report.** Detail goes there; **the return value is state and artifacts
  only**
- **The surface the preceding tasks actually left.** Function names, types, paths that exist.
  This is the only thing that cannot go in the brief

**Do not paste the history of the previous task.** Whatever you paste is re-read on every turn
that follows. The rest of the handoff — scope, what to decide on, what not to touch, the shape
of the return — is owned by step 2 of `playbooks/fan-out.md`.

**When small tasks of the same shape line up, hand them out in one message.** The same one-line
fix scattered across five files is not five jobs.

**Do not let the implementer stand up its own reviewer.** A seat they create reads the same
diff twice and **does not count as judgment.** The gate is your seat.

## 3. Handle what comes back

When it comes back with a caveat attached, **read the caveat before you move on** — if it
touches correctness or scope, clear it before the gate. If it says it lacked context, supply
it and hand it out again.

**When it says it is stuck, do not fire the same thing again.** Add context, split the task,
rule on the plan, or swap the role. **Resending it unchanged is the same as ignoring it.**

## 4. Run the gate

**Do not let self-report stand in for the gate**
(**principle-gate-claims-on-evidence**). An implementer's self-check is its own eye, not
judgment.

**Hand the diff over as a file.** Do not load the diff into the main session's context.

    from=<the starting commit you wrote in the ledger>
    pkg="$(plumb-path run)/task-3.diff"
    git log --format='%h %s' "$from"..HEAD  >  "$pkg"
    git diff --stat          "$from"..HEAD >> "$pkg"
    git diff -U10            "$from"..HEAD >> "$pkg"

You hand over three paths — the brief, the implementer's report, the diff file — plus **the
plan's global constraints, copied over verbatim, in a few lines.** The constraints are what
aims the reviewer's eye.

- **Do not write "don't flag this area".** That is ruling in advance. Let it be raised, then
  rule
- **Do not have the checks the implementer already ran run again.** The evidence is in the
  report
- **Items that come back as "cannot be confirmed from the diff" are yours to clear.**
  A requirement that spans tasks is out of the reviewer's reach. If it is a real hole, treat
  it as a gate failure

## 5. Cap the rework rounds

**The implementer does the fixing. The main session does not fix it itself** — a diff the main
session wrote never passes through the gate once.

- **Rounds one and two go back to the same role.** Hand over the findings verbatim. It is
  faster while the context is still alive
- **Round three stands up a different role.** Give it the report file and say "the previous one
  tried twice and did not get there". **Three rounds without convergence means that role
  cannot see its own hole**
- **That is the cap.**

When you hit the cap, **rule on each remaining finding yourself and write it in the ledger.**

| Remaining finding | What to do |
|---|---|
| The finding is wrong, or it is contested | **Defer it.** Write why. The final whole-branch review sees both sides |
| Real, but nothing downstream rides on it | Defer it. **Write down that it is real**, then defer |
| Real, and something downstream rides on it | **Decide the smallest fix that lets the next task move, and carry it into that task** |

**Rule only after you have hit the cap.** Ruling early to close the rounds out is burying a
finding under a different name. **A finding that is not in the ledger never existed.**

Keep minor findings out of the rounds: **add a ledger line and aim them at the final
whole-branch review.** A "look at it later" with no destination written down is the same as
throwing it away.

## 6. Close a task

You may close only when **the gate passed, or you hit the cap and every finding carries a
ruling.**

    plumb-decision-log "$log" 3 done "$from" "$(git rev-parse --short HEAD)" "major 0 / minor 2" -

**One line per task at dispatch, one per round, one at completion.** A task with no completion
line is treated as untouched on resume — **a task that left no trace gets handed out again.**

## 7. When everything is done

**Put the whole branch through review, once.** A per-task gate is scoped to its task, and
**failures that only appear once the pieces connect never went through one**
(**principle-sequence-verifiable-units**). Aim the ledger's deferred lines and minor lines at
that review.

When findings come back, **fix them in one pass, once.** Stand up a role per finding and each
one rebuilds the context and re-runs the checks. After fixing, re-check once with the scope
narrowed. **One wave, no more.** Rule on what is left the same way as in 5, put it in the
ledger, and **carry it into your reply to the owner.**

From here, `playbooks/closing-a-branch.md`. If you open a PR along the way,
`playbooks/opening-a-pr.md`, and `playbooks/being-reviewed.md` for answering what comes back.

## Where you stop

**While it is running, you do not wait on a human**
(**principle-never-block-on-the-human**). A conflict, an ambiguity, a flaw in the plan:
**decide, write it in the ledger, move.** A ruling you got wrong comes back with one diff.
**A night spent stopped on a question gives nothing back.**
Do not stop for a progress report or for "may I keep going".

You stop for exactly four things. **An irreversible operation** (deleting, wiping, touching
production). **A side effect that leaves this workspace** (a push to a shared branch, a merge,
a publish). **A change that touches keys or permissions.** **A flaw in the plan that reaches
all the way to the shape, where every road is a guess.**

The fourth is the same line as "the price of undoing it" in
`playbooks/shaping-the-work.md`. **On the method side, decide and move. On the shape side, stop.**

**What you return:** the ledger path, how many tasks and each one's starting and landing
commit, which tasks went into rework and how many rounds, **every ruling you made** (what, why,
and what is lost if it was wrong), the findings you deferred, the result of the whole-branch
review, the playbook you enter next.
**A run that does not list its rulings is a run that decided in silence.**
