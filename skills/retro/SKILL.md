---
name: retro
description: The weekly look back over agent work in one repository - which landed changes were fixed later, what the work cost on which models, and which failures happened - ending in at most three changes, each with its owning layer and the number that will show whether it worked. Use when asked for "the weekly retro", "look back at last week", "how did the agents do", "what did this week cost" or "what should we change in how we work". Not for one failure (plumb:failure-to-rule) or one pull request (plumb:pr-review).
---

# The weekly retro

Read the numbers for one repository and one period, and decide what to change next. The tools
gather; this skill reads and chooses. It changes nothing by itself: no code, no labels, no issues,
no pull requests.

The period is last Monday to Sunday in the contract's `ledger.timezone` unless the owner names one.
Write everything under `plumb-path run`, in `retro/<since>/`, never in the tracked tree.

## 0. Check what is there, and say what is not

Run each, from inside the checkout, and keep its exit status:

```bash
plumb-project rework.required_authors   # who is in the rework cohort (0 and empty: no cohort)
plumb-config ledger.store               # empty: cost covers this machine only
gh api user --jq .login                 # GitHub REST reachable
```

- `plumb-project` exits 2 or 3: **stop**, report its stderr line. A broken contract is never read as
  "no policy".
- `gh api` fails: **stop**, report that GitHub is unreachable. Do not fill numbers from memory.
- No `required_authors`: continue without the rework rate and say so in the review.
- No `ledger.store`: continue; the review says cloud sessions are not covered.

## 1. Gather

```bash
OUT="$(plumb-path run --mkdir)/retro/$SINCE"; mkdir -p "$OUT"
plumb-ledger changes  --repo <owner/name> --since <SINCE minus 14 days> --until <today> --out "$OUT/changes.jsonl"
plumb-ledger rework   --changes "$OUT/changes.jsonl" --since "$SINCE" --until "$UNTIL" --json > "$OUT/rework.json"
plumb-ledger prs      --repo <owner/name> --since <SINCE minus 14 days> --out "$OUT/prs.json"
plumb-ledger report   --repo <owner/name> --since "$SINCE" --until "$UNTIL" --prs "$OUT/prs.json" --changes "$OUT/changes.jsonl" --rework "$OUT/rework.json" --json > "$OUT/cost.json"
plumb-ledger failures --repo <owner/name> --since "$SINCE" --until "$UNTIL" --json > "$OUT/failures.json"
```

Changes run from 14 days before the period to today: the cohort is still only what landed in the
period (`rework` bounds it), but a fix that landed after the period and inside its look-ahead window
must be in the file, or its original is counted clean. The report is scoped to this repository with
`--repo`; requests of other repositories and those whose repository is unknown are counted beside
it, never added. If any
command fails, stop there and report the command and the first line of its stderr; never estimate
the missing number. Records and bodies stay in `$OUT`: the review carries numbers and pull request
numbers only.

## 2. Read last week's proposals

Open the previous `retro/<since>/review.md`. For each proposal record its state (adopted, declined,
not started) and whether its number moved. A proposal adopted four weeks ago whose number did not
move is a finding of this week.

## 3. Choose at most three

Look for, in this order:

- **Rework.** The changes fixed within the look-ahead window, and the failure codes
  (`docs/failure-taxonomy.md`) that recur. Failures with no code or no layer are a finding too:
  classify them with `plumb:failure-to-rule`, not here.
- **Cost.** The most expensive tasks, the frontier share, which roles and agent types spend most,
  and which token kind dominates (an hour-long cache write that dominates is fixed by splitting
  sessions, not by changing models).
- **Coverage.** Unknown attribution, unknown cost, ambiguous tasks and pending exports. A number you
  cannot attribute is not a number you can act on.

Each proposal names: what to change, the **layer** that owns it (`docs/failure-taxonomy.md`, "Layers"),
the number that will show whether it worked and when to look again (four weeks by default), and,
for a CI rule, that it reaches everyone and is the repository owners' call. Run the experiment with
`playbooks/hillclimb.md` or `playbooks/evaluating-an-agent.md` and log the decision with
`plumb-decision-log`; this skill does not grow its own experiments. Working a failure out in detail
is `plumb:failure-to-rule`.

## 4. Write `review.md`

```markdown
# Retro <SINCE> – <UNTIL> (<repository>)

## Numbers
| | This week | Last week |
|---|---|---|
| Cost (list price applied to recorded tokens) | | |
| Frontier share | | |
| Landed changes | | |
| Reworked within the window (cohort) | | |
| Cohort changes with a readable Fixes-PR line | | |
| Failures (agent-failure), by layer | | |
| Unknown: attribution / cost / failure code | | |
| Coverage (pending exports, store) | | |

## Costliest tasks (top 5)
| Task | Cost | Main model | Note |

## Failures by code
| Code | Count | Records |

## Last week's proposals
| # | Proposal | State | Did the number move |

## Proposals (at most three)
| # | Change | Layer | Number to watch | When | State |
```

Report the same in short form. Say which machine the local records came from and whether the store
was read. Costs are list prices applied to recorded tokens: on a flat-rate plan they compare tasks
and models, they are not the bill.

## How this skill is judged

By the share of its proposals that are adopted, and whether the adopted ones move their number
within four weeks. Two weeks in a row with nothing adopted means the proposals are wrongly sized or
aimed: change how they are chosen.
