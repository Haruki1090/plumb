---
name: plumb
description: The entry point to plumb - an index of named principles that puts discipline on non-trivial work. Use when asked to "use plumb", "follow the principles", "get a plumb line on this first", or whenever a task needs real rigor.
---

# plumb

## How to use this

When you start non-trivial work, **make your first todo "read the principle index below"**.
When the index points you at a principle, **read that principle in full before applying it**.

**When you apply a principle, name it in your reply alongside the specific decision it changed.**
A citation with no decision attached is treated as evidence you never read the leaf.

## Where roles run

`docs/role-map.md` is the source of truth for where each role runs. Do not write a model name
in the body text.

| Role | Where it runs |
|---|---|
| Main session | the Claude Code session you are in |
| Implementer role | `Task` (do not set `model`). Produces a diff; the main session reviews it |
| Explorer role | `Task` (do not set `model`). Produces no diff |
| Judge role | `role.judge` (unset: the main session stands in, and says so) |
| Bulk role | `role.bulk` (unset: the main session works through it in order) |

**Non-trivial work must open a todo line for the judge role.** Open the line before you decide
whether to run it.

That line closes exactly two ways:

- it runs
- it stays, carrying `skip: <reason>`

**You cannot get away without opening the line.** You cannot delete it either. Skipping is
allowed; skipping silently is not. A todo list with no judge line is itself the mark of a
breach of discipline.

## The playbook index

If your work has one of the shapes below, **read that playbook in full before you start**.
Playbooks name principles. A named principle means you read the leaf in full.

### Investigate (changes no code)

| Job | Playbook |
|---|---|
| How does this work, why is it this way, is it really safe, which of the two do we take | `playbooks/investigation.md` |
| A live process leaks, spins, or runs slow | `playbooks/runtime-forensics.md` |
| Read a profile / trace / spindump / heapsnapshot someone handed you | `playbooks/trace-forensics.md` |

### Change

| Job | Playbook |
|---|---|
| **Fix a bug** (it crashes, it is flaky, it came back after you fixed it) | `playbooks/fixing-a-bug.md` |
| Fix one slow thing, once | `playbooks/perf-issue.md` |
| Push one metric down, continuously | `playbooks/hillclimb.md` |
| Change the structure without changing the behavior | `playbooks/refactoring.md` |
| **Decide the shape of something you have not built yet** (what to build is still open) | `playbooks/shaping-the-work.md` |
| **Turn an approved shape into steps someone else can execute** | `playbooks/writing-a-plan.md` |
| **Land those steps, one task at a time** | `playbooks/running-a-plan.md` |
| Write tests, or repair existing ones | `playbooks/writing-tests.md` |
| Buy a design decision with an implementation you throw away | `playbooks/prototype.md` |
| Hand independent work out to parallel roles | `playbooks/fan-out.md` |
| Call a tool that needs several calls per answer, or the same call over many items | `playbooks/batching-chatty-tools.md` |

### Ship

| Job | Playbook |
|---|---|
| **Close out a branch** (decide between merge / PR / leave it) | `playbooks/closing-a-branch.md` |
| Open a PR | `playbooks/opening-a-pr.md` |
| Get it green and land it | `playbooks/landing-a-stack.md` |

### Keep going

| Job | Playbook |
|---|---|
| Keep it running overnight; run until it is done | `playbooks/autonomous-run.md` |
| Stop safely; compaction is close | `playbooks/pause-safely.md` |
| Pick up where another session left off | `playbooks/session-pickup.md` |
| Set up an isolated workspace | `playbooks/worktree-setup.md` |
| Clean up worktrees and disk | `playbooks/worktree-cleanup.md` |

### Look, and hold the line

| Job | Playbook |
|---|---|
| Review a PR (as the one who approves it) | `plumb:pr-review` |
| **Ask for review and answer what comes back** (as the author) | `playbooks/being-reviewed.md` |
| Add a different model family's axis to that review | `plumb:interrogate` |
| Check whether the environment plumb claims still exists | `plumb:doctor` |
| See what a session spent its context on | `plumb-session-audit` |
| Decide which configuration of a playbook to run, with a number | `playbooks/evaluating-an-agent.md` |

### Decide, and design

| Job | Playbook |
|---|---|
| Draw the execution graph (2 or more of the 5 signals) | `plumb:graph` |
| **Hand a branching decision back to the owner** (2+ options, and the choice changes what gets built) | `plumb:decision-brief` |

### What plumb has no playbook for

**Shaping the work, writing the plan, running the plan, fixing a bug and writing tests are
all plumb's own playbooks now.** Enter through the "Change" section above. Not one line in
this router forwards to an outside plugin any more.

| Job | Where |
|---|---|
| **Write or repair a skill** | Claude Code's skill-authoring conventions -> `claude plugin validate` -> `plumb:doctor` |
| Who to hand it to | `docs/role-map.md` |
| Driving panes and other agents | whatever `pane.driver` points at (unset: run it in the foreground) |
| The wake-up mechanism (when you wake) | `/loop` and `ScheduleWakeup`. **The discipline lives in `playbooks/autonomous-run.md`** |

Which upstream playbooks were not ported, and why, is in `docs/scope.md`.

## Where the artifacts go

**Do not assemble paths. Ask the tool.**

