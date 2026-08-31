# Pattern catalogue

The stock to draw on when you build a graph. The first half is the workflow patterns Anthropic set out (structure outside a single agent); the second half is patterns specific to graphs.

## Contents

- [A. Anthropic's workflow patterns](#a-anthropics-workflow-patterns)
- [B. Graph structure patterns](#b-graph-structure-patterns)
- [C. Patterns that raise quality](#c-patterns-that-raise-quality)
- [D. Anti-patterns](#d-anti-patterns)

---

## A. Anthropic's workflow patterns

Source: [Building Effective AI Agents](https://www.anthropic.com/engineering/building-effective-agents)

The article's consistent claim, underneath everything: **start from a simple prompt, and go multi-stage only when that is not enough.** Watch that using a pattern does not become the point.

### Prompt Chaining (sequential decomposition)

Split the task into fixed steps, each taking the previous step's output. You can put a code check between the steps.

- **When to use** — a fixed procedure that decomposes cleanly. You buy accuracy with latency
- **Example** — write the text, then translate it; make the outline, then write the body

### Routing (classify and dispatch)

Classify the input and dispatch it to a specialized downstream. Gives you separation of concerns.

- **When to use** — clearly different kinds of input are mixed together, and the classification can be accurate
- **Example** — dispatch by inquiry type; pick a model by how hard the question is
- **Important** — classification is AI, the dispatch control flow is code. Make both AI and the same input takes wobbling paths

### Parallelization

Run at once and aggregate the results in code. Two variants.

- **Sectioning** — split into independent subtasks and run them at once
- **Voting** — run the same task several times, from several angles, to get diversity
- **When to use** — you need speed, or you want confidence raised by several viewpoints
- **Example** — review by angle; a vulnerability scan across several prompts

### Orchestrator-Workers (dynamic decomposition)

A central LLM decomposes the task on the fly, delegates to workers, and integrates the results.

- **When to use** — the subtasks cannot be predicted in advance, and you need flexibility
- **Example** — a code change spanning several files; gathering information from many sources
- **Caution** — if the decomposition is settled in advance, Parallelization is cheaper and its paths are traceable

### Evaluator-Optimizer (a generate-and-evaluate loop)

One side generates, the other returns an evaluation and feedback, in a loop.

- **When to use** — the evaluation criteria are clear and you have confirmed that iterating actually improves the result
- **Example** — literary translation; multi-round research
- **Caution** — aimed at something where "iterating makes it better" does not hold, the loop is pure waste

### Workflow or agent

- **Workflow** — a well-defined task that needs predictability and consistency
- **Agent** — when flexibility and model-driven judgment are needed at scale

Three principles: **simplicity**, **transparency** (show the steps of the plan), and **tool design** (document and test the boundary between the agent and its tools carefully).

---

## B. Graph structure patterns

### Fan-out / Fan-in

Branch from one node to many, then collect back into one. The most basic shape. **Always check for a shared-resource barrier before the branch.**

### Diamond

Fan out and fan back in. The most common shape in practice.

### Barrier (a synchronization point)

Place one only when what follows needs *everything* finished. **It is justified only in cases like these**:

- You deduplicate or merge across all results before handing them downstream
- You skip the whole next stage when the total count is zero (early cutoff)
- The next stage's prompt includes "compare against the other results"

**Not reasons**:

- "I want to flatten it once" -> do that inside the stage
- "The stages are conceptually separate" -> stages being separate and synchronization being required are different things
- "The code is nicer that way" -> the wait a barrier imposes is a real cost

### Pipeline (multi-stage, no barrier)

Each item flows through the stages independently. Item A can be in stage 3 while item B is still in stage 1. **This is the default for multi-stage processing.** Total time is "the slowest item's end-to-end time", not "the sum of the slowest item in each stage".

### Router

Change the path by the classification result. As above: AI judges, code branches.

```javascript
const classification = await classifyRisk(diff);
if (classification.severity === "high") return runFullAudit(diff);
return runQuickReview(diff);
```

---

## C. Patterns that raise quality

### Adversarial Verification

Stand up N independent skeptics per claim and have them read **with refuting as the goal**. Drop the claim if a majority refutes it. This is what kills plausible-but-wrong artifacts. State it in the prompt: when in doubt, fall toward refuted.

### Perspective-diverse Verification

When there are several ways to fail, splitting the angles catches more than running the same check N times. Divide the roles: correctness / conformance to convention / reproducibility / performance. It catches failure modes redundancy cannot.

### Judge Panel

Generate N options under different policies, score them with parallel judges, and graft the good parts of the others onto the winner. When the solution space is wide, this beats iterating on one option.

### Loop-until-dry

For things whose count you cannot know in advance — bugs, gaps, edge cases — run **until K consecutive rounds turn up nothing new**. A plain count cap drops the tail.

An implementation note that matters: deduplicate against **everything you have seen, not against what you accepted.** Against the latter, items rejected by the judge come back every round and it never converges.

```javascript
const seen = new Set(), confirmed = [];
for (const f of findings) {
  const id = key(f);
  if (seen.has(id)) continue;   // decide against seen
  seen.add(id);
  if (await verify(f)) confirmed.push(f);
}
```

### Multi-modal Sweep

Line up several agents that search differently — by structure, by content, by proper noun, by chronology. Run them without letting them know what the others found. One way of searching never finds all of it.

### Completeness Critic

At the end, place a node that asks one thing only: what is missing — a search axis never run, a claim never verified, a source never read. What comes out of it is the next round's work.

### Ban the silent cutoff

If you capped the count, skipped retries, or narrowed the scope by sampling, **always record what you dropped.** Trim it silently and it reads later as "everything was covered".

---

## D. Anti-patterns

| Anti-pattern | Why it is bad | Instead |
|---|---|---|
| The top model on every node | cost grows linearly, and the mechanical stages show no difference | Model Tiering |
| The implementer verifies itself | it shares blind spots in the same context, so the verification is circular | an independent verification node |
| Passing whole conversation history between nodes | it eats context and destabilizes downstream behavior | Edge Contract (structured JSON) |
| Making AI do deterministic work | the result wobbles on the same input, and it costs more | put it in code |
| Collecting every gate into one door | one pending decision stops everything | split the gates by batch |
| Rewriting shared files in parallel with no barrier | conflict resolution eats the gain, and the intent is lost too | clear them serially first |
| A termination condition that is only a count | it either cuts off before convergence or runs forever | a compound condition + loop-until-dry |
| A new ledger for progress tracking | a second source of truth appears and drifts | add a column to the source of truth you have |
