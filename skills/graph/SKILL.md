---
name: graph
description: Draw the execution graph before you start a large goal - nodes, edges, shared state, human gates, and where verification sits. Use when asked to "design this first", "draw the graph", "graph this out", "plan the parallel lanes", and whenever 2 or more of these hold, many changes to make, work you want to parallelize, alignment with a design doc or source-of-truth document, several files or several screens, subagents to run side by side, or an ask phrased as "all of them", "in one pass", "in bulk". Do not use it for a single, branch-free, short piece of work.
---

# Graph Engineering

## What this skill does

Before you start, **draw one execution graph**. Name the nodes (units of work), the edges, the shared state, the places a human decides, and where verification sits — then implement.

**This skill covers the graph layer only. What lives inside a node — the implement-and-verify loop — goes to the delegation table below.** That is the principle *a loop is one node in a graph* turned directly into structure.

Designing the graph usually takes 10-30 minutes. Running parallel work without it costs you: every lane redone after a collision on a shared file, work-in-progress stalled waiting on a decision, and errors that passed because someone thought they had verified them. **The trade is worth it.**

## First: do you actually need a graph

This is the most important call, and skipping it is how you end up over-designing.

> a loop is a single node in a graph. You don't graduate from loops to graphs.

**When in doubt, stay a loop. Handle it in one node until something demands a second one.**

Draw a graph only when **2 or more** of these five hold:

1. **Split specialization** — the kinds of judgment differ (the head that implements is not the head that rejects against a convention)
2. **Demand for parallelism** — several independent tasks of the same shape, where running them serially makes waiting dominate
3. **Switching models or tools** — the right model or tool changes from node to node
4. **Auditable control flow** — you will have to explain later why this order, and who decided
5. **An overloaded verifier** — one loop is doing both implementation and verification, approving what it just wrote

At one or fewer, do not draw a graph — go straight to **plumb's `playbooks/shaping-the-work.md`**. Leave one line recording the call ("one signal only, staying a loop"). When the size changes later, you can re-decide.

Wrapping a graph around work a loop would have handled adds description cost and speeds nothing up. Workflows whose shape changes as they run also get *more* complicated when written as a graph.

## Designing the graph layer

Fill these in order. An item you cannot fill is a sign the design is not finished, and starting anyway means stalling exactly there.

### 1. Decide the end state

Write "what has to exist for this to be over" so it is observable from outside. "Update the mocks" is not an end state. "All 14 P0 items satisfy their numbered clause in the design doc, and the source of truth reflects it" is.

### 2. List the nodes

Split the work into 5-10 pieces. More than that and management breaks down; fewer and there was no point drawing a graph.

The first thing to do here is **regroup the nodes**. A naive list — by screen, by file, by issue — is usually the wrong set of graph nodes.

- **Bundle items that reference the same source of truth into one node.** Two diffs may stand on different screens, but if their grounds are the same clause of the same design doc, fixing them in separate lanes introduces a contradiction
- **One cause, one node.** Symptoms scattered across three screens still make one node when the cause is one place in a shared file
- Conversely, split an item that mixes two different kinds of judgment

### 3. Inventory the shared resources and place a barrier ★

**Always do this before parallelizing. Skipping it is the single biggest failure pattern.**

List every file, table and setting any node touches, and mark the resources **two or more nodes write to**. Work that touches those gets cleared serially, before the fan-out.

The method is plain: for each node, write down which files it rewrites, then mark every file that appears under more than one node. Collect all the nodes that touch a marked file — that set is the barrier phase.

Run parallel without a barrier and resolving the conflicts costs several times what the parallelism bought you. Worse, one side's intent gets lost in the resolution.

### 4. Draw the edges

Make fixed order, conditional branches (Router), parallelism and send-backs explicit. In particular:

- **Which nodes have to be decided together** (the pairs that go inconsistent if you fix only one)
- **Which nodes wait on another node finishing** (real dependencies only; "I'd sort of rather do this first" is not one)

### 5. Define the state you hand across (Edge Contract) ★

What passes between nodes is **structured data only**. Do not pass conversation history or "everything the previous node output".

