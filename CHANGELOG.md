# Changelog

All notable changes to plumb are recorded here. Versions follow Semantic Versioning.

## [0.9.2] - 2026-09-07

### Fixed

- `plumb-statusline-cost` paints every part of its segment bright white. It emitted no colour at
  all below the 50 % band, so the dollar, yen and percentage figures inherited the status line's
  default foreground and rendered as dim grey the owner could not read. The 50 / 80 / 100 % band
  colours are unchanged and still take precedence.

## [0.9.1] - 2026-09-06

### Fixed

- `plumb-prompt-weight` now counts project-level skills (`<project>/.claude/skills/*/SKILL.md`
  descriptions) and the SessionStart hooks in the project's `settings.json` and
  `settings.local.json`. Found on a repository that carried a project-level copy of a plugin: the
  global listing had dropped to 23KB while that project still started at 57KB.

## [0.9.0] - 2026-09-06

### Added

- `FIRST-REQUEST-OVER`: session-audit flags a session whose first main-chain request exceeds
  `--first-threshold` (default 50,000 tokens), so the fixed prompt is a measured term.
- `plumb-prompt-weight`: lists the user-controlled parts of the fixed prompt (instruction files,
  memory index, session-start hooks, enabled plugins' skill and agent listings, user skills, MCP
  declarations) with bytes and a byte-derived token estimate. Never runs a hook or prints contents.
- `plumb-statusline-cost`: a status-line segment printing the runtime's running cost estimate,
  with yen and a 50 / 80 / 100 % budget band from `cost.jpy_per_usd` and `cost.session_budget_usd`.
- `role.explorer.model`: a config key that sets the explorer role's model; unset inherits.

### Changed

- The table saying where effort goes up lives in `docs/role-map.md`; the graph reference and the
  PR-review skill point at it instead of restating it.

## [0.8.0] - 2026-09-06

### Added

- Normalize Codex-side usage accounting: dedupe cumulative snapshots, avoid double-counting cache
  reads, and fail closed on counter resets or unknown formats.
- Add a scoped Codex audit mode that never scans transcripts outside the requested location.
- Add an explicit baseline/candidate acceptance gate to bench-score: block any precision, recall, or
  F1 regression (including per-grade) and require a measured token-cost improvement.
- Add negative-control end-to-end tests proving a cheap-but-worse candidate and an incomplete run
  cannot pass the gate.

## [0.7.1] - 2026-09-06

### Fixed

- Diagnose Codex-only installations without requiring Claude directories or plugin loading.
- Keep missing, failed, and unverified graph nodes visible; document dependent-phase barriers.
- Make decision briefs usable without an external artifact design or publishing service.
- Correct nearest-rank percentiles and reject unrecognized usage records in session auditing.
- Preserve unavailable token categories and display totals instead of reporting partial usage as zero
  or as a complete total.

### Documentation and verification

- Clarify grounded exploration, visible terminal execution, measurement scope, and runtime limits.
- Add negative regression fixtures and record the audit and independent review disposition.
- Preserve the Claude-first canonical corpus and the existing Codex model profile.

## [0.7.0] - 2026-09-04

### Added

- Additive Codex support while keeping Claude Code as the canonical runtime.
- A universal `.codex-plugin/plugin.json` manifest and a thin `$plumb:plumb-codex` entry skill.
- A Sol-led Codex profile with a four-subagent ceiling and role-specific Luna/Sol routing.
- Ten native Codex custom agents covering exploration, implementation, bulk work, judgment, and the
  six PR-review axes.
- An idempotent `plumb-codex-install` command for user-level or project-level configuration.
- Codex runtime, installation, model-family, and repository-maintenance documentation.

### Verification

- Extend the harness check to parse the Codex JSON/TOML surface and keep both plugin versions aligned.
- Extend the self-test to cover user/project installs, repeat installs, overwrite refusal, and forced
  restoration of configuration files managed by plumb.

### Compatibility

- Claude installation and routing remain unchanged.
- Sol and Luna are treated as tiers in one GPT-5.6 family; a Luna pass does not masquerade as plumb's
  genuinely different-family judge.

## [0.6.0] - 2026-08-30

- First English open-source release of the self-contained Claude Code harness.
- Added the complete playbook and principle corpus, adversarial PR review, evaluation tooling, and
  self-checking scripts.
