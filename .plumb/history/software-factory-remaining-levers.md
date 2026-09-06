> **This is history. Do not execute it.**
> The current source of truth is `.plumb/specs/software-factory-remaining-levers.md`. **If this document disagrees with it, the source of
> truth wins.** Do not sync this back up — syncing it revives the second source of truth.

# Plan: Software Factory remaining levers

Spec: `.plumb/specs/software-factory-remaining-levers.md`. Executed in order by the main session,
one commit per task. **Disposable: stale the moment execution starts.**

Global constraints (copied from the spec and the harness): body text never names a model slug
(`scripts/check-harness.sh` rule 1) or a routing target (rule 10); every `plumb-*` name in body
text must exist in `bin/` (rule 11); agent frontmatter never pins `model:` (rule 12); the README's
"N playbooks / N principles" digits must match (rule 14). Scripts are python3 or bash, no
dependencies. Verify with `bash scripts/check-harness.sh && bash scripts/selftest.sh` → both `→ passed`.

## Task 1 — A. effort default

Edit `~/.claude/settings.json`: `effortLevel` → `"medium"`, `modelSettings.claude-fable-5-1.effortLevel` → `"medium"`.
Edit `docs/role-map.md`: add section "## Where effort goes up" holding the table now at
`skills/graph/references/execution.md:93-98`. Replace that table with one line pointing at the
section. `skills/pr-review/SKILL.md:153` keeps its sentence and adds the pointer.
Check: `bash scripts/check-harness.sh` → `ok`.

## Task 2 — B1. FIRST-REQUEST-OVER

`scripts/session-audit.py`: `--first-threshold` (int, default 50000); in `read_session` append
`"FIRST-REQUEST-OVER"` when `first_context > args.first_threshold`; in `summarize` add
`"FIRST-REQUEST-OVER": {"sessions": ...}` and `"first_tokens": args.first_threshold` under
`thresholds`; in `print_text` add the flag line after `IDLE-REBUILD`.
`scripts/selftest.sh`: pass `--first-threshold 60` to the fixture runs; expect
`counts == {"CTX-P90-OVER": 1, "TOOL-RESULT-OVER": 1, "IDLE-REBUILD": 1, "FIRST-REQUEST-OVER": 1}`
and `sessions["clean-session"]["flags"] == ["FIRST-REQUEST-OVER"]` (its first request is 61).
`docs/scope.md`: add the flag to the audit sentence.

## Task 3 — B2. plumb-prompt-weight

Create `scripts/prompt-weight.py` (argparse: `--home`, `--project`, `--json`) and
`bin/plumb-prompt-weight` (same wrapper shape as `bin/plumb-session-audit`).
Components, each `{"component": str, "path": str, "bytes": int, "tokens_est": int, "note": str}`:
`<home>/.claude/CLAUDE.md`, `<project>/CLAUDE.md`, `<project>/.claude/CLAUDE.md`,
`<home>/.claude/projects/<slug>/memory/MEMORY.md` (slug: every non-alphanumeric byte of the
absolute project path → `-`), `settings.json` SessionStart hook commands (bytes of the command
strings, note "not executed"), per enabled plugin (`settings.enabledPlugins` true →
`installed_plugins.json` first entry `installPath`): skill `description:` frontmatter bytes summed
over `skills/*/SKILL.md`, agent `description:` bytes over `agents/*.md`, `hooks/hooks.json`
SessionStart presence, `.mcp.json` server count; user skills `<home>/.claude/skills/*/SKILL.md`
descriptions; `<home>/.claude.json` `mcpServers` names (global and for `<project>`).
`tokens_est = ascii_bytes / 4 + non_ascii_bytes / 3`, rounded. Text output: table sorted by bytes
desc, then `total`, then the line `estimate: tokens are byte-derived; the runtime's own prompt and tool schemas are not visible here`.
Self-test: synthetic `--home` with a CLAUDE.md, one enabled plugin carrying one skill and a
SessionStart hook, one disabled plugin; assert the disabled plugin is absent, the hook row says
`not executed`, and `--json` `total.bytes` equals the sum of rows.

## Task 4 — C. plumb-statusline-cost

Create `scripts/statusline-cost.py` and `bin/plumb-statusline-cost`. Read stdin JSON;
`usd = data["cost"]["total_cost_usd"]` (absent → print nothing, exit 0). Config through
`scripts/plumb-config.sh` (resolve relative to the script): `cost.jpy_per_usd`,
`cost.session_budget_usd`. Output `$%.2f`, then ` ¥%d` when the rate is set, then ` %d%%` when the
budget is set, wrapped in ANSI: <50 % plain, 50–79 `33` (yellow), 80–99 `35` (magenta), ≥100 `1;31`.
Self-test: `printf '{"cost":{"total_cost_usd":1.5}}' | plumb-statusline-cost` → `$1.50`; with
`PLUMB_CONFIG` carrying `cost.jpy_per_usd = 150` → contains `¥225`; with
`cost.session_budget_usd = 2` → contains `75%` and `\033[33m`; `{}` → empty, exit 0.
Owner's `~/.claude/settings.json` statusLine: append the segment via the absolute bin path.
Add the two keys to the header comment of `scripts/plumb-config.sh`.

## Task 5 — D. role.explorer.model

`scripts/plumb-config.sh` header: add `role.explorer.model = <model>` with the note that it is
the one key whose value is a model name, and that it lives in config so no document carries it.
`docs/role-map.md` Explorer row: `role.explorer.model` (unset: inherits the main session's model).
`SKILL.md` Explorer row: same wording. `skills/pr-review/SKILL.md:96`: pass `model` from
`plumb-config role.explorer.model` when it resolves. `scripts/selftest.sh`: add
`role.explorer.model = tier-x` to the config fixture and assert the lookup.
Bench lap (not run here): with the owner's private bench launcher (outside this repository), `RUN=explorer-light` with the
key set, over the 12-item corpus, compared on tokens/review and requests per review against
`clean-pass-3`; F1 must not regress beyond the noise floor (`bench-score` gate).

## Task 6 — CHANGELOG, verification, judge

`CHANGELOG.md`: `## [Unreleased]` with the four levers. Run `bash scripts/check-harness.sh` and
`bash scripts/selftest.sh` in a Herdr pane, tee to the scratchpad, read the file. Judge role:
`role.judge` is configured; propose the review to the owner, do not launch it.