```json
{
  "node_id": "billing-cluster",
  "claim": "A9-01 corrected to the single-plan design",
  "evidence": [{"file": "billing.html", "line": 142, "spec": "08-plan-sheet §1.2"}],
  "confidence": 0.9,
  "unresolved": []
}
```

A downstream verification node no longer has to read the whole upstream history, so context consumption drops. At the same time, because what arrives is fixed, **the receiving side behaves deterministically**. Vague handoffs are a leading source of hallucination downstream.

Give every node its inputs, outputs and responsibility (Node Contract): what this node takes, what it returns, and what it does not do.

### 6. Draw the line between AI and code ★

Leave this line undrawn and both cost and uncertainty go up.

| Give to AI | Write in code |
|---|---|
| Understanding meaning, ranking, summarizing | Concatenating arrays, deduplicating, sorting |
| Evaluating, generating hypotheses, spotting contradictions | Type checks, conditionals, counting, saving files |

The basic form is "AI judges, code decides the control flow". Let AI do the classification itself, but write in code what runs next given that result. Otherwise the same input takes different paths.

### 7. Place the human gates (Human Gate) ★

Judgment that carries responsibility stays with a human. How you place the gate matters.

**Do not "close every gate before starting".** Collect the open questions into a single door and one pending decision stops everything. In practice most open questions do not block the first batch.

What you do instead is cross **open questions × the nodes in the first batch** and pull out only the ones that genuinely block that batch. That alone routinely moves the start date days earlier. The rest go behind, as gates on later batches.

### 8. Decide the termination conditions and the failure isolation

**Hold the termination condition as a compound.** Count alone either cuts off before convergence or runs forever.

- Max iterations / max tokens / max time
- Reaching the quality bar
- **No new findings** (loop-until-dry: stop when two consecutive rounds turn up nothing new; a plain count cap drops the tail)

**Failure isolation** — one node failing does not stop the whole thing. Aggregate parallel results with the failures excluded, and hold a separate threshold: "fail the whole run if valid results fall below N".

### 9. Record, resume, and write back to the source of truth ★

Long-running work always gets cut off partway. Make it resumable from where it stopped.

Then, at the end, **land the results in the source of truth**. Forget this and the graph's results evaporate with the session. Make it part of a node's responsibility to write status and grounds back to the matching line of the source of truth — the design doc, the ticket, the ledger — when the node completes.

**Keep one source of truth.** The urge to create a new ledger for progress tracking is strong, and the moment a second source of truth exists it will drift. Add a column to the ledger that already exists.

This rule applies to what you delegate to as well (see below).

### 10. If you changed UI, show the screen (best effort) ★

**A graph that touched frontend or UI puts screenshots of what changed where in the PR.** Not mandatory, but tilted far enough that the decision *not* to include them is the one that needs a reason.

The reason is that **UI changes cannot be evaluated by reading the diff**. A change like "took a feature buried in settings and put it somewhere visible" — `+978 −466` tells you nothing about whether it was good. Paste the screen and the review takes 5 seconds.

At graph-design time you decide two things only. **Which verification node takes the shots** (the node that already drives the real thing, if there is one; do not add a node just for capture), and **how you secure the before state** (shoot it first, or restore with `git archive`; after implementation it no longer exists).

What to capture, WebP conversion, and the image-URL trap in private repositories are in `references/ui-evidence.md`. **GitHub has no API for uploading an image into a PR body**, so automating it leaves few routes. Start without knowing this and you get stuck at the very end.

## Delegate the node layer

Once the graph layer is designed, do not write the inside of each node yourself.

| What the node does | Delegate to |
|---|---|
| Implementation | **plumb's `playbooks/writing-a-plan.md`** -> **`playbooks/running-a-plan.md`** (a small node can be implemented directly) |
| Independent verification | **REQUIRED SUB-SKILL: plumb's `playbooks/being-reviewed.md`** (the section for the side asking) |
| Send-back loop | SDD's fix loop (5-round cap, with an arbitration flow) |
| Which model goes on which node | SDD's Model Selection |
| Closing out the branch | **plumb's `playbooks/closing-a-branch.md`** |

Four principles about verification survive the delegation. Write them into the "Verification" field of the graph definition and hand them over.

