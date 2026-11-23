# Uptake from pstack 0.15.46

Source: pstack 0.15.46 at `cursor/plugins` commit `7a58391` (2026-11-21), read in full against
plumb 0.30.0. `docs/scope.md` still describes the upstream of 2026-08-30; refreshing it is item 9.

Decision: the owner approved proceeding on 2026-11-23. Read here as "work through the list";
any single batch can be reverted, so each lands as its own merge commit on the integration branch.

## End state

The items below are in plumb, written in plumb's own words (NOTICE's claim that no text is taken
from pstack keeps holding), each wired to a part plumb already has, and each landed in a batch
whose check was not the implementer's own report.

## Acceptance criteria

- `bash scripts/selftest.sh` exits 0.
- `bash scripts/check-harness.sh` reports no `NG` line that is absent on `main` at `26ffd27`
  (the base already fails on 13 files holding e-mail-shaped strings; this work does not touch them).
- Every new skill has trigger-eval rows; every new `plumb-*` command has a test the self-test runs.
- The Codex sidecar checks in `AGENTS.md` pass for any batch that touches it.
- The counts in README and NOTICE match the files (harness rules 13 and 14).

## Branching and merge authority

Batches target `integrate/pstack-0.15.46`. A batch merges there, without squash, once a check
independent of its implementer covers its head. One ready pull request carries the branch to
`main`; that merge is the owner's. The owner's rule, stated 2026-11-23: an agent may merge once
the problem is confirmed solved, except into the production branch.

## Items

### A. First

1. A skill that writes the `[verify]` table and a feature-map skeleton for a repository that has
   none, and is done only when `plumb-verify plan` is runnable and one feature ran on base and head.
2. A maintenance pass for the feature map: read-only readers per feature, one live pass, results
   `clean` / `changed` / `blocked`, edits confined to the verification directory.
3. Three invariants in `agents/verifier.md`: drive only an instance whose health was checked;
   confirm evidence exists after cleanup; stop only what you started.
4. One worker-rules file every delegated agent reads first, put there by a hook, not by prose.
   Opt-in by a config key and scoped; the default changes no Agent call.
5. `plumb-lane` lists lanes whose time since the last recorded event exceeds what that kind of
   work usually takes, from recorded events and the ledger, never from a status line.
6. Principle explain-the-number, and seven questions for any measured number, applied in
   `perf-issue`, `hillclimb`, `evaluating-an-agent` and `plumb:retro`.
7. `plumb-decision-log audit`: evidence cells that name a SHA, pull request or file are resolved
   by machine; a run boundary row; an Attention section from the judge role in long-run reports.
8. A catch-up skill: what changed since the owner last spoke, and each waiting decision in a form
   a reply alone can settle (the decision, the pick, the evidence, the risk).
9. `plumb-upstream-diff` (upstream SHA recorded in NOTICE, files changed since listed) and a
   refreshed `docs/scope.md` covering skills, agents, the guide and automations.
10. The way in: a help skill that answers from `plumb-doctor` output without starting work, a
    short guide (what a request needs, recipes, pitfalls), and a Claude-side setup that writes
    role models and an effort budget to the config with a defaults version line.

### B. Next

11. Principle attack-the-premise (fires on the second failure at the same gate).
12. Blast radius as a claim with a rung: the one fact that makes the change safe, how far it was
    checked (said, pointed at, walked, ran, reproduced), and where a text search does not reach.
13. A per-repository ledger of review-bot patterns with a confidence that is earned.
14. A table of rule to enforcing mechanism, and optional expiry and approver on policy exceptions.
15. `plumb:retro` mines reverts, review comments and workaround comments for repeated failures.
16. A reflect skill: what from this session will still hold in six months, routed to the layer
    that owns it, with trigger-eval rows for a skill that should have fired.
17. A recall skill across sessions, each thread tagged with one fact-checked state.
18. A mechanical check of a pull request body, and numbered writing rules.
19. Competing implementations of one brief, judged by another family, with grafting.
20. A re-verification table for landing (what a rebase, a small fix and a wording change need).
21. One condition for blocking: a problem that can be shown at this head.
22. Loosening a gate needs the verifier's proof and the coordinator's countersign.
23. `plumb-pr-watch`: the state of a pull request as an exit code. Reopens a recorded decision.
24. A playbook for work no playbook fits.
25. A playbook for properties tests cannot reach.
26. An existing fix is verified, not rebuilt.
27. Blinding of an evaluation checked by machine.
28. Four conditions before a loop is trusted.
29. When work goes up to a stronger model.
30. Codex agent definitions generated from `agents/*.md`, with a staleness check.

### C. A few lines each

31. `investigation`: answer "why" from the record, and say what the record does not answer.
32. Restate a long or vague report in your own words before reading code; four sharpening questions.
33. Router: label claims measured, inferred or guessed; do not hand the owner a check you can run;
    give a real judgment when asked.
34. `writing-tests`: assert the error's type, pair every "does not happen" with a case where it does.
35. `fix-root-causes`: a guard is a fix only when the state is legitimate; propose the cheap
    always-on signal that would have shown the cause at first glance.
36. `build-the-lever`: applying a tool leaves a file in the diff; do the first item by hand and
    check the tool against it.
37. `fixing-a-bug`: the failing repro lands in a commit before the fix; no test beats a bad test.
38. `fan-out`: results carry the SHA and the method; a result without them is discarded and
    re-run once; a gap is not a pass.
39. `writing-a-plan`: per-pull-request unit / live / perf boxes; four parallelism questions
    answered even when the answer is `n/a: <reason>`.
40. How to clear a code-policy finding: encode the constraint, then delete the comment.
41. A harness change goes in its own pull request with its prompt-weight delta and trigger eval.
42. Review which skills stay model-invocable, by measured description weight. Reopens a recorded decision.

## Rejected

- Principles as skills: the 2026-08-29 incident still decides this.
- Slack-triggered triage and repair automations: tied to another product's automation service,
  and they send outside the machine.
- The TLA+ diagram toolchain, the TypeScript pull-request watcher, bun: runtimes plumb does not carry.
- Language-specific and product-specific skills, and personal-style skills.
- Trying the performance levers in a fixed cheapest-first order: plumb's families are sources of
  hypotheses, not a checklist.
- Always replacing the worker on a fix round, and cheap models for verification: both contradict
  recorded choices; compare by ledger before changing either.

## Open design points held for the main session

- Item 4 and the effort part of item 10: `agent-route.py` promises to change no other Agent call.
- Item 14: the exceptions file is schema 1 and in use; new columns are optional.
- Merge authority in `plumb:lead`: a contract key names the production branch; without the key,
  today's stop at a ready pull request stays. A merge needs a verdict covering the current head.
- Items 23 and 42 reopen decisions recorded in `docs/scope.md` and the router.
