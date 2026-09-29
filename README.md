<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/plumb-banner-dark.png">
  <img alt="plumb — a handwritten wordmark with a plumb bob hanging from the letter l" src="assets/plumb-banner.png">
</picture>

# plumb

A Claude-first harness, with an additive Codex adapter, that makes discipline *namable*: every principle has a
name you can call it by, judgment is routed to a different model family than the
one that wrote the code, and **skipping is allowed but never silent** — a skipped
judgment pass leaves a visible `skip: <reason>` line.

## What it adds

plumb is self-contained: 24 playbooks covering the whole arc of a unit of work —
shaping it, planning it, running the plan task by task, fixing what breaks,
writing the tests, and landing the result. It depends on no other plugin.

- **Visible skip.** Non-trivial plumb work keeps one visible todo line for the
  judgment pass. That line closes one of two ways: the configured independent
  review runs, or the line carries an explicit `skip: <reason>`. A skip does not
  stop safe, authorized work, and it is never reported as independent
  verification — which makes the omission reviewable instead of invisible.
- **Judgment in another family.** The model that wrote the code is the worst
  reviewer of it: it shares the blind spots that produced the bug. plumb routes
  the adversarial pass to a different model family and treats a same-family-only
  verdict as unreviewed.
- **A principle index you call by name.** 23 principles, each with a
  name. A principle is read in full when its decision criterion applies, and
  cited alongside the specific decision it changed rather than narrated rule by
  rule. Naming turns "be careful" into something a reviewer can check. Each
  principle states *why it is hard to keep* — the mechanism that makes people
  and models break it — and how to tell afterwards whether it was kept.
- **A harness that checks its own claims.** Documentation rots silently: a
  playbook names a script that was since renamed, the router indexes a principle
  that was deleted, an agent definition points at a skill that moved.
  `scripts/check-harness.sh` fails on the first two; `scripts/doctor.sh` checks the
  documents and the outer edge besides — whether the tools and skills the docs name
  still exist on this machine. `plumb-session-audit` checks the sessions themselves.
  `plumb-prompt-weight` weighs the fixed prompt those sessions start with, and
  `plumb-statusline-cost` keeps the running cost in the status line.
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
- **`plumb:lead`** — runs a queue as the coordinator: takes "review the open PRs"
  or "implement the issues assigned to me", drops what already landed, gives each
  unit its own worktree and visible pane, and drives implement → independent
  review → local checks → ready PR. Stops at a ready PR; the owner merges.
- **`plumb:graph`** — pre-work execution-graph design for goals that are large,
  parallelizable, or need to stay aligned with a source-of-truth doc.
- **`plumb:decision-brief`** — hands a branching decision back to the owner as
  options compared on the same axes, with a recommendation: a compact table for
  a simple choice, a standalone HTML brief when the comparison is complex or
  visual, then one question using the same option labels — instead of a wall of
  prose.
- **`plumb:doctor`** — checks whether the environment plumb's docs claim (routed
  tools, bundled agents, paths, plugin loading) actually exists on this machine.

The `plumb-bench-extract` and `plumb-bench-score` commands build a pruned review corpus and compare
agent configurations by precision, recall, F1, and tokens per review.

## Install

### Claude Code (primary)

    /plugin marketplace add Haruki1090/plumb
    /plugin install plumb@plumb

From a shell instead:

    claude plugin marketplace add Haruki1090/plumb
    claude plugin install plumb@plumb

Nothing else is required. plumb has no plugin dependencies — beyond git and gh,
`scripts/doctor.sh` checks only the tools you chose to route roles to, and reports
`--` for the ones you left unset.

### Codex (sidecar)

Codex uses the same playbooks and principles. Install the plugin directly from its GitHub marketplace:

```bash
codex plugin marketplace add Haruki1090/plumb
codex plugin add plumb@plumb
```

These commands download and register the universal plugin; no clone or local path is required. Start a
new ordinary Codex session and invoke `$plumb:plumb-codex` to use it.

