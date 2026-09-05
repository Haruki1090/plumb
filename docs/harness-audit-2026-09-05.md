# Harness audit: 2026-09-05

Scope: the Claude-first source, additive Codex runtime, graph execution, owner decisions, and
measurement paths at base commit `b50b77b326fa7e9a179fdc0f999236a10705dcd6` plus this repair diff.
This is an engineering assessment, not a measured productivity or model-quality benchmark.

## Assessment

| Dimension | Maximum | Before | After | Grounds |
|---|---:|---:|---:|---|
| Graph correctness | 20 | 14 | 17 | Required outcomes now survive failure aggregation; verification receives implementation evidence |
| Owner alignment | 15 | 10 | 13 | Decisions work without an external artifact service; matching labels and pending gates remain |
| Runtime portability | 20 | 12 | 16 | Codex-only diagnostics no longer require a Claude installation; transcript support remains asymmetric |
| Verification | 20 | 15 | 17 | Regression checks cover runtime loading, unknown records, and percentile boundaries; separate review is retained |
| Outcome and cost measurement | 15 | 10 | 11 | Incorrect zero-usage success and percentile boundaries repaired; no measured routing comparison was run |
| Operational visibility | 10 | 7 | 7 | Pane identity, logs and exit status have a shared contract; no live cost dashboard is bundled |
| Total | 100 | 68 | 81 | Strong local harness; incomplete as an automatically enforced execution platform |

Scores express review judgment against the stated dimensions. They are not accuracy percentages.

## Repairs

1. `scripts/doctor.sh`: explicit runtime selection plus active-thread detection; Codex loading checks
   installed and enabled plugin identity from JSON. Disabled, malformed, and similarly named entries
   fail. Claude defaults remain available. The Codex-only fixture previously failed and now passes.
2. `skills/decision-brief/SKILL.md`: removed mandatory external design/publishing dependencies. Local
   HTML and runtime-supported questions are sufficient; silence never selects a branch.
3. `skills/graph/`: retain missing and failed node identities, block required dependencies, and send
   implementation artifacts into verification. A schema is no longer described as deterministic AI.
4. `scripts/session-audit.py`: nearest-rank percentiles replace the off-by-one boundary; no recognized
   usage exits 2 instead of emitting a misleading zero-cost success. Both regressions were observed
   before their fixes. Empty usage objects also fail and missing token categories stay unavailable
   instead of being silently filled with zero. This does not add a Codex transcript parser.
5. Shared operating instructions: establish relevant code and evidence before splitting work, preserve
   command failures through log capture, and compare efficiency only for equivalent completed work.
6. Documentation: remove external attribution and borrowed performance figures from the active
   efficiency guidance; distinguish diagnostic defaults from runtime enforcement and vendor prices.

## What the operating model actually provides

| Capability | Current implementation | Boundary |
|---|---|---|
| Workload-specific roles | Canonical agents plus native runtime role configuration | Defaults are configured, not proven optimal by a fresh benchmark |
| Comparable review evaluation | Corpus extraction, human pruning, precision/recall/F1, token-based Pareto comparison | One bundled example is a format fixture, not a representative evaluation suite |
| Reduced tool round trips | A batching playbook and bundled CLI scripts | No universal tool gateway; runtime tool discovery is external |
| Context control | An indexed rule corpus, bounded handoffs, three session flags | Thresholds diagnose; they do not enforce automatic compaction or truncate tool output |
| Grounded exploration | Source, entry-point, caller, and check discovery before graph nodes | No semantic repository index or cross-service knowledge graph |
| Recoverable execution | Specs, plans, history, node contracts and visible failure rules | Most state transitions are followed by the agent, not enforced by a controller |
| Continuous improvement | Repeatable script checks, evaluation and decision-log playbooks | No automatic collection of skill failures or evidence-backed routing changes |
| User visibility | Configurable pane driver, logs, exit status and progress | No combined live spend counter across runtimes |

## Remaining limits and next verification

- **Codex usage parity:** add a native transcript adapter only against documented or captured fixtures
  with deduplication and usage semantics established. Until then, usage must come from actual runtime
  evidence or be marked unavailable; never manufacture missing cache fields to make a run comparable.
- **Routing evidence:** use a human-pruned private corpus spanning difficulty levels, repeated runs,
  and recorded completion failures and elapsed time before changing model placement. Token volume is
  not dollar cost, and a single run is not a stable ranking.
- **Automatic enforcement:** an execution controller and live monitoring require a separately defined
  state schema and runtime hooks. The graph documents are currently a contract, not such a service.
- **Release coverage:** local installation fixtures and manifest validation do not prove a fresh
  GitHub marketplace download on another machine. No publish, push, or personal configuration change
  is part of this repair.
- **Judge:** the configured command does not establish a verified different model family. Keep a visible
  different-family skip; the native reviewer supplies an additional context, not that verdict.

## Verification record

Executed in a task-owned terminal pane, with pipeline failures preserved:

| Check | Result |
|---|---|
| `bash scripts/check-harness.sh` | exit 0 |
| `bash scripts/selftest.sh` | exit 0, including the new negative fixtures |
| Installed Codex plugin validator against this plugin root | exit 0 |
| `claude plugin validate .claude-plugin/plugin.json` | exit 0 |
| `codex exec --strict-config --profile plumb --skip-git-repo-check --ephemeral` in a temporary home | shipped config accepted; stopped at the deliberate empty prompt |
| Same strict-config invocation with an unknown field inserted into the temporary copy | rejected with `unknown configuration field` before prompt handling |
| `PLUMB_RUNTIME=codex bash scripts/doctor.sh` | exit 0; actual enabled plugin found |
| `git diff --check` | exit 0 |

Strict-config runs deliberately do not start a model task. Both CLI invocations exit 1, for different
observed reasons: empty prompt after successful config loading versus unknown config field. The
negative control prevents treating an unsupported CLI invocation as a validation success.

Session logs are temporary local evidence, not published transcripts.

Independent review returned one confirmed blocking finding and two suspected findings. The confirmed
finding exposed partial display totals despite unavailable machine-readable totals; both views now
use complete-coverage aggregation, with a regression fixture. The graph example now explicitly limits
parallel execution to independent lanes and requires predecessor checks between dependent phases.
The command-PATH concern was not accepted as a defect: the existing runtime adapter already requires
resolving every bundled command from the loaded plugin root; duplicating runtime commands into the
canonical skill would create another mapping to maintain. The reviewer is a separate native context;
the different-family judge remains a visible skip. A bounded follow-up review confirmed that the
display-total defect and the dependent-lane documentation concern are resolved.
