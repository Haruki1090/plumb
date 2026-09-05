# Measured efficiency and quality

## End state
Make runtime usage comparable without double-counting, and reject a candidate configuration that
reduces tokens by losing quality or failing to complete reviews. Preserve user control of adoption.
The owner requested token efficiency and higher task accuracy; this first batch supplies measurement
and decision gates, without changing model weights or claiming an unmeasured accuracy gain.

## Graph
Signals: specialized runtime and evaluation judgments, auditable control flow, independent verifier.
Execute small implementation nodes serially; independent review follows working regression checks.

| Node | Inputs | Outputs | Ownership |
|---|---|---|---|
| A | Current-session usage metadata, existing audit contract | Native runtime schema and fixtures | main, temporary probe |
| B | A plus audit scripts | Codex audit mode, accurate totals and bounded output | main, scripts and runtime docs |
| C | Existing scorer and outcome metrics | Explicit baseline/candidate acceptance gate | main, scorer and evaluation docs |
| D | B/C | Negative fixtures and whole-harness results | main, tests |
| E | Diff and this spec | Independent confidence/blocking findings | read-only judge |
| F | D/E | Remaining work and measured limitations | main, this spec |

Edges: A -> B -> C -> D -> E -> F. Required failures block completion. No parallel file writers.
Handoff: claim, file/revision evidence, verification command/result, unresolved items.

## Acceptance criteria
- Existing Claude audit interface and complete-record values stay compatible.
- Codex audit takes an explicitly scoped transcript location; never scan unrelated conversations.
- Repeated cumulative usage snapshots count once, cache-read tokens are not double-counted, counter
  resets and unknown formats fail explicitly. Missing categories stay unknown.
- Machine output distinguishes actual observations from metrics unavailable in the native format.
- Candidate gate requires named baseline and candidate, complete verdict coverage, and known cost.
- Default gate allows no precision, recall, or F1 regression; per-grade regressions also block.
  Token cost must improve. Thresholds can be explicit but do not mutate model configuration.
- Negative tests prove a cheap-but-worse candidate and an incomplete run cannot pass.
- Whole harness/selftest, plugin validator, and independent review pass.

## Human gates and boundaries
Implementation is authorized by the current request. No automatic model switch, external review
posting, production mutation, or new private-corpus collection. A real deployment choice needs the
owner and a representative evaluated corpus; fixtures prove the mechanism, not candidate quality.

## Remaining batches
1. Enforced tool-output budgets and scoped retrieval, evaluated on representative tasks.
   Also compare fresh-context role handoffs with inherited histories; include controller and all
   participant usage in the same cost unit so delegation cannot hide the spend.
2. Repeated blind evaluations with failure rate and latency, including difficult holdout cases.
3. Regression-driven skill improvements from recorded failures, with stable holdouts and rollback.
4. Live visibility and automatic controller integration after runtime hooks are established.

## Visible checklist
- [x] Read principles and existing runtime/evaluation contracts.
- [x] Native usage adapter and negative fixtures; current scoped session also parsed successfully.
- [x] Quality/cost acceptance gate and negative fixtures; exact ratios protect against rounding.
- [x] Harness/selftests, both manifest validators, strict-config with negative control, and doctor passed.
- [x] Independent judge: bounded follow-up found no remaining blocker in the reviewed fixes.
- [x] Different-family judge: explicitly skipped; available native reviewer is the same GPT family.
- [x] Record results and remaining limits.
- [ ] Complete native session coverage: latest real stream is rejected; see below.

## Observations and remaining work
The first native probe normalized 98 requests without duplicate snapshots or cache double-counting.
It found two tool results over the configured 40KB threshold. These are observations from this task,
not a before/after saving or a model-quality comparison. No default routing was changed.

Fifteen fixture tests exercise cache accounting, missing categories, counter resets, truncated prefixes,
duplicate exports, equal-quality lower cost, cheaper misses, per-grade regressions, missing results,
nonfinite costs, unpruned truth, and display-rounding boundaries. Synthetic passes prove gate behavior;
they do not prove production precision or recall. Representative repeated holdout evaluation is next.

Review added regressions for aggregate overflow, premature cost rounding, optional counter coverage,
and empty gate names. All four failed before repair and the complete fourteen-test suite then passed.
Native duplicate detection relies on session metadata or a filename fallback; renamed metadata-free
exports remain an operator responsibility. Unknown non-usage record types are ignored for forward
compatibility, not certified as an exhaustive accounting schema.

The final real-session probe exited 2: one last-usage snapshot reports `total_tokens=17210` while all
categories are zero. Earlier consistent snapshots parsed, but this whole session can no longer be
reported as measured. Preserve the rejection until runtime semantics are established; neither ignore
the event nor invent its category allocation. A captured-counter regression locks in this behavior.
Thus native parity is partial, and the combined real-session verification is not an all-green result.
