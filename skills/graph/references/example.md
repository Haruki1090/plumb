# A worked example: 125 mock diffs in one pass

A record of actually running these steps, with the numbers and the calls left concrete. Read it to get a feel for what happens where.

## The situation

- 15 screens of plain HTML/CSS/JS mocks (12 customer-facing + 3 internal), 4 shared asset files
- **125 diffs** against the 26 design docs that are the source of truth, 14 of them P0
- **11 open questions** awaiting a ruling
- The diffs were already organized in a Notion database. **Every row carried its grounds: the numbered clause of the design doc**

## Graph or loop

Signals that hold: split specialization (implementing and checking conventions are different heads), demand for parallelism (125 items), auditable control flow (the alignment with the design docs has to be explainable later), an overloaded verifier (the implementer was judging their own conformance). **4 hold -> draw the graph.**

## Step 2: what regrouping the nodes turned up

Naively, "15 screens = 15 lanes". Regrouping by the clause each diff cited said otherwise.

- **Billing cluster** — A9-01/02/03, A5-01, C-08, D-03, D-04 all referenced one source of truth, `08-plan-sheet-design.md` §1.2 and §5. Fixed in separate lanes, the numbers disagree. **One node**
- **F-069 cluster** — A6-08, A7-06, A8-01 through 05, D-06 are one contract in `15-A8 §5`. **One node**
- **"Demo elements mixed in"** — filed as three separate items across three screens (X-02, A5-12, A8-08), but the cause is one place in the shared `mock.js`. **One node**

The real parallelism turned out to be **9-10 lanes**, not 15.

## Step 3: barrier analysis (this paid the most)

Writing out "files it touches" for every node showed 4 files appearing under more than one node.

| File | Nodes that touch it |
|---|---|
| `mock-data.js` | all of D-01 through D-08 + the billing cluster |
| `app.css` / `tokens.css` | X-01, X-03, X-04, X-05, C-06 |
| `mock.js` | X-02, A5-12, A8-08 |

Scattered across parallel lanes, nearly every lane would have been writing to the same 4 files and colliding. The structure changed to **13 nodes handled serially first, as the barrier phase**.

## Step 7: what splitting the Human Gate turned up

The documentation said "close the §4 rulings list first". Read plainly, that means waiting on all 11 decisions.

Crossing the 11 open questions against the composition diffs in the first batch (the P0 corrections) showed that **exactly one of them genuinely blocked that batch**: whether customer template export was in this release. The other 10 were gates on later batches.

That one cross-check turned the start from "waiting until all 11 rulings are in" into "decide one and start today".

## Why verification came nearly free (the part now delegated to plumb's `playbooks/being-reviewed.md`)

Every Notion row already carried its `grounds` — the numbered clause of the design doc — so the verification node's input was assembled from the start.

```
Input: the HTML after the change + the numbered clause it stands on
Ask: does this change satisfy what that clause requires? Try to refute it.
```

On top of that, the cross-cutting rules (banned words, the convention for writing precision, errors inline and toasts for success only) drift whenever they are interpreted per lane, so the structure put **the same verification node across every lane**.

## What it taught

1. **The documents that already exist are often already the graph.** Read the structure of what is there instead of creating a new ledger. Here, "every row carries its grounds" meant the node-to-source-of-truth edges were already drawn
2. **The order of a list — by screen, by issue — is usually the wrong set of graph nodes.** Regrouping is worth the time
3. **Barrier analysis and splitting the Human Gate return far more per hour spent than anything else.** Both take about 15 minutes
4. **Counts disagree.** The document's tally said P0 = 12; counting rows gave 14. Count the nodes yourself
