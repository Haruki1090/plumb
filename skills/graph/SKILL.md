---
name: graph
description: Design dependencies, shared resources, and verification for complex multi-step engineering work; use when an execution graph or parallel plan is needed.
---

# Execution graph

Use a graph when dependencies, parallel work, or several sources of truth need coordination. A short, linear change can proceed directly. File count alone does not require a graph or a design-approval gate.

## Define only what execution needs

- State the observable end condition and the source of truth. Locate relevant callers and checks before dividing work.
- Group work by cause and shared authority. Use as many nodes as the dependencies require; do not split one cause just to fill a template.
- For each node, record input, responsibility, writable paths, output, and verification. Mark it required or optional before execution.
- Put changes to shared resources before parallel writers. Draw real dependencies and identify which unresolved decision blocks which node.
- Carry evidence paths and concise structured results across boundaries. Do not copy whole histories by default; validate required fields, and do not call AI judgments deterministic.
- Keep user authorization and artifact destinations unchanged. Update external records only when that is included in the request.

## Execution and completion

Run a small graph serially when that is simpler. Delegate only authorized, bounded work; implementation and independent verification must not share a claim of independence. For substantial or risky changes, arrange independent review through `playbooks/being-reviewed.md`; retain an explicit skip when it cannot run.

Every required node must satisfy its acceptance criteria. A failed or missing required node blocks its dependents and completion; independent nodes can still proceed. Optional omissions need a reason. Time or iteration caps terminate an attempt, not prove success. Continue correcting change-related failures while there is a safe, productive path within the request.

Persist the graph when it is needed for review or resumption. Reuse the accepted plan instead of generating a spec per node. Record decisions and evidence in the existing authority, not a parallel ledger. A user-requested approval gate must be honored; do not invent one for routine implementation choices.

## Conditional references

- Execution mechanics and resumption: [execution](references/execution.md).
- Choosing topology: [patterns](references/patterns.md); a worked [example](references/example.md) is optional.
- UI evidence required by the task or useful for review: [UI evidence](references/ui-evidence.md). Capture the before state without overwriting uncommitted work.
- Planning an unresolved implementation: `playbooks/writing-a-plan.md`; executing an accepted plan: `playbooks/running-a-plan.md`. Do not rerun shaping for an already settled node.
