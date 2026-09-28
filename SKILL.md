---
name: plumb
description: Route complex engineering work to plumb playbooks and principles when plumb is requested or the task needs an explicit engineering workflow.
---

# plumb

## Runtime adapter

Claude Code remains the canonical runtime for this harness. When the current session is an OpenAI
coding agent, read `docs/openai-runtime.md` before applying any instruction about roles, agent return
values, tools, configuration paths, or command lookup. That document translates the execution surface;
it does not replace the playbooks or principles below.

## Apply only the relevant workflow

Use the requested outcome, existing authorization, and task risk to select one playbook below. Short, well-defined work can proceed directly. Read a principle when its decision criterion is relevant; name it alongside the decision it changes, without narrating every rule.

The current session remains responsible for integration. Runtime role mapping is in `docs/role-map.md`; read it when assigning roles. For non-trivial plumb work, keep one visible judge line: run the configured independent review or record `skip: <reason>`. A skip does not stop safe, authorized work or establish independent verification.

Continue through the requested deliverable and relevant checks. Ask only for unresolved choices that change scope, permissions, or the result. Existing approval remains valid; a playbook does not authorize external publication or messages. An explicit plan/review gate requested by the user still applies.

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
| **Work a queue as the coordinator** (review the open PRs; implement the assigned issues one by one) | `plumb:lead` |
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
| Coordinate dependencies, parallel work, or multiple sources of truth with an execution graph | `plumb:graph` |
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

## Artifact paths

When writing or retiring a spec, plan, or run ledger, read [artifact lifecycle](docs/artifact-lifecycle.md). Resolve paths with `plumb-path`; do not create a second source of truth.

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
