# Changelog

All notable changes to plumb are recorded here. Versions follow Semantic Versioning.

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
