# Path map

Every Cursor-dependent path in upstream pstack is replaced in plumb by the entry below.
Do not write `.cursor` in the body text. This table is the only source of truth.

| Upstream | plumb | Notes |
|---|---|---|
| `~/.cursor/rules/pstack-models.mdc` | Dropped | plumb has no model configuration file. It is absorbed into the role map (`role-map.md`) |
| `~/.cursor/projects/<slug>/agent-transcripts/<uuid>/<uuid>.jsonl` | `~/.claude/projects/<slug>/<uuid>.jsonl` | **Flat.** There is no intermediate `<uuid>/` directory |
| How the slug is built (drop the leading `/`) | **Every non-alphanumeric character becomes `-`** | `/`, `.` and `_` all count. `/Users/you/.herdr/x` → `-Users-you--herdr-x` (**the dot is what doubles the dash**). `lv_slide_gen` → `lv-slide-gen`. Measured on 2026-08-29 (all 88 entries held `[-A-Za-z0-9]` only). **Replace `/` alone and you miss every session whose path contains a dot** |
| The `agent-transcripts/` directory | `~/.claude/projects/<slug>/` | There is no dedicated directory; the `.jsonl` files sit directly under the slug |
| `.cursor/skills/` | `.claude/skills/` | Project-local skills |
| `~/.cursor/skills/` | `~/.claude/skills/` | User skills |
| `.cursor/skills/<handle>-mode/` `.cursor/skills/<handle>/<handle>-mode/SKILL.md` `.cursor/skills/**/*-mode/SKILL.md` `.cursor/skills/verify-<app>/` `.cursor/skills/verify-*/` | The matching path under `.claude/skills/` | Apply the same replacement rule to paths carrying wildcards and placeholders |
| `.cursor/settings.json` | `.claude/settings.json` | |
| `.cursor/worktrees/<repo>/...` | **Do not replace it. Read it out of `git worktree list`** | Upstream already argues that a hand-typed path misses things. The worktree roots in this environment run in more than one line, so writing a single replacement would be a lie. See "Watch out" below |
| `~/.cursor/plugins/` | `~/.claude/skills/` (where you put it by hand during development) | pstack lived under `~/.cursor/plugins/` as a plugin; put plumb under `~/.claude/skills/plumb/` by hand and that becomes the real location. **Install through the marketplace and the real location is `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` instead** |
| `~/.cursor/projects/*/` `HOME/.cursor/projects/` | `~/.claude/projects/*/` | The wildcard form of the slug listing path |
| `//api2.cursor.sh/automations/webhook/<id>` | Out of scope | Cursor's cloud webhook API. plumb does not have this feature |
| `.cursor/automations/benny/` and everything under it (`skills/`, `skills/triage-issue-reports/SKILL.md`, `skills/reproduce-and-fix-issues/SKILL.md`, `skills/setup-benny/SKILL.md`), `<target-repository>/.cursor/automations/benny/` | Out of scope | benny is not ported |
| `.cursor/benny/` and everything under it (`routing.md`, `feature-map.md`, `configuration.yaml`) | Out of scope | benny is not ported |
| `.cursor` (a bare mention, with no extension and no path component) | Out of scope | The single occurrence confirmed upstream is in `automations/benny/skills/setup-benny/SKILL.md` (under benny). benny is not ported, so this row needs no separate decision. Decide case by case only if a new occurrence turns up outside benny |

## Watch out

- An instruction to read "the transcript for the current workspace" must not glob
  `~/.claude/projects/*/`. That reads private chats from other projects. Pin the slug down
  first, then open it.
- `~/.claude/history.jsonl` is a different thing (the command history across every session).
  Do not confuse it with a transcript.
- **Do not assemble a worktree path by hand.** This machine has more than one root (measured
  2026-08-29): `~/.cursor/worktrees/<repo>/` (Cursor Agent), `~/.herdr/worktrees/<repo>/`
  (Herdr), `~/.codex/worktrees/<id>/` (Codex), and `.claude/worktrees/<name>/` inside the
  repository itself (Claude Code's `EnterWorktree`). **`~/.claude/worktrees/` does not
  exist** — Claude Code creates its worktrees inside the repository, not under the home
  directory. Hand-made roots such as `~/<anything>/<repo>-worktrees` are mixed in as well.
  Always enumerate them from `git worktree list`. The point upstream `worktree-cleanup.md`
  makes applies here unchanged.
- An additional fact from measurement (context, outside the scope of the table): when a
  session used subagents, an extra directory
  `~/.claude/projects/<slug>/<uuid>/subagents/agent-<id>.jsonl` can exist carrying the same
  name as the main `<uuid>.jsonl` (for example
  `3ae3dda1-633d-4bb1-9d0a-6b96dce014fe/subagents/`). The main session's transcript itself is
  flat as the table says (`<slug>/<uuid>.jsonl`), but a directory of the same name can sit
  beside it under the same slug. pstack's transcript reading targets the main session, so
  this does not affect the replacement rules; watch for the collision if you write anything
  that runs `find` or a glob under `<slug>/`.
