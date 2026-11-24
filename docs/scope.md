# What plumb does not have

## Runtime scope

Claude Code remains plumb's canonical runtime and owns the shared router, playbooks, principles, and
agent definitions. Codex support is an additive execution adapter: `.codex-plugin/`, `.codex/`,
`skills/plumb-codex/`, and `docs/openai-runtime.md` translate packaging, model placement, delegation,
and return-value mechanics without forking the shared behavior. A Sol/Luna split is explicitly kept
separate from the genuinely different-family judge requirement.

**The upstream commit last read is recorded in `NOTICE`** (the `Upstream last read:` line). `plumb-upstream-diff`
lists the files that changed upstream since then; `plumb-upstream-diff --unrecorded` lists the upstream
skills, playbooks, agents and guide pages whose name appears nowhere in this document, which is how a new
item with no recorded decision gets found. Moving the recorded commit forward is a person's edit, after reading.

plumb starts from the playbooks in pstack (`pstack/` in `github.com/cursor/plugins`, MIT).
**13 playbooks come from pstack**, broken down in the table below. **The rest did not come
from pstack** (see "Written outside pstack" below).

**On 2026-08-31 the last verbatim asset went away.** 21 of the 22 principles then carried
pstack's English body text; all 21 were rewritten in plumb's own words (466 → 1,010 lines).
**These are not translations.** The upstream text was read only to grasp what failure each
principle exists to prevent, then closed, and what got written was **the mechanism that makes
the principle hard to keep** and **how to judge afterwards whether it was kept**. Only the
English names stay, because the 22 playbooks call them by those names in their body text.
**At that point, the amount carried over verbatim from pstack became zero.**

**The upstream count changes with how you count.** The upstream README says "22 playbooks" in
its body and prints a table of that many, but the directory itself,
`skills/poteto-mode/playbooks/`, holds 23 files: `opening-a-pr.md` exists and is missing from
the README's table (measured against `github.com/cursor/plugins` on 2026-08-30). The breakdown
below — 11 ported + 3 folded + 9 not ported = 23 — counts **what is actually in the
directory**, so it matches 23, not the README's 22.

*Note, 2026-11-23: the directory now holds 22 files. `orchestrate` and its scripts are gone, and
`autopilot-full` and `autopilot-stack` are there. See "Read again at 0.15.46" below.*

**Keep the record of the difference.** "Not gotten to yet" and "deliberately left out" are
different things, and without a record they stop being distinguishable later. **This document
is also an acknowledgment:** where plumb came from, and where it became something else, is
written here.

## Ported (11)

Ones whose upstream dependencies were thin and whose vocabulary the existing assets did not
have. The bodies were rewritten for this environment.

`investigation` `runtime-forensics` `trace-forensics` `perf-issue` `hillclimb`
`refactoring` `prototype` `pause-safely` `session-pickup` `worktree-cleanup`
`autonomous-run` (**added in batch 3, withdrawing the decision recorded below**)

## Folded (3 → 2)

| Upstream | plumb | Why |
|---|---|---|
| `opening-a-pr` | `playbooks/opening-a-pr.md` | The PR-writing convention (Why / Scope / Tradeoffs / Blast Radius / Verification) is not in the existing assets. The Graphite dependency was replaced with `gh` |
| `babysit` + `shipping` | `playbooks/landing-a-stack.md` | **`gh stack merge` is atomic (all-or-nothing)**, so the whole back half of the upstream text disappears. Watching a queue drain in order, the discipline of not touching it midway, checking that merge-when-ready was armed, the warning against reading `autoMergeRequest` as evidence: **all of it comes from Graphite's sequential merge**. What is left collapses into picking the ceiling correctly. *Note, 2026-11-23: the "no watcher" half of this decision is revised. `plumb-pr-watch` now reads one pull request's state as one word and one exit code. It is a single read, not a queue watcher, and it is how `plumb:lead` and `landing-a-stack` read a pull request* |

## Not ported (9)

### Ride machinery that is not here (6)

`autopilot-full` `autopilot-stack` `orchestrate` `multi-phase-plan` `eval` `visual-parity`

