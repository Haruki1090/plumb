# Harness audit and repair

## End state
Audit the Claude-first harness and additive Codex adapter, fix confirmed defects, and report
an evidence-based score with remaining limits. Preserve canonical runtime boundaries and user files.

## Graph or loop
Signals 1, 4, 5: portability and orchestration need different judgments; the audit must be
traceable; implementation needs a separate verification context. Execute serially except review.

## Nodes
| ID | Responsibility | Input | Output | Writes |
|---|---|---|---|---|
| A | Baseline and audit | README, runtime adapter, scripts, playbooks | confirmed defects and evidence | this spec |
| B | Repair portability and checks | A findings | implementation and regression checks | scripts, runtime docs |
| C | Repair graph completion contract | A findings | explicit required/optional outcomes | graph skill and references |
| D | Verify | B/C diff | commands, exit codes, regression results | temporary logs |
| E | Independent review | diff, this spec | confidence × blocking findings | none |
| F | Integrate and score | D/E evidence | audit report and remaining limits | docs/harness-audit-2026-09-05.md |

Edges: A -> B -> C -> D -> E -> F; E findings -> B/C -> D -> E when needed.
Shared resources: all source changes remain owned by the main thread. Reviewer is read-only.
Edge contract: finding ID, claim, file/line evidence, confidence, blocking, verification, unresolved.
AI ranks defects; executable checks decide pass/fail. No new general orchestration framework.

## Human gates
The user authorized audit and repairs. Changes to product direction, external publication or user
configuration require separate direction; none is needed for the local repairs.

## Verification
Use failure-oriented regression tests, full harness check and selftest, installed plugin validators,
strict Codex config validation, and doctor for the active runtime. Independent review checks the final
diff. Same-family review does not satisfy the different-family judge requirement.

## Termination and writeback
Required checks pass, confirmed blocking findings are resolved, and limitations are reported.
Review is bounded to two repair rounds before reporting any unresolved blocker. Budget exhaustion or
missing required evidence is incomplete, never success. Optional environment gaps are explicit skips.
Write final score and evidence to the audit report; this file remains the acceptance criteria.

## Visible checklist
- [x] Read the principle index and applied leaves.
- [x] Baseline and confirmed findings.
- [x] Repairs and regression verification.
- [x] Independent same-family review; display-total repair and graph clarification confirmed in follow-up.
- [x] Different-family judge: skip: configured command does not establish a verified different model family.
- [x] Final report: docs/harness-audit-2026-09-05.md.