`plumb-*` are thin wrappers in `bin/`. Claude Code puts every plugin's `bin/` on PATH at
install time, so you can call them by bare name from anywhere.

```bash
plumb-path spec      # approved designs
plumb-path plan      # plans being executed
plumb-path history   # finished plans
plumb-path run       # ledgers, decision logs, briefs
plumb-path spec --mkdir   # create it if it is missing
```

The default is `<repo root>/.plumb/`. Override it with `PLUMB_ROOT`, or with `root=` in
`.plumb/config`. **Spell a path out in prose and one of the two copies goes stale**
(**principle-encode-lessons-in-structure**).

### spec and plan are not the same rank

| | What it is | Lifetime |
|---|---|---|
| **spec** | End state, acceptance criteria, why this approach, what you rejected | **The source of truth.** It is what gets approved; changing it needs re-approval. Tracked |
| **plan** | Files, signatures, **test code**, how to slice the commits | **Disposable.** Stale the moment execution starts. Tracked, but retired when it is done |

**"What has to pass for this to be done" is the spec. "Which tests, written how" is the plan.**
Same tests, two documents: the bar for judging goes in one, the implementation in the other.

`run/` is not tracked (`.plumb/.gitignore`). Ledgers and decision logs are traces of the work,
not the source of truth. **Conversely, specs and plans are always tracked.** A source of truth
that disappears with the working tree is not a source of truth.

### Retire a finished plan by freezing it

**Do not leave a completed plan in `plans/`.** In batch 1, a `docs/plan.md` frozen back at
Task 1 sat 18 lines out of date, still flying a header that said "execute these in order" —
and **anyone who came along and executed it would have rolled back every fix from that day**.

Move it to `history/` and put this at the top:

```markdown
> **This is history. Do not execute it.**
> The current source of truth is <path>. **If this document disagrees with it, the source of
> truth wins.** Do not sync this back up — syncing it revives the second source of truth.
```

**What stops the damage is the header, not the directory name.** Moving it is not enough.

### An existing `docs/superpowers/`

Repositories that have used `superpowers` still carry `docs/superpowers/specs|plans`.
**Do not migrate them wholesale.** Decide per repository. In a repository you have not
migrated, **assume the old material is under `docs/superpowers/`** when you go looking.

## The principle index

**Principles are not skills.** They live in `principles/<name>.md` as plain documents
(`principle-prove-it-works` is `principles/prove-it-works.md`).

They are not skills so that **they cannot fire on their own**. Stopping them with a flag also
seals the path that opens them from this index — which is exactly what had happened on
2026-08-29. **Stop them with structure instead: this index is the only way in, and it opens.**

Read the full text of a principle you are applying. A summary is not enough.

### Core

- **principle-laziness-protocol** — Lean toward deleting and toward the smallest change. When refactoring; when you feel the urge to add an abstraction
- **principle-foundational-thinking** — Settle the core types and data structures before the logic
- **principle-redesign-from-first-principles** — Design a new requirement as though it had been a premise since day one
- **principle-subtract-before-you-add** — Strip the dead weight first, then build on the base that got simpler
- **principle-minimize-reader-load** — Count the layers between question and answer, and the hidden state the reader has to carry
- **principle-outcome-oriented-execution** — Converge a migration on the target design. Do not leave a disposable compatibility layer behind
- **principle-experience-first** — Take the experience of the person using it over what is convenient to implement
- **principle-exhaust-the-design-space** — On a decision with no precedent, build 2-3 competing options and compare them
- **principle-build-the-lever** — Do not do it by hand. Build the tool that does it and the tool that proves it. The tool becomes an artifact the reviewer can re-run

### Architecture

- **principle-model-the-domain** — Express the domain in structure, not in conditionals scattered around
- **principle-boundary-discipline** — Concentrate guards at the boundary. Trust the types inside
- **principle-type-system-discipline** — Make invalid states unrepresentable: brand your types, parse external data at the boundary, do not lie to the compiler, exhaust your variants, derive from the canonical schema
- **principle-make-operations-idempotent** — Converge on the same end state even after a half-finished run
- **principle-migrate-callers-then-delete-legacy-apis** — Migrate the callers and delete the old API in the same wave
- **principle-separate-before-serializing-shared-state** — Remove the sharing first. Serialize only when there is a real invariant

### Verification

- **principle-prove-it-works** — Verify against the real thing. Do not settle for a proxy or for "the build passed"
- **principle-fix-root-causes** — Trace a symptom to its root cause. Reproduce it first
- **principle-sequence-verifiable-units** — Verify each unit before you move to the next. The ordering is itself your proof to the reviewer
- **principle-gate-claims-on-evidence** — Put a gate immediately before you write "done". If you did not run it, do not claim it
- **principle-spend-on-the-outcome** — Name the cost term a lever moved, measure it from the session, and state the spend per unit of finished work

### Delegation

- **principle-guard-the-context-window** — When large output, long files, repeat reads, or a fan-out plan are about to fill the context. Push the bulky work to a subagent and keep only the summary in the main session
- **principle-never-block-on-the-human** — Push reversible work forward, then show the result and let them correct it

### Meta

- **principle-encode-lessons-in-structure** — If you have written the same instruction twice, make it a lint, a check, or a script instead of prose
