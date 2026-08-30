# plumb

A harness for Claude Code that makes discipline *namable*: every principle has a
name you can call it by, judgment is routed to a different model family than the
one that wrote the code, and **skipping is allowed but never silent** — a skipped
step leaves a `skip: <reason>` line you cannot delete.

## What it adds

plumb sits next to [superpowers](https://github.com/obra/superpowers), not on top
of it. superpowers owns the innermost loop of a single unit of work — debugging,
TDD, task-by-task execution. plumb owns what surrounds it, and since 2026-08-30
the shaping and planning steps too, written in plumb's own vocabulary:

- **Visible skip.** A non-trivial task must open a todo line for the judgment
  pass. That line closes one of two ways: it runs, or it carries an explicit
  `skip: <reason>`. It cannot be deleted. A todo list with no judgment line is
  itself the evidence the discipline was dropped — which makes the omission
  reviewable instead of invisible.
- **Judgment in another family.** The model that wrote the code is the worst
  reviewer of it: it shares the blind spots that produced the bug. plumb routes
  the adversarial pass to a different model family and treats a same-family-only
  verdict as unreviewed.
- **A principle index you call by name.** Twenty-one principles, each with a
  name. Citing one obliges you to name the specific decision it changed — a
  quotation with no decision attached is treated as proof the leaf was never
  read. Naming turns "be careful" into something a reviewer can check.
- **A harness that checks its own claims.** Documentation rots silently: a
  playbook names a script that was since renamed, the router indexes a principle
  that was deleted, an agent definition points at a skill that moved.
  `scripts/check-harness.sh` fails on the first two; `scripts/doctor.sh` catches
  the third and checks the outer edge besides — whether the tools and skills the
  docs name still exist on this machine. Both have caught real breakage, including
  a frontmatter flag that had made the entire harness unreachable from the model.

## What's bundled

Beyond the router and the 21 principles, plumb ships these skills (all called under
the `plumb:` namespace) and their supporting agents:

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

## Install

    /plugin marketplace add Haruki1090/plumb
    /plugin install plumb@plumb

From a shell instead:

    claude plugin marketplace add Haruki1090/plumb
    claude plugin install plumb@plumb

plumb also requires the [superpowers](https://github.com/obra/superpowers)
plugin. plumb's router forwards bug-fixing and task-by-task plan execution to
superpowers rather than reimplementing them; without it, `scripts/doctor.sh`
reports `NG`.

## Configuration

plumb works with nothing configured. Unset roles fall back to the main session,
which says so instead of pretending the pass happened.

To route a role elsewhere, write `~/.claude/plumb/config`:

    role.judge   = <command>   # adversarial pass, ideally another model family
    role.bulk    = <command>   # mechanical fan-out
    pane.driver  = <command>   # terminal multiplexer for long-running work
    stack.tool   = gh-stack    # stacked-PR tooling

Run `plumb-doctor` from a shell to see what is wired and what is unset (installing the
plugin puts it on your PATH). Unset reads `--`, never `NG` — plumb does not report a
tool you chose not to install as breakage. From inside Claude Code, the `doctor` skill
covers the same ground.

## Language

SKILL.md, the 13 playbooks, and the docs/ files are written in Japanese. The 21
files under principles/ are verbatim English, carried over from pstack (see
NOTICE).

## Credits

Derived from pstack by Lauren Tan. See NOTICE and docs/scope.md.

## License

MIT
