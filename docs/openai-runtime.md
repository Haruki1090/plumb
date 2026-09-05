# Codex runtime adapter

This is a sidecar, not a rewrite. `SKILL.md`, `playbooks/`, `principles/`, and `agents/*.md` remain the
Claude-first source of truth. Apply this document only when those files name a Claude-specific execution
surface.

## Start profile

The shipped `.codex/config.toml` is both this repository's project configuration and the source for the
optional user profile installed as `~/.codex/plumb.config.toml` (or `$CODEX_HOME/plumb.config.toml`).
The marketplace plugin works without this profile. After installing the plugin, invoke `$plumb:setup`
from a new Codex session to install the profile and native custom agents without locating the plugin
cache. Then start Codex with:

```bash
codex --profile plumb
```

The main thread uses `gpt-5.6-sol` at high reasoning. The default subagent uses `gpt-5.6-luna` at medium
reasoning, with four spawned threads allowed at once. Named agents override those defaults where their
job needs more or less depth.

## Role mapping

| Claude-first term | Codex execution |
|---|---|
| Main session | The current Sol-led Codex thread |
| Explorer `Task` | `plumb_explorer` |
| Implementer `Task` | `plumb_worker` |
| `role.bulk` when unset | `plumb_bulk`, only after the fan-out independence test passes |
| Same-family verification | `plumb_judge` |
| `role.judge` | The command configured by `plumb-config role.judge`; see the family rule below |
| Several `Agent` calls | Spawn the named agents together, then wait for every required result |
| `AskUserQuestion` | Use the runtime's structured user-input tool when available; otherwise ask one concise question |
| Agent `SendMessage` instruction | Ignore it. A Codex subagent returns its final response to the parent automatically |
| `Workflow` parallel/pipeline | Explicit spawn, wait/barrier, and follow-up calls using the graph's node contracts |

Custom agent files live in `.codex/agents/`. `$plumb:setup` resolves the installed plugin root and runs
`bin/plumb-codex-install --user`; direct installer invocation remains available to repository
maintainers. If a named custom agent is unavailable, spawn a generic subagent with the same model and
reasoning setting from that file, and include the bounded role instructions in the task. Do not silently
collapse independent implementation and verification into one thread.

## PR-review agent mapping

| Canonical definition | Codex custom agent |
|---|---|
| `agents/pr-diff-reader.md` | `plumb_pr_diff_reader` |
| `agents/pr-invariant.md` | `plumb_pr_invariant` |
| `agents/pr-cutover.md` | `plumb_pr_cutover` |
| `agents/pr-repro.md` | `plumb_pr_repro` |
| `agents/pr-refuter.md` | `plumb_pr_refuter` |
| `agents/pr-blindspot.md` | `plumb_pr_blindspot` |

The Markdown definitions remain canonical for the role's questions and output shape. The TOML agents
translate those roles into native Codex model, reasoning, sandbox, and return-value semantics.

Before starting `plumb_pr_repro`, the parent creates an isolated git worktree and gives the agent its
absolute path. The agent must restrict edits to that path. A shared working directory is not isolation.

## Model-family rule

Sol and Luna are execution tiers in the same GPT-5.6 family. A `plumb_judge` or Luna refuter is useful
independent verification, but it does **not** close the harness's different-family judge line.

For the different-family pass:

1. Read `plumb-config role.judge ""`.
2. If it resolves to a genuinely different-family command, run that bounded review and record it.
3. Otherwise leave the required todo line as `skip: role.judge unset or not a different model family`.

Never describe a Sol/Luna split as cross-family review.

## Command lookup

Codex plugins do not promise to put a plugin's `bin/` directory on `PATH`. Resolve the plugin root from
the loaded skill path and execute commands from `<plugin-root>/bin/`. A user installation may also expose
the wrappers on `PATH`, but the workflow must not depend on that convenience.

## Environment diagnostics and measurement

Run `PLUMB_RUNTIME=codex <plugin-root>/bin/plumb-doctor` for this runtime. Doctor also detects
`CODEX_THREAD_ID`; a plain shell defaults to Claude for compatibility. Codex diagnostics check the
enabled plugin from `codex plugin list --json` and do not require Claude's directories or plugin
installation. Missing diagnostic tools produce explicit skips, not proof of successful loading.
Use `bin/plumb-codex-install --check` separately to verify the optional user profile and agents.

Role and pane routing still use `PLUMB_CONFIG`, defaulting to `~/.claude/plumb/config` for compatibility.
The file is plain configuration and does not require a Claude installation. Codex-only users can point
`PLUMB_CONFIG` at a file of their choosing. There is no automatic second routing config to drift.

Use `<plugin-root>/bin/plumb-session-audit --runtime codex --transcripts <scoped-directory> --all --json`
for a dedicated review directory, or select one file with `--session <filename-without-jsonl>`.
Do not point `--all` at a date directory containing unrelated sessions. Gather only the transcripts
for the review being measured, including its participants; the tool does not discover teammates.
Keep each original export only once: duplicate detection uses `session_meta.id` when present and
otherwise the filename. Renamed copies without metadata cannot be identified as the same session.

The adapter reads cumulative `event_msg/token_count` snapshots and ignores duplicate per-response
records. It rejects resets, missing snapshots, and unobserved prefixes rather than undercounting.
Native input includes cached tokens; normalization separates uncached input, cache reads and cache
writes, and does not add reasoning tokens a second time. Missing cache-write information makes those
cost categories unavailable. Cache TTL and idle rebuild metrics remain unavailable in this format.
This adapter supports consistent snapshots, not every native session: a captured stream also emitted
nonzero `total_tokens` with every category zero. Such sessions fail explicitly (exit 2); do not remove
that event or substitute a zero cost to make an evaluation pass. Its runtime semantics remain unresolved.
The default audit mode remains Claude. See `skills/pr-review/references/bench-format.md` for scoring.

## Delegation discipline

- Delegate only when the user explicitly asks for agents or when the active plumb playbook calls for a
  role. Loading plumb is not permission for unrelated fan-out.
- Keep requirements, decisions, and final integration in the main Sol thread.
- Give each subagent a bounded input, writable-file ownership, output contract, and stopping condition.
- When the spawn interface exposes history inheritance, use `fork_turns="none"` for an independent
  bounded role and supply the contract plus absolute evidence/spec paths. Fork history only when the
  role needs conversation-only decisions that cannot be supplied as a compact contract; record why.
  A cheaper role carrying the controller's full history does not make the handoff cheap.
- Use Luna low/medium for extraction, exploration, and repetitive work. Use Luna max only for bounded
  adversarial judgment or refutation. Use Sol high for ambiguous implementation, invariants, cutover
  reasoning, and final integration.
- Do not run parallel writers against the same files. Put shared-state changes before the fan-out or run
  them serially.
- Wait for all required lanes, then integrate their structured summaries. Do not paste their raw logs
  into the main context.