The bundled profile and native custom agents are an optional enhancement. In a new Codex session, invoke
`$plumb:setup`; it resolves the installed plugin automatically and adds only
`~/.codex/plumb.config.toml` and the `plumb-*` agents under `~/.codex/agents/`. It does not edit or
remove the Claude installation, and it refuses to overwrite differing files without explicit approval.
After setup, start the enhanced profile:

```bash
codex --profile plumb
```

For project-scoped configuration instead, ask `$plumb:setup` to install into the active project. Codex
loads project `.codex/` configuration only for trusted projects. See
[`docs/openai-runtime.md`](docs/openai-runtime.md) for the runtime mapping and model-family caveat.

The plugin-qualified `$plumb:plumb-codex` entrypoint reads the unchanged root router and then applies
the Codex execution adapter.

The included profile uses a high-reasoning Sol main thread, medium-reasoning Luna subagents by default,
and a concurrency cap of four. Named agents spend Luna `max` only on bounded judgment and refutation;
ambiguous implementation and integration stay on Sol. Sol and Luna are the same GPT-5.6 family, so this
does not pretend to satisfy plumb's genuinely different-family judge requirement.

## Claude configuration

plumb works with nothing configured. Unset roles fall back to the main session (the
implementer to a subagent), which says so instead of pretending the pass happened.

To route a role elsewhere, write `~/.claude/plumb/config`:

    role.judge   = <command>   # adversarial pass, ideally another model family
    role.bulk    = <command>   # mechanical fan-out
    role.implementer = <command>   # implementer started in a visible pane, e.g. a lighter model tier
    role.implementer.model = <model>  # the implementer's subagent fallback; unset inherits
    pane.driver  = <command>   # terminal multiplexer for long-running work
    stack.tool   = gh-stack    # stacked-PR tooling
    bench.corpus = <directory> # private evaluation corpus (see playbooks/evaluating-an-agent.md)

One `key = value` per line. A line starting with `#` is a comment, and so is
everything after whitespace followed by `#`. Wrap a value in double or single
quotes to keep a `#` or surrounding spaces; the quotes themselves are dropped. A
key with an empty value counts as unset. A role value may be a whole command line
(`role.judge = codex exec`); doctor checks only its first word against PATH.

Claude Code puts the plugin's `bin/` on PATH for its own Bash tool, not for your
login shell. Run `plumb-doctor` from Claude Code's Bash tool, or use the `doctor`
skill; from an ordinary terminal, call it by its path in the plugin cache,
`~/.claude/plugins/cache/plumb/plumb/<version>/bin/plumb-doctor`. It shows what is
wired and what is unset. Unset reads `--`, never `NG` — plumb does not report a
tool you chose not to install as breakage.

Specs, plans and run ledgers go under `<repo>/.plumb/` by default; `plumb-path
--help` lists the kinds and the `PLUMB_ROOT` / `.plumb/config` overrides (`root =`
follows the same format as above). Specs and plans are tracked and stay with the
checkout. `run/` is untracked, so from a linked worktree it resolves to the main
worktree's `.plumb/run` and outlives `git worktree remove`.

Codex model placement lives separately in [`.codex/config.toml`](.codex/config.toml). Keeping the two
configuration surfaces separate is intentional: Claude remains the primary harness, while Codex reuses
the shared behavior through a thin adapter.

For Codex diagnostics, run `PLUMB_RUNTIME=codex <plugin-root>/bin/plumb-doctor`; the loaded skill's path
identifies the plugin root. The runtime adapter documents routing configuration and the explicit
`--runtime codex` session-audit mode for scoped native transcripts.

## Language

plumb is written in English throughout — SKILL.md, the 24 playbooks, the 23
principles, the bundled skills and agents, the scripts and the docs/ files.

It was written in Japanese through v0.5.0 and rewritten in English for release.
The Japanese original is frozen at the tag `v0.5.0-ja` and is not maintained:

    git show v0.5.0-ja:playbooks/fixing-a-bug.md

## License

MIT
