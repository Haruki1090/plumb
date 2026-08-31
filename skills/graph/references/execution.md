# Ways to execute it

Once the graph definition exists, this is the mapping that turns it into something that runs. Assumes Claude Code.

## Design element -> how it runs

| Design element | How it runs |
|---|---|
| Node | one subagent, or a step of code. Its implementation and verification are delegated (SKILL.md, "Delegate the node layer") |
| Parallel lane | `Workflow`'s `parallel()` / `pipeline()`, or several Agent calls in one message |
| Barrier | `parallel()` (waits for all), or simply split the phases and write them serially |
| Pipeline (no barrier) | `Workflow`'s `pipeline()` |
| Edge Contract | `agent()`'s `schema` option (enforced by JSON Schema; validation happens in the calling layer) |
| Model Tiering | `agent()`'s `model` / `effort` options |
| Separating the workspace | `isolation: 'worktree'` (**has constraints. Read "Worktree constraints" below first**) |
| Human Gate | stop execution and ask a human. Do not bury it inside the graph |
| Writing back to the source of truth | write back with an MCP tool (Notion, GitHub and the like) after the run |

## Using the Workflow tool

**Precondition**: use `Workflow` only when the user explicitly asked for multi-agent execution. "Design the graph" is a request for a design, not for a run. Show the design and confirm before executing.

The default structure is `pipeline()`. Use `parallel()` only when you need every upstream result at once.

```javascript
export const meta = {
  name: 'lane-and-verify',
  description: 'implement lane by lane, verify each one independently as it finishes',
  phases: [{ title: 'Implement' }, { title: 'Verify' }],
}

const results = await pipeline(
  LANES,
  lane => agent(lane.prompt, {
    label: `impl:${lane.id}`, phase: 'Implement',
    schema: NODE_OUTPUT,          // Edge Contract
    isolation: 'worktree',        // keeps collisions off everything but the shared resources
  }),
  (out, lane) => agent(
    `Decide whether the following change satisfies ${lane.spec}. Try to refute it. When in doubt, refuted.`,
    { label: `verify:${lane.id}`, phase: 'Verify', schema: VERDICT, effort: 'high' }
  ).then(v => ({ lane: lane.id, out, verdict: v }))
)

return results.filter(Boolean).filter(r => !r.verdict.refuted)
```

The points:

- Verification is a **separate `agent()` call** from implementation. Do not let the same agent carry on
- With `schema`, the return value comes back as a validated object. You write no parsing, and a shape that does not match makes the model retry
- `agent()` returns `null` when it fails. `.filter(Boolean)` before using the results (failure isolation)
- Naming `phase` explicitly keeps the progress display grouped stably
- `isolation: 'worktree'` has a setup cost, so use it **only when rewriting files in parallel**

## Worktree constraints

Before using `isolation: 'worktree'`, check what the node needs.

- **Gitignored files are not copied.** `.env`, `.env.local` and local-only directories do not exist in the worktree. A `docker-compose.yml` that requires them as `env_file` **fails at config resolution, let alone startup**
- **The compose project name changes with the directory name.** Named volumes become different volumes, so the database data and the caches start empty. If it publishes fixed ports, it cannot run alongside the main stack
- **Lint and test results can disagree with the main tree.** Warnings disappear exactly to the extent that gitignored directories are missing. Do not claim "local CI passed" on the strength of a worktree run
- **A gitignored graph definition is invisible from the worktree.** Hand the node the absolute path in the main tree

So **what belongs in a worktree stops at nodes that edit source and run lint / test / build**. Verification nodes that start containers — touching a database, E2E — run outside the worktree.

## Specifying model and effort

When a node is delegated to `playbooks/running-a-plan.md`, **`docs/role-map.md` is the source of truth for role assignment** and this document carries no model names. What follows is a rough guide for building directly with Workflow.

The default is to specify nothing. Unspecified, a node inherits the parent session's model.

| What the node does | What to specify |
|---|---|
| Extraction, classification, mechanical transformation | `effort: 'low'`, and a lighter model if needed |
| Implementation, investigation | nothing (inherit the default) |
| Verification, arbitration, final integration | `effort: 'high'` or above |

If you are not sure, specify nothing. Lower it and verification slips through; raise it and only the cost goes up.

## Without the Workflow tool

If the graph is small (3-5 nodes), writing it out plainly beats building a Workflow.

- Independent nodes run at the same time if you put **several Agent calls in one message**
- Anything that can be serial just runs in order
- A barrier is achieved by splitting the phases and nothing else

**The value of designing the graph does not depend on how you execute it.** The design itself has already killed the collisions, the stalls, and the missed verification. Executing it by hand still pays.

## Surviving a long run

Source: [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

Context always runs out, so keep the state outside.

- **A progress file** — write what is finished to an external file. A new session reads it to pick up the situation. Do not rely on context to remember
- **Restrict updates to the item list** — let it rewrite the completion flag and nothing else. Never the items themselves. Left alone, the requirements get rewritten and everything is "done"
- **A health check at session start** — confirm that what was built so far still runs before starting new work
- **Commit often** — commit in slices with descriptive messages. If something goes wrong you can go back
- **Compaction alone is not enough** — context compaction is necessary, but on its own it does not carry work across several contexts. Pair it with external state

## Resuming

`Workflow` resumes with `resumeFromRunId`. The unchanged head of the script returns instantly from cache, and only what follows the first change re-runs.

Before resuming, confirm that the nodes marked finished **really returned results with something in them**. An empty result can be sitting in the cache.

## Keeping it deterministic

- `Date.now()`, `Math.random()` and no-argument `new Date()` cannot be used inside a workflow script (they break resumption). Pass the time in as an argument, or attach it after the run
- When you need randomness, vary the prompt or the label by index