*Note, 2026-11-23: this list is the 2026-08-30 reading. `orchestrate` no longer exists upstream.
Three of the others gave plumb something small without being ported as playbooks (the rows below
for `eval`, and "Read again at 0.15.46" for `autopilot-full`, `autopilot-stack` and
`multi-phase-plan`). `visual-parity` is still not taken.*

They assume Cursor cloud agents, Graphite, a review bot, the `cursor-team-kit` operating
skills, and dedicated CLIs and watchers. **They are also the six longest files upstream**, so
this would be a full rewrite, not a port.

On top of that, `orchestrate` says this about itself upstream: measured, putting the ritual
over a 30-minute, 12-unit job landed 1, while plain agents landed all 12.
**It is not a playbook for the scale one person runs alone.**

**Two of these six are a functional gap, not a hand-off to existing assets.** That is written
down here on purpose.

| Playbook | What carried over, what was dropped |
|---|---|
| `eval` | What now exists is the **blinding rule and corpus/score loop** in `playbooks/evaluating-an-agent.md`, on top of putting the judge role in a different family (`docs/role-map.md`, `plumb:interrogate`). A candidate sees only the repository, PR number, and pinned SHA; truth, fixing PR, evaluation wording, and rival verdicts stay out. **What is still missing is hiding repository history after that SHA.** The run instruction forbids reading later history and discards a verdict that cites it, but plumb cannot make those commits invisible. *Note, 2026-11-23: the blind is now also checked by machine, by searching the paths and prompt a candidate sees for words that reveal the trial, before it runs (`playbooks/evaluating-an-agent.md`). The hiding of later history is still missing* |
| `visual-parity` | What carried over is only **taking the before shot first** and **not touching the baseline** (the UI section of `playbooks/opening-a-pr.md`). **There is no pixel-diff regression harness and no zero-diff pass condition.** An eyeballed screenshot is not proof that nothing changed visually. **plumb stops at eyeballing, knowing that** |

**Do not delete these two rows.** Delete them and the gap starts to read as handed off.

### Would duplicate existing assets (4 originally → 1 now)

**This section nearly emptied out on 2026-08-30.** Only `authoring-a-skill` is left. For the
other three, the premise that existing assets already had them was withdrawn, and they were
written from scratch.

| Upstream | What already covers it |
|---|---|
| ~~`feature`~~ | **Withdrawn on 2026-08-30 and written from scratch.** `playbooks/shaping-the-work.md` → `playbooks/writing-a-plan.md` |
| ~~`bug-fix`~~ | **Withdrawn on 2026-08-30 and written from scratch.** `playbooks/fixing-a-bug.md` + `playbooks/writing-tests.md` |
| `authoring-a-skill` | Claude Code's skill-authoring conventions and `claude plugin validate` |
| ~~`autonomous-run`~~ | **Withdrawn on 2026-08-29 and ported.** `/loop` and `ScheduleWakeup` are **mechanism** (when you wake) and **carry no discipline**: no termination predicate, no smallest change, no rollback, no handling of what you find mid-run, no stalled ≠ stopped. `hillclimb` covers only the single-metric case |

**Porting one creates a second source of truth.** In batch 1, `docs/plan.md` became a stale
second source of truth and an agent that came along later nearly rolled back every fix. This
decision exists so that failure does not get built again.

One row is left in the router's "What plumb has no playbook for" table: `authoring-a-skill`.
**Not one row forwards to an outside plugin any more.**

**`feature` left this section too.** On 2026-08-30, the playbook for deciding the shape before
you build and the playbook for turning a shape into steps were written from scratch in plumb's
vocabulary (the table below). **They are not ports, so they do not count toward the breakdown
above.**

