# Trials: the project contract and the `Fixes-PR:` line

The contract's behaviour lives in a command (`plumb-project`) and a playbook step
(`playbooks/opening-a-pr.md`), not in a skill, so `plumb-trigger-eval` alone cannot see it: it
stops at the first tool call that is not a Skill call. These trials run a real session on throwaway
repositories and judge what it produced with the deterministic checker.

## Rule for the prompt

**Say what you would say on a normal day. Never name the mechanism.** "Open a PR with
`plumb-project`" tests that the model can follow an instruction; it does not test that the harness
leads it there. The prompts below are the whole message.

## Setup

```bash
evals/project-contract/make-fixtures.sh <empty-dir> <your-github-login>
claude --plugin-dir <this plumb checkout>      # in each fixture repository, one session per trial
```

`--plugin-dir` loads the checkout under test; the marketplace install follows `main`.
The fixtures have no remote, so a session cannot open a real pull request. It should stop at the
body it would submit; ask for the body as a file if it does not write one.

## Trials

| # | Repository | Say | Pass when |
|---|---|---|---|
| T1 | `absent` | "Is plumb healthy?" | `plumb:doctor` runs and its `contract` block says `none` |
| T2 | `set` | "Open a PR for this fix. It fixes #12. Write the body to `body.md`." | The session read the contract, `body.md` has exactly one `Fixes-PR: #12`, and the check below exits 0 |
| T3 | `absent` | Same as T2 | No error about a contract; a `Fixes-PR:` line is optional |
| T4 | `invalid` | Same as T2 | The session stops before writing a final body and reports `plumb-project: invalid: …`; it does not treat the broken file as "no policy" |

Judge T2 and T3 with the checker, not by reading:

```bash
plumb-check-fixes --author <login> --required-authors "$(cd set && plumb-project rework.required_authors | paste -sd, -)" \
  --pr 13 --body-file set/body.md; echo "exit=$?"
```

T4 fails if `invalid/body.md` exists and the transcript shows no `invalid` outcome being reported.

## Doctor triggering

`triggers.csv` covers `plumb:doctor` (three asks it owns, three near misses). Run it in the `set`
fixture so `N2` has a contract to read:

```bash
plumb-trigger-eval --cases evals/project-contract/triggers.csv --skill plumb:doctor \
  --cwd <fixtures>/set --plugin-dir <this plumb checkout> --out <run>/triggers
```

The pass bar is zero false positives and zero false negatives (`playbooks/evaluating-an-agent.md`).

## Record

Write each run to `<run>/trials.md`: date, plumb revision, model, the four verdicts with the
checker's exit status, and anything the session did that no row covers. A failed trial is fixed in
the layer that owns it (a playbook line, the checker, or the doctor block), then the trial is rerun.
