# Worked example: "open a PR" never reached the Fixes-PR rule

One real failure, taken through `plumb:failure-to-rule` end to end (2026-10-30). It is the populated
example the spec's acceptance criterion E asks for.

## The record

```html
<!-- plumb:failure v1 {"code": "C09", "kind": "harness", "category": null, "layer": "harness", "evidence": "evals/project-contract trials T2 and T4 on plumb 15d3df1^ (session transcripts kept by the owner)", "origin": "Haruki1090/plumb#27"} -->
```

## 1. What happened, and why it was not noticed

In the session trial T2 the owner said "Open a PR for this fix. It fixes #12." in a repository whose
contract requires a `Fixes-PR:` line. The session read `.plumb/project.toml` itself, then wrote
`Fixes #12` and no `Fixes-PR:` line. In T4, on a broken contract, it wrote the body anyway.

Not noticed because **no step told it to**: the rule lived only in `playbooks/opening-a-pr.md`,
reached through the root skill, and the root skill fires on "use plumb", not on "open a PR". No plumb
skill was called in either session. Selftest and review had passed: neither exercises routing from
an everyday request.

## 2. The same pattern elsewhere

Any rule that lives only in a playbook is reached only when the root skill fires. The others found:
none that a contract makes mandatory today. This is the first.

## 3. The layer

Not recognisable from the shape of a change, so not a CI rule; the repository's CI
(`plumb-check-fixes`) still catches a missing line, one review cycle late. The fix belongs to the
**harness**: a skill reached by the request itself, holding the rule in one hop.

## 4. The measurement, decided before the change

- Trigger cases `evals/open-pr/triggers.csv` (five asks, five near misses), first-call routing.
- The trials T2 and T4, rerun unchanged.

## 5. The change and the result

| Step | Change | Trigger recall | Near misses | T2 | T4 |
|---|---|---|---|---|---|
| Before | rule only in the playbook | — | — | `Fixes #12` | wrote a body |
| 9edfd48 | `plumb:open-pr` added | 0.20 | 5/5 | `Fixes-PR: #12`, check exit 0 | stopped on exit 2 |
| 15d3df1 | description: load it before running git | 1.00 | 5/5 | — | — |

The first attempt reached the skill, but only as the second call, after `git status`: the trials
passed and the trigger cases did not. The second change moved it to the first call.

## What it shows

A rule that a request must reach is measured by routing, not by the rule's own tests. Selftest
passed throughout; only the trial and the trigger cases saw the failure.
