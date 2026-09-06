# Software Factory remaining levers

Source: Uber Engineering, "Running a Software Factory Efficiently at Uber Scale" (2026-08).
Decision: `.plumb/run/decisions.tsv` row `uber-software-factory-remaining-levers` (2026-09-06);
brief `.plumb/run/uber-software-factory-remaining-levers-2026-09-06.html`.

## End state

The four levers the article names that plumb did not yet carry are in place, each judged by a
term `plumb-session-audit` already prints or a segment the terminal shows live:

| Lever | What exists afterwards | Term it moves |
|---|---|---|
| A. Effort default | The owner's global effort default is medium; the one table saying where effort goes up lives in `docs/role-map.md` | Tokens/Request (output side; `thinking %`) |
| B. Prompt initialization | `FIRST-REQUEST-OVER` flag in the audit; `plumb-prompt-weight` lists the user-controlled parts of the fixed prompt with byte and token estimates | Tokens/Request (input side; `first request p50`) |
| C. Live cost | `plumb-statusline-cost` prints the session's running cost from the status-line JSON, with a budget-ratio colour at 50 / 80 / 100 % when a budget is configured | Visibility (feeds the decision to stop a turn) |
| D. Explorer tier | `role.explorer.model` config key; explorer-shaped roles pass it when set; the bench run that decides whether to keep it is written down, not run | Price/Token (sidechain) |

## Acceptance criteria

- A: `~/.claude/settings.json` carries `effortLevel: medium` and no per-model override above it;
  `docs/role-map.md` holds the effort table; `skills/graph/references/execution.md` and
  `skills/pr-review/SKILL.md` point at it instead of restating it.
- B1: `plumb-session-audit` accepts `--first-threshold` (default 50000), flags a session whose
  first main-chain request context exceeds it as `FIRST-REQUEST-OVER`, counts it in the summary,
  prints it in the flags block, and `--strict` fires on it. `scripts/selftest.sh` asserts it on
  the synthetic fixture.
- B2: `plumb-prompt-weight [--home DIR] [--project DIR] [--json]` prints one row per component
  (global and project CLAUDE.md, memory index, SessionStart hooks, each enabled plugin's skill and
  agent descriptions and its SessionStart hook, user skills, MCP server declarations) with bytes
  and an estimated token count, sorted descending, with a total. It never executes a hook and never
  prints file contents. It exits 0 on a home with none of these, printing an empty table. The
  self-test runs it on a synthetic home.
- C: `plumb-statusline-cost` reads the status-line JSON on stdin and prints `$<usd>`; adds
  `¥<jpy>` when `cost.jpy_per_usd` is configured; adds `<pct>%` coloured by band when
  `cost.session_budget_usd` is configured; prints nothing and exits 0 when the JSON carries no
  cost. The self-test covers all four. The owner's status line appends the segment.
- D: `plumb-config role.explorer.model` resolves the key; `docs/role-map.md` and `SKILL.md` name
  it for the explorer role; `skills/pr-review/SKILL.md` passes it to `pr-diff-reader`; no agent
  frontmatter pins a model (harness rule 12 holds). The bench command that would decide it is in
  the plan.
- `scripts/check-harness.sh` and `scripts/selftest.sh` exit 0.

## Chosen approach

Extend the existing scripts and config mechanism rather than adding a service: the audit gains a
flag, the config file gains keys, two small stdin/stdout commands ship in `bin/`. Cost stays an
estimate computed by the runtime (`cost.total_cost_usd`, list price) and the token counts in
`plumb-prompt-weight` are byte-derived estimates, labelled as such.

## Rejected

- Replacing the owner's whole status line with a plumb-shipped one: it carries personal segments
  (account, branch) that do not belong in the plugin. A segment command composes instead.
- Decomposing the first request from the transcript: the transcript carries one number for the
  whole request, so the split has to come from the files the runtime loads.
- Running the explorer-tier bench in this lap: it is a multi-hour pane job on a private corpus
  (the owner's private bench scripts, outside this repository); the plumbing lands now, the measurement is its own lap.
- Automated papercut recording and a context graph: recorded in the brief as deferred / out of scope.