**`autonomous-run` left this section.** Withdrawn on 2026-08-29 and ported
(`playbooks/autonomous-run.md`, listed in the router's "Keep going" section).
**Do not treat it as a second source of truth and delete it.** `/loop` is mechanism; it
carried no discipline.

## Written outside pstack (11 playbooks + 2 principles + 5 tools)

*Note, 2026-11-23: this heading counts the batch it was written for. plumb now has 26 playbooks, 25
principles, 19 skills and many more commands. The counts that stay checked are in README and
NOTICE (harness rules 13 and 14).*

**Problems pstack did not have, and that the existing assets held in another form**, written
from scratch in plumb's vocabulary. These are not ports, so they sit outside the breakdown
above.

| plumb | What it took on | What plumb added |
|---|---|---|
| `playbooks/closing-a-branch.md` | Getting the owner to decide where finished work goes (merge / PR / leave it) | The discipline for folding an isolated workspace stays in `worktree-cleanup.md` as the source of truth and **is not copied here**. Do not mix "throw it away" into the three choices |
| `playbooks/worktree-setup.md` | Creating an isolated workspace | `docs/path-map.md` is the source of truth for where they go (**the roots run in more than one line**). Makes explicit that **ignored files do not get copied in**, as the mirror image of the cleanup gate |
| `playbooks/fan-out.md` | Handing independent work out to parallel roles | The role is `role.bulk` in `docs/role-map.md` (unset: a visible skip). Connects the test for independence to **principle-separate-before-serializing-shared-state** |
| `playbooks/batching-chatty-tools.md` | Moving several calls per answer, or the same call over N items, out of the model loop | The 40KB line and `plumb-session-audit` as the pass condition for `TOOL-RESULT-OVER` |
| `playbooks/evaluating-an-agent.md` | Choosing which configuration of a playbook or agent to run | A pruned follow-up-fix corpus, a pinned-SHA blinding rule, precision / recall / F1 / tokens per review, and a Pareto decision that is re-measured when the frontier moves |
| `playbooks/shaping-the-work.md` | Settling a product decision that is still open before you build | **Only an unresolved product choice goes to the owner**; implementation choices are resolved from evidence, and a concrete request or accepted spec is not re-approved. No separate approval ceremony: the user's explicit plan/review gate is the only stopping point it adds. Scales the record to the work (a probe's evidence, a few lines, or a durable spec). Settles what a small authorized experiment (`playbooks/prototype.md`) can settle before asking; groups independent questions, holds dependent ones for their prerequisite, and keeps independent work moving while an answer is pending |
| `playbooks/writing-a-plan.md` | Turning an approved shape into steps someone else can execute | `plumb-path plan` is the source of truth for where it goes. **The difference in rank between spec and plan, and the freezing discipline, belong to `docs/artifact-lifecycle.md` and are not copied here.** The exception that copies whole-project constraints verbatim out of the spec now carries its reason: **the implementer role never opens the spec** |
| `playbooks/running-a-plan.md` | Landing a plan one task at a time (both handing it out and slicing commits in the main session) | **Cut the ceiling from 5 rounds to 3** (rounds 1-2 the same role, round 3 a different role, then stop). **Moved the base commit out of a shell variable and into a column of the ledger**: a variable does not survive a compaction. Dropped the model-selection section (`docs/role-map.md`'s territory). Added no workspace-creation mechanism either (`plumb-path run` has it) |
| `playbooks/fixing-a-bug.md` | Getting a repro first, then tracing the symptom back to the root cause and fixing it | **Did not adopt `defense-in-depth` (scatter checks across every layer)**: it collides head-on with **principle-boundary-discipline** (concentrate guards at the boundary, trust the types inside). Step 6 falls on the side of tightening the boundary, and **says so**. Kept the verification that does not wait on a clock and the isolation of the polluter; rewrote the tooling to be language-independent |
| `playbooks/writing-tests.md` | The content of the tests themselves. A test you never watched fail protects nothing | **Gave five names to tests that protect nothing and banned them** (the whiff, the mirror, the transcript, the stand-in check, the loosened test). Ends with "**break one place in the product and say which test fails**", to put it in a form you can judge instead of assert |
| `playbooks/being-reviewed.md` | Asking for review as the author, and answering what comes back | **Puts the asking side and the receiving side in one document.** Asks for the answer in the same **two axes** as `plumb:pr-review` (confidence × blocking), and does not bring in a single-axis severity |
| `principles/gate-claims-on-evidence.md` | Passing a gate before you claim done | **The method belongs to `prove-it-works`.** This principle owns the **trigger point** only, so it does not become a second source of truth |
| `principles/spend-on-the-outcome.md` | Connecting session cost to finished work | Names the three controllable terms between reach and price, requires a measured term for every claimed saving, and makes cost per unit of work the comparison |

**A principle written from scratch carries `origin: plumb` in its frontmatter.** `NOTICE`
claims how many files in `principles/` are verbatim copies of pstack, and rule 13 of
`scripts/check-harness.sh` checks that number against the directory. **Forget the mark or
forget to fix NOTICE, and either one goes red**
(**principle-encode-lessons-in-structure**). The count is now 23 / 0. *(2026-11-23: 25 / 0.)*

**The same rot had reached README.** "the 13 playbooks" (actually 22), "Twenty-one principles"
(actually 22). Rule 13 guarded NOTICE, but nobody was watching README. **Rule 14 was added,
and it was measured firing on both a wrong count and a spelled-out number** (counts are
written as digits by convention because a machine cannot read the spelled-out form).

## Deliberately dropped from upstream in the principle rewrite

| Dropped | Why |
|---|---|
| The fixed `Why:` → `The pattern:` → `Applications:` structure | **Tracing it produces a translation.** Each principle's sections were rebuilt around the shape in which that principle breaks |
| Exhaustive per-language idioms (the seven-pattern list in `type-system-discipline`, and the like) | plumb does not pick a language. **Inverted into "how to tell, and how to fix"**, with the examples swapped for plumb's own practice |
| The examples upstream gave | **Replaced with plumb's own** (`plumb-worktree-audit`, `plumb:doctor`, ledger counts, approved × sent back, and so on) |
| Signature phrasings such as `Prime directive:` | Translating them makes it an adaptation |

**What went in instead** is the same two things in every principle. **The mechanism that makes
it hard to keep**: a principle you can keep by being careful is not a principle, so the cause
of the breakage got dug out one level. And **the judgment**: the question, gate, or count that
lets you say afterwards whether it was kept. Those two additions are why the line count runs
higher than upstream. **Getting shorter is not the goal.**

Five tools were added as well. `scripts/isolate-pollution.sh` (`plumb-isolate-pollution`) picks
out the polluter one case at a time when things pass alone and fail together. **The upstream
script of the same kind is hardwired to npm, and if residue is already there before the run it
reports the first case as the culprit.** It was rewritten to take the check command and the
run command as arguments, and **to exit 2 on pre-existing pollution**, so an innocent case
does not get named.

`scripts/session-audit.py` (`plumb-session-audit`) streams one project's Claude Code
transcripts and measures context per request, oversized tool results, the size of the first
request (the fixed prompt), and cache rebuilds after idle resumes without printing transcript
content. `scripts/prompt-weight.py` (`plumb-prompt-weight`) estimates what the user-controlled
part of that fixed prompt weighs, from the files the runtime loads; the runtime's own prompt and
tool schemas are not visible to it. It separates usage volume, request overhead,
and context growth so a change can be assessed per completed task. Its thresholds were measured
on 2026-09-02; they are diagnostic defaults, not universal limits or guaranteed savings.
Execution graphs organize work and verification; they do not provide a repository knowledge index.
plumb does not bundle an indexing service, tool gateway, live cost dashboard, or managed-agent platform.
An explicit native audit mode normalizes scoped cumulative usage snapshots, retains unknown fields,
and rejects duplicate session exports and discontinuous counters. Runtime-specific invocation and
coverage limits live in `docs/openai-runtime.md`.

`scripts/bench-extract.py` (`plumb-bench-extract`) turns a fixing PR's overlapping hunks into draft
truth without overwriting a person's reviewed pruning. `scripts/bench-score.py`
(`plumb-bench-score`) matches review locations against that truth and compares configurations by F1
and tokens per review. The corpus stays private; only its format and one repository-owned example
ship with plumb.

After marketplace installation, `$plumb:setup` resolves `bin/plumb-codex-install` from the installed
plugin and installs the optional Codex profile and native custom-agent definitions at user or project
scope. The installer is idempotent, refuses to replace a differing destination by default, and leaves
the Claude installation untouched.

**What was dropped** is either something each playbook already holds in another form, or a
step riding machinery this environment does not have: the menu boilerplate, the opening
speech, the three severity levels, the approval passphrase, the hardwired `.worktrees/`, the
per-language-runtime auto-setup. **It was dropped because it was judged unnecessary**, not
left undone.

Dropped from `shaping-the-work`: **the in-browser visual companion** (a separate server
process plus a set of templates). plumb already has `plumb:decision-brief` (a compact table, or a
standalone HTML brief for a complex comparison, plus a question with matching labels) and `playbooks/prototype.md`, so a second mechanism for
showing things is not needed. **The templates for having another role read the spec / plan**:
`playbooks/being-reviewed.md` is the source of truth for how to ask, `docs/role-map.md` for
who to ask. **The process diagram** and **the opening speech** went too.

## No bun (decision withdrawn on 2026-08-29)

Batch 0 decided to bring in bun on the premise that pstack's TypeScript assets would be
ported. **That premise is gone, so the decision is withdrawn.** Here is the measured
breakdown.

| Asset | Lines | Who it is for |
|---|---|---|
| `scripts/orch/` | 2,819 | `orchestrate`. **A playbook decided against porting** (*2026-11-23: gone upstream*) |
| `scripts/watch-pr/` | 3,392 | `babysit`'s queue watcher. **Unnecessary once `gh stack merge` is atomic.** *2026-11-23: the TypeScript watcher stays out; `plumb-pr-watch` is plumb's own single read, in Python* |
| `scripts/check-plan.mjs` | 186 | `multi-phase-plan`. **A playbook decided against porting** |
| `scripts/worktree-audit.sh` | 86 | `worktree-cleanup`. **A ported playbook** |
| `show-me-your-work/scripts/log.sh` | 40 | The decision log. `hillclimb` requires it |

**All ~6,400 lines of TypeScript served playbooks this document had already decided not to
port.** What is alive is 2 shell files, 126 lines, and both run under bash. **No reason is
left to install a runtime nobody uses.** *(Still true on 2026-11-23: plumb's new commands are
Python and shell.)*

Both were rewritten and put in `scripts/`. `worktree-audit.sh` stopped hardwiring the default
branch, had its transcript path fitted to this environment, and now **excludes ignored files
that can be regenerated** — without that it says "go check" on every run, and a real `.env`
gets lost among 34 `__pycache__` directories.

## Read again at 0.15.46 (2026-11-23)

**The upstream was read a second time on 2026-11-23, at the commit `NOTICE` records (version
0.15.46).** The first reading covered playbooks and principles only. This one also took the
skills, the agents, the guide pages and the automations, and plumb then took a number of things
(`CHANGELOG.md` 0.31.0). The text was read for what failure each item exists to prevent and then
closed; what plumb carries is written in its own words, so the claim in `NOTICE` that nothing is
reproduced verbatim keeps holding.

### What changed upstream since the first reading

- **The playbook directory now holds 22 files** (it held 23). `orchestrate` and its scripts are gone;
  `autopilot-full` and `autopilot-stack` are there.
- **There are 24 principles, three of them new**: `attack-the-premise`, `explain-the-number` and
  `test-behavior-not-implementation`.
- **The skills, the agents, the guide pages and the automations had no record in this document at
  all.** The first reading never opened them, so nothing here said whether they were left out or
  simply not looked at. The tables below are that record.

`plumb-upstream-diff --unrecorded` lists the upstream names this document does not mention. After
this section it lists none.

### Decisions

**Principles.** Every principle name is recorded here, so the command stops listing it. The
rewrite of 2026-08-31 already covers all of them except the new three.

| Upstream | Decision | Where in plumb, or why not |
|---|---|---|
| `explain-the-number`, `attack-the-premise` | ported | `principles/explain-the-number.md`, `principles/attack-the-premise.md`, rewritten as every principle is. `playbooks/perf-issue.md`, `playbooks/hillclimb.md` and `playbooks/fixing-a-bug.md` name them where they apply |
| `test-behavior-not-implementation` | folded into `playbooks/writing-tests.md` | Its named worthless-test shapes already carried it; three lines were added rather than a principle that would repeat the playbook |
| every other principle: `boundary-discipline`, `build-the-lever`, `encode-lessons-in-structure`, `exhaust-the-design-space`, `experience-first`, `fix-root-causes`, `foundational-thinking`, `guard-the-context-window`, `laziness-protocol`, `make-operations-idempotent`, `migrate-callers-then-delete-legacy-apis`, `minimize-reader-load`, `model-the-domain`, `never-block-on-the-human`, `outcome-oriented-execution`, `redesign-from-first-principles`, `separate-before-serializing-shared-state`, `sequence-verifiable-units`, `subtract-before-you-add` | already recorded | Ported by the principle rewrite above (`principles/`, one file each, same names) |

**Skills.**

| Upstream | Decision | Where in plumb, or why not |
|---|---|---|
| `benchmark-checklist` | folded into `principles/explain-the-number.md` and two playbooks | The seven questions about a measured number live in the principle; `playbooks/perf-issue.md` and `playbooks/hillclimb.md` apply them |
| `blast-radius` | folded into `principles/gate-claims-on-evidence.md` and `playbooks/opening-a-pr.md` | A safety claim carries a rung (said, pointed, walked, ran, reproduced); the pull-request body asks Blast Radius for the one fact that makes the change safe |
| `show-me-your-work` | folded into `plumb-decision-log --start/--audit` and the playbooks that use it | A run boundary, and a machine check that every cited commit, pull request and file exists. The "Attention" section a different family writes at the end of a long run's report is in `playbooks/autonomous-run.md` |
| `create-verification-skill`, `maintain-verification-skill` | ported as `skills/verify-init` and the map-keeping pass in `skills/verify` | Bound to the project contract (the `[verify]` table and the feature map) instead of a per-app skill, so there is one source of truth for how a repository is verified |
| `ketchup` | ported as `skills/catch-up` | What changed, and each waiting decision in a form one reply settles |
| `recall` | ported as `skills/recall` | One topic across sessions, each thread tagged from a checked fact |
| `reflect` | ported as `skills/reflect` | At most five changes from one session, routed to the layer that owns them, applied only after approval |
| `poteto-help` | ported as `skills/help` | Answers and hands back the prompt; never starts the work |
| `setup-pstack` | ported as `skills/configure` (roles and drivers) | **The effort-budget part is not taken**: effort is a per-call setting by role (`docs/role-map.md`, "Where effort goes up"), and a stored budget would be a second source for it |
| `correct` | folded | Optional `expires` and `approved_by` columns on code-policy exceptions (`docs/project-contract.md`); history mining in `skills/retro`. The table that maps each rule to its enforcing mechanism is `docs/enforcement.tsv`, read by `plumb-enforcement` (*2026-11-24: this row said "not taken yet" until that table landed*) |
| `arena` | folded into `playbooks/prototype.md` | Racing one brief across model families, a judge from another family, and grafting |
| `swarm` | folded into `playbooks/fan-out.md` | Every result carries the SHA and the method it was measured with; a result without them is discarded and run once more; a gap is not a pass |
| `figure-it-out` | ported as `playbooks/designing-a-run.md` | Work no playbook fits: a predicate a command decides, the verifier and its baseline before the work |
| `create-formal-verification-skill`, `maintain-formal-verification-skill` | folded into `playbooks/properties-tests-cannot-reach.md` | The discipline (one promise, a mutation seen to fail, a coverage record). **No toolchain** |
| `statechart` | not taken | A toolchain and runtime plumb does not carry |
| `why`, `how`, `in-your-own-words`, `sharpen` | folded as lines in `playbooks/investigation.md` and `playbooks/fixing-a-bug.md` | Answer "why" from the record and say what the record does not answer; restate a long or vague report in your own words before reading code. **The four sharpening questions as a separate skill are not taken** |
| `tdd` | folded into `playbooks/fixing-a-bug.md` | The failing repro is committed before the fix; no test beats a bad test |
| `no-comments` | not taken as a skill | `plumb-code-policy` reports the comments and effect hooks a branch adds, and `docs/project-contract.md` says how to clear one: encode the constraint, then delete the comment |
| `unslop`, `technical-writing` | not taken yet | `plumb-check-pr-body` covers only the mechanical part of a pull request body (sections, order, length, fenced blocks) |
| `interrogate` | already `plumb:interrogate` | It exists as an axis of the pull-request review; the standalone form is not taken |
| `architect` | not taken | plumb has `playbooks/shaping-the-work.md` and the principles; a second entry point would split the source of truth |
| `reframe` | folded into `playbooks/shaping-the-work.md` (*added upstream in 0.15.48, 2026-11-24*) | When a description could name more than one problem: the candidates, the name practitioners use for each, the sign that separates them, and a source cited only after it was opened. **Not taken as a skill**, for the reason given for `architect` and `sharpen` |
| `teach`, `bro`, `automate-me`, `ketchup-video`, `make-bot-ui`, `typescript-best-practices` | not taken | Personal style, another product's features, or one language; plumb is language-neutral |
| `poteto-mode` | the router itself (root `SKILL.md`) | Its worker file became `docs/worker-rules.md`, delivered by the Agent hook when `worker.rules.types` is set |

**Agents.**

| Upstream | Decision | Where in plumb, or why not |
|---|---|---|
| `poteto-agent` | not taken | plumb delegates through role keys in `docs/role-map.md`, not through a named agent |
| `comment-sicko` | not taken as an agent | A reviewer that only hunts comments is a rule, and `plumb-code-policy` is where plumb keeps rules (see `no-comments` above) |

**Playbooks that were already in the first reading.**

| Upstream | Decision | Where in plumb, or why not |
|---|---|---|
| `autopilot-full`, `autopilot-stack` | not ported as playbooks | Taken from them: stale-lane detection (`plumb-lane stale`); re-verification by the kind of change and the reach check in `playbooks/landing-a-stack.md`; in `skills/lead`, the countersign for loosening a gate and a conditional merge. **The merge is allowed only below the production branch named by `repo.production_branches`; the production branch stays the owner's** |
| `babysit`'s watcher | `plumb-pr-watch` | plumb's own single read with an exit code; this revises the "no watcher" decision recorded above |
| `eval` | blinding by machine | Lines in `playbooks/evaluating-an-agent.md` (see the note on that row above) |
| `multi-phase-plan` | folded | The per-pull-request unit, live and perf boxes in `playbooks/writing-a-plan.md` |
| `visual-parity` | still not taken | The reasons recorded above still hold |

**Guide pages.** Not ported page by page. `docs/guide/` is plumb's own five pages for the person
working with plumb (a first hour, how to ask, recipes, overnight runs, pitfalls). The upstream
pages, in one line so the command stops listing them: `01-setup`, `02-poteto-mode`, `03-understand`,
`04-design`, `05-build-and-clean`, `06-verify-and-ship`, `07-overnight`, `08-principles`,
`09-make-it-yours`, `10-recipes-and-pitfalls`.

**Automations.** The pack of chat-triggered triage and repair is **not taken**. It depends on another
product's automation service and posts outside the machine. One idea is kept: an existing fix is
verified, not rebuilt (`skills/lead`: an item that already has a fix is reproduced on the baseline
and on the fix, and no competing pull request is opened).

### Still decided against

- **Principles as skills.** The incident of 2026-08-29 still decides this: stopping a principle with
  a flag sealed the path that opens it, and the router index is the only way in (root `SKILL.md`,
  "Principles are not skills").
- **A merge into the production branch by an agent.** A merge cannot be taken back, so the production
  branch stays the owner's whatever evidence an agent holds. Merging below it needs
  `repo.production_branches` in the base branch's contract.
- **A fixed cheapest-first order for performance levers.** plumb's families of levers
  (`playbooks/perf-issue.md`) are sources of hypotheses, not a checklist, and elimination beats the
  others whenever it applies.
- **Always replacing the worker on a fix round.** The recorded choice is the ceiling in
  `playbooks/running-a-plan.md`: rounds 1-2 the same role, round 3 a different role, then stop.
- **Cheaper models for verification.** Verification is a `high` row in `docs/role-map.md`, and
  lowering it lets verification slip. Compare by ledger before changing it.
- **bun and TypeScript tooling.** Unchanged from "No bun" above: plumb's commands are Python and
  shell, and a runtime nobody else uses is not worth installing.

## When to revisit this

- If `gh` grows a stack watcher, the CI-classification section of `landing-a-stack` can lean
  on the machine
- If the scale being run passes "does not finish in one session", the brief template and the
  liveness section of `orchestrate` are worth coming back for — those two sections only, not
  the ritual (*2026-11-23: `orchestrate` is gone upstream; the stale-lane check and the brief
  commands in cockpit mode now cover those two sections*)

## Cockpit mode

Cockpit draws three ideas from pstack (MIT, Lauren Tan). Each lane starts with a shared
`worker.md`, per-role model lines become personal launch-command keys, and Attack the Premise
becomes a hold when two attempts on the same work report the same cause.

The upstream worker prose, model assignments, launch machinery, and orchestration playbooks
remain outside cockpit. The commands implement routing and acceptance from plumb's own event log.
