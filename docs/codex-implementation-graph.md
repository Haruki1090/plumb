# Graph definition: Codex sidecar for plumb

## End state

The Claude Code plugin remains the canonical harness and keeps its existing behavior. A Codex user can
install the same repository, start a Sol-led profile, and delegate bounded work to native custom agents
whose model and reasoning levels are explicit. The repository checks both plugin manifests and the Codex
sidecar without requiring a live model call.

## Why this is a graph

Signals 1, 3, 4, and 5 apply: packaging, runtime adaptation, model placement, and independent validation
are different kinds of work; Claude and Codex use different configuration surfaces; the routing must be
auditable; and the harness must not approve its own unsupported claims.

## Nodes

| ID | Responsibility | Input | Output | Files touched |
|---|---|---|---|---|
| N1 | Freeze the compatibility boundary | Existing Claude plugin and official Codex docs | Runtime mapping and invariants | This document |
| N2 | Add Codex packaging | N1 | Universal plugin manifest and thin entry skill | `.codex-plugin/plugin.json`, `skills/plumb-codex/SKILL.md` |
| N3 | Add native model routing | N1 | Profile and custom agents | `.codex/config.toml`, `.codex/agents/*.toml` |
| N4 | Adapt shared instructions | N1-N3 | Thin runtime adapter; Claude remains canonical | `SKILL.md`, `docs/openai-runtime.md` |
| N5 | Make installation repeatable | N2-N3 | Idempotent installer and guide | `bin/plumb-codex-install`, `README.md` |
| N6 | Verify the seam | N2-N5 | Static and behavioral checks | `scripts/check-harness.sh`, `scripts/selftest.sh` |

## Barrier

N1 is the barrier: model names, role names, and file ownership are decided once before the packaging,
agent, and documentation work diverge.

## Human gate

None blocks the first implementation. The user already decided the material point: Claude stays primary;
Codex is additive.

## Edges

`N1 -> (N2 || N3) -> N4 -> N5 -> N6`

## Edge contract

Each node hands the next node: changed paths, the claim each path establishes, commands that can verify
the claim, and unresolved compatibility gaps. No node may change a Claude execution primitive merely to
make the Codex adapter simpler.

## Verification

- Parse every TOML file with Python's `tomllib` and both plugin manifests with `json`.
- Validate the Codex plugin with the installed plugin validator.
- Run the existing harness check and self-test after adding Codex-specific assertions.
- Run Codex with `--strict-config` against the shipped profile without starting an interactive task.
- Treat Luna as a different execution tier, not a different model family; preserve the visible-skip rule
  when no genuinely different-family judge is configured.

## Completion conditions

All static checks pass; the installer is idempotent in a temporary Codex home; the shipped profile is
accepted by the installed Codex CLI; and the README gives both Claude and Codex installation paths.

## Source of truth

Claude files remain canonical for shared behavior. `docs/openai-runtime.md` is the sole translation layer
for Codex execution semantics, and `.codex/config.toml` is the sole model-placement map.
