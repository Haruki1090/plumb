# Pitfalls

When something goes wrong, look up the symptom, check the cause, do what the last column says. Every row
rests on a command, a file or a playbook that exists in this repository. If your symptom is not here, say
what you checked and what you could not; do not guess across the gap.

The commands are on your agent's path, not your shell's. Ask the agent to run them and show the output.

| Symptom | Likely cause | What to do |
|---|---|---|
| It said done and it was not | A claim was accepted in place of a run (`principles/gate-claims-on-evidence.md`) | Ask for the command and its output, before and after. For a running app, ask for `plumb:verify`, which compares base and head and never says "pass" |
| A skill did not fire | The skill's `description` does not match how you phrased the request | Name it in the prompt ("use plumb:verify"). To fix the routing, measure with `plumb-trigger-eval --cases evals/<skill>/triggers.csv --skill plumb:<skill> --out <dir>` and ask `plumb:reflect` for the change |
| The context filled early | Large outputs, repeated reads, or a long idle gap that forced a rebuild | `plumb-session-audit` flags the sessions (`CTX-P90-OVER`, `IDLE-REBUILD`); `plumb-prompt-weight` weighs the fixed prompt you control. Before leaving a session for an hour, ask for `playbooks/pause-safely.md` |
| A lane went quiet | The agent in it is stuck, waiting on an unseen prompt, or gone | `plumb-lane stale` lists running lanes silent for a multiple of their expected time. Inspect that worktree and replace the lane; do not wait on it |
| Cost is unknown | Capture is off, so nothing was recorded | `plumb-config ledger.capture` prints empty. Set `ledger.capture = on`, then read `plumb-ledger report --since <day> --until <day>`. Records are in [docs/ledger.md](../ledger.md) |
| Verification says absent | The repository has no `[verify]` contract (`plumb-verify plan` exits 4) | Ask for `plumb:verify-init`. Until then your own tests are only tests, not verification |
| The judge line says skip | `role.judge` is unset or its command is missing | `plumb-config role.judge` shows the value; the doctor says whether the command resolves. Set it as in [A first hour](01-first-hour.md). A skip is never independent verification |
| Two agents edited the same file | Work was fanned out before listing what each job writes | Give each writer its own worktree (`playbooks/worktree-setup.md`) and list shared writes first, step 1 of `playbooks/fan-out.md`. If the causes are connected, do not fan out |
| A fix came back | The cause was patched, or no test kept the repro | `playbooks/fixing-a-bug.md`, step 6: keep the repro as a test. `plumb-ledger rework` counts changes fixed later, from the `Fixes-PR:` line. Take the pattern to `plumb:failure-to-rule` |
| A number looked too good | A run that got faster by failing, or too few runs, or the wrong surface | `principles/explain-the-number.md`: ask for run count, spread and error count beside every figure. Anything measured on a different surface is "cannot be judged", not a pass |
| The plan went stale | A plan is disposable and goes stale once execution starts; the branch moved | Stop. Ask for the plan to be read against `git log`, each contradiction ruled on and written in the ledger (`playbooks/running-a-plan.md`, step 1). If the shape changed, return to `playbooks/shaping-the-work.md` |
| The same review finding keeps coming back | It is being answered one comment at a time, or it was never taken in with a reason | Ask for `playbooks/being-reviewed.md`: verify each finding, reply in its own thread, and give a reason for what was not taken in. If it recurs across pull requests, `plumb:failure-to-rule` |
| Pull requests are waiting and nobody knows | Nothing reports what waits on whom | `plumb-stalled`; for one pull request, `plumb-pr-watch <number>` answers in one word |
| Worktrees and disk pile up | Lanes leave a checkout each and nothing removes them | `plumb-worktree-audit` lists each with size, age and merge state, read-only. Then `playbooks/worktree-cleanup.md` |
| A test passes alone and fails in the set | State left behind by an earlier test | `plumb-isolate-pollution '<detect residue>' '<run one>' <target>...` stops at the first polluter. Fix the side that left it, not the side that fell |
| A review bot keeps flagging the same thing | Each comment is judged from scratch every time | `playbooks/landing-a-stack.md`: classify it fix / dismiss / ask, and keep the pattern in `.plumb/review-patterns.md` with a confidence that repeated outcomes raise |
| A pull request body says more than the diff does | The body is the author's belief, not fact | `plumb-check-pr-body` checks sections and length mechanically before opening; `plumb:pr-review` checks the claims against the diff |

## Before you look anything up

Ask three questions first, because they explain more failures than any single row.

1. **Does the doctor print an `NG`?** A broken pointer, a missing tool or a store that does not answer
   shows up there before it shows up in a run. A `--` is only an unset option.
2. **Did the request carry a done-condition?** Without one the agent cannot tell that it stopped short, and
   neither can you. [Asking well](02-asking.md) lists what to include.
3. **Is it the first time or the second?** One occurrence is a fix. A second occurrence of the same
   failure is a missing check, and the remedy belongs in a tool, not another reminder.

## What a skip line tells you

A skip is plumb saying that a step did not happen and why. It never stops safe work, and it is never
reported as verification. These are the ones you will see, each with the setting that removes it
(where each role runs is in [docs/role-map.md](../role-map.md)):

- `skip: role.judge unset`: no second family reviewed the work. Set `role.judge`.
- `skip: pane.driver unset — lanes are not visible`: queue work ran without panes. Set `pane.driver`.
- `skip: role.bulk unset`: parallel work ran in order in the main session. Set `role.bulk`.
- `skip: role.implementer unset — implementer runs as a subagent`: set `role.implementer` to route it.

## Three habits that prevent most of these

- **Ask for output, not statements.** Every request on [asking well](02-asking.md) names the evidence
  it wants back. A report without it is a claim.
- **Read the judge line.** If a non-trivial run ends with no judge line, or with `skip: <reason>`, you
  know exactly what was not independently looked at. A missing line is the worse sign.
- **Write the same instruction once, then make it a check.** If you have typed a warning twice, it is a
  missing check (`principles/encode-lessons-in-structure.md`). `plumb:failure-to-rule` finds the layer
  where the check belongs.

When the table does not help, ask `plumb:help`. It answers from this checkout, names the entry that
fits and hands back the prompt to send.
