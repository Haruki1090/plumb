<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/plumb-banner-dark.png">
  <img alt="plumb — a handwritten wordmark with a plumb bob hanging from the letter l" src="assets/plumb-banner.png">
</picture>

# plumb

A harness for Claude Code that makes discipline *namable*: every principle has a
name you can call it by, judgment is routed to a different model family than the
one that wrote the code, and **skipping is allowed but never silent** — a skipped
step leaves a `skip: <reason>` line you cannot delete.

## What it adds

plumb is self-contained: 24 playbooks covering the whole arc of a unit of work —
shaping it, planning it, running the plan task by task, fixing what breaks,
writing the tests, and landing the result. It depends on no other plugin.

- **Visible skip.** A non-trivial task must open a todo line for the judgment
  pass. That line closes one of two ways: it runs, or it carries an explicit
  `skip: <reason>`. It cannot be deleted. A todo list with no judgment line is
  itself the evidence the discipline was dropped — which makes the omission
  reviewable instead of invisible.
- **Judgment in another family.** The model that wrote the code is the worst
  reviewer of it: it shares the blind spots that produced the bug. plumb routes
  the adversarial pass to a different model family and treats a same-family-only
  verdict as unreviewed.
- **A principle index you call by name.** 23 principles, each with a
  name. Citing one obliges you to name the specific decision it changed — a
  quotation with no decision attached is treated as proof the leaf was never
  read. Naming turns "be careful" into something a reviewer can check. Each
  principle states *why it is hard to keep* — the mechanism that makes people
  and models break it — and how to tell afterwards whether it was kept.
- **A harness that checks its own claims.** Documentation rots silently: a
  playbook names a script that was since renamed, the router indexes a principle
  that was deleted, an agent definition points at a skill that moved.
  `scripts/check-harness.sh` fails on the first two; `scripts/doctor.sh` checks the
  documents and the outer edge besides — whether the tools and skills the docs name
  still exist on this machine. `plumb-session-audit` checks the sessions themselves.
  The harness has caught real breakage, including a frontmatter flag that had made
  it unreachable from the model.

## What's bundled

Beyond the router, the 24 playbooks and the 23 principles, plumb ships these skills
(all called under the `plumb:` namespace) and their supporting agents:

- **`plumb:pr-review`** — adversarial PR review: cross-checks the PR body against
  the diff, runs bidirectional inventory, and returns confidence × blocking
  separately. Backed by six agents: `pr-diff-reader`, `pr-invariant`, `pr-cutover`,
  `pr-repro`, `pr-refuter`, `pr-blindspot`.
- **`plumb:interrogate`** — adds one adversarial pass in a different model family
  to `plumb:pr-review`'s stage 3. Does not stand on its own.
- **`plumb:graph`** — pre-work execution-graph design for goals that are large,
  parallelizable, or need to stay aligned with a source-of-truth doc.
- **`plumb:decision-brief`** — turns a branching decision into a one-page HTML
  comparison plus an `AskUserQuestion` call with matching labels, instead of a
  wall of prose.
- **`plumb:doctor`** — checks whether the environment plumb's docs claim (routed
  tools, bundled agents, dependency plugins) actually exists on this machine.

The `plumb-bench-extract` and `plumb-bench-score` commands build a pruned review corpus and compare
agent configurations by precision, recall, F1, and tokens per review.

## Install

    /plugin marketplace add Haruki1090/plumb
    /plugin install plumb@plumb

From a shell instead:

    claude plugin marketplace add Haruki1090/plumb
    claude plugin install plumb@plumb

Nothing else is required. plumb has no plugin dependencies — `scripts/doctor.sh`
checks only the tools you chose to route roles to, and reports `--` for the ones
you left unset.

## Configuration

plumb works with nothing configured. Unset roles fall back to the main session,
which says so instead of pretending the pass happened.

To route a role elsewhere, write `~/.claude/plumb/config`:

    role.judge   = <command>   # adversarial pass, ideally another model family
    role.bulk    = <command>   # mechanical fan-out
    pane.driver  = <command>   # terminal multiplexer for long-running work
    stack.tool   = gh-stack    # stacked-PR tooling
    bench.corpus = <directory> # private evaluation corpus (see playbooks/evaluating-an-agent.md)

Run `plumb-doctor` from a shell to see what is wired and what is unset (installing the
plugin puts it on your PATH). Unset reads `--`, never `NG` — plumb does not report a
tool you chose not to install as breakage. From inside Claude Code, the `doctor` skill
covers the same ground.

## Language

plumb is written in English throughout — SKILL.md, the 24 playbooks, the 23
principles, the bundled skills and agents, the scripts and the docs/ files.

It was written in Japanese through v0.5.0 and rewritten in English for release.
The Japanese original is frozen at the tag `v0.5.0-ja` and is not maintained:

    git show v0.5.0-ja:playbooks/fixing-a-bug.md

## Credits

plumb began as a port of pstack by Lauren Tan, which is where its shape came
from — the router, principles as plain documents, and most of the principle
names. No text is carried over verbatim any more. See NOTICE and docs/scope.md.

## License

MIT
