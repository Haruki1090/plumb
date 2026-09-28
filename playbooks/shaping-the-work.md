# Shaping the work

Use this playbook when a material product decision is still open. A concrete request or an accepted spec already supplies the shape; do not ask the owner to approve it again.

## Establish the unresolved decision

Read the relevant existing flow and constraints. Distinguish product choices (what to build, affected behavior, scope) from implementation choices (file layout, APIs, test structure). Resolve implementation choices using evidence and judgment.

Ask only when missing information materially changes the result or permission and cannot be inferred from the request. A new component alone does not require a separate approval ceremony. If the user asks to see a plan before implementation, show the concrete plan first and honor the requested stopping point.

Scale the record to the work: a probe returns evidence and a recommendation; a local change may need only a few lines; structural work may need a durable spec. Reassess the scale when evidence changes, including when the problem becomes simpler.

## Compare meaningful alternatives

Build or inspect disposable options when a small authorized experiment can resolve the question. Keep experiments within the user's data, systems, budget, and side-effect boundaries. Do not invent two extra implementations when the viable path is already clear.

When the owner's choice changes what will be built, use `plumb:decision-brief`. Explain what differs, the evidence, and your recommendation. Group independent questions; wait for prerequisite answers before asking dependent ones. Work that does not depend on a pending answer can continue. Silence never supplies required approval.

An explicit choice can be delegated to the agent by the user. In that case decide, explain the tradeoff, and proceed; do not send the delegated decision back merely because alternatives exist.

## Record and execute

For work needing a durable spec, resolve its location with `plumb-path spec` and follow `docs/artifact-lifecycle.md`. Capture the end state, constraints, acceptance criteria, and material choices. Reuse an existing accepted spec; do not create a second source of truth.

Once the unresolved decision is settled, proceed to implementation or `playbooks/writing-a-plan.md` when dependencies warrant a plan. Use `plumb:graph` when shared state or parallel dependencies need explicit coordination. If the task was only a probe or explanation, return that result without turning it into implementation.

Return the decision or recommendation, evidence, any remaining question, and the next authorized action. Do not enumerate procedural steps that add no reviewable information.