- **Never let the agent that implemented it verify its own work.** The same model in the same context shares the blind spots, so the verification is circular
- **Refutation-oriented** — ask "can I refute this", not "is this right". When in doubt, fall toward refuted
- **Spread the viewpoints** — when there are several ways to fail, one pass each from a different angle (correctness / convention / reproducibility) catches more than the same check three times
- **Concentrate cross-cutting rules in a single verification node** — banned words, style conventions, an error-display policy and other global rules must not be interpreted per lane

**Cost lands on the controller, not on the nodes.** Model Tiering can make nodes cheap, but a controller that delegates while still holding the runbook and the research results grows more than the nodes shrink. There is a measured case where 99% of the cost landed on the controller. Keep what you hand to a node down to the Edge Contract (step 5). That is the second reason step 5 pays.

## Constraints on using other playbooks inside a graph

**1. Do not run `playbooks/shaping-the-work.md` in a node.** The graph definition is the spec. Redrawing the design per node collapses the node boundaries the graph set.

**2. Do not let a node generate spec or plan files.** They duplicate the graph definition. **This is step 9's "keep one source of truth" applied directly.** What you delegate to will write and commit a spec or plan by default — plumb's own `playbooks/writing-a-plan.md` does, and so do existing implementation loops. Forbid it explicitly in the text you hand the node.

**3. Do not use `isolation: 'worktree'` unconditionally.** A worktree does not copy gitignored files (`.env` and the like). A verification node that depends on docker compose will not run in one. Use it only for nodes rewriting files in parallel, and run verification that starts containers in the main tree.

## Output: the graph definition

Always leave the design in a file. Keep it in your head and it falls apart once you start.

```markdown
# Graph definition: <goal name>

## End state
The completion condition, observable from outside.

## Graph or loop
Signals that hold: <numbers and why>. -> Draw the graph / stay a loop.

## Nodes
| ID | Responsibility | Input | Output | Files it touches | Delegate to |
|----|----------------|-------|--------|------------------|-------------|

## Barrier (cleared serially, first)
The shared resources and the nodes that touch them. One line of why.

## Human Gate
| Open question | What it blocks | Due |
|---------------|----------------|-----|
Only what stops the first batch goes under "decide first".

## Parallel lanes
The lanes after regrouping. One lane = one source of truth.

## Verification
The bar and the grounds for each lane. Cross-cutting rules stand separately. Write it refutation-oriented.

## Termination conditions
List the compound.

## Writing back to the source of truth
What gets written back, and where.

## How the result is shown (only when UI was touched)
Which screens to capture, and how the before state is secured (shoot first / git archive). Which verification node captures them.
```

## Putting it into execution

If the graph is small (3-5 nodes), running it straight through in order is faster. **The value of designing the graph does not depend on how you execute it.** The design itself has already killed the collisions, the stalls, and the missed verification.

How to write it with the `Workflow` tool, how it survives a long run, resumption, and the determinism caveats are in `references/execution.md`. The stock of patterns is in `references/patterns.md`. A worked example that was actually run is in `references/example.md`.

## Cap the count on the first run

Even with a correct design, do not push every node through the first time. **Start with a cap, run part of it, and confirm the verification node is really working.** Push everything through without noticing that verification is passing things blind and you mass-produce wrong artifacts. That is the most expensive failure there is.

## How this breaks

- **Parallelized without drawing the graph** -> collision on a shared file. Do not skip the barrier analysis (step 3)
- **Stalled trying to close every gate** -> step 7. Pull out only the open questions that stop the first batch
- **Let the implementer verify** -> delegate independent verification to plumb's `playbooks/being-reviewed.md`. Do not let the same agent carry on
- **Turned the list straight into nodes** -> step 2. Bundle what references the same source of truth
- **Made a graph out of work a loop would have handled** -> the call at the top. Under 2 signals, go straight to `playbooks/shaping-the-work.md`
- **A spec per node, and the source of truth doubled** -> step 9. The graph definition is the spec
- **The results evaporated** -> step 9. Make writing back to the source of truth part of a node's responsibility
- **Changed UI and the PR was diff only** -> step 10. The "before" especially: forget to capture it and you are reshooting
