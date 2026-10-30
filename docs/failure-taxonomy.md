# Failure taxonomy and the failure record

A failure is agent work that had to be redone: a pull request a reviewer sent back, a later fix of
a landed change, a defect found in staging or production, or a trial that failed. Recording each one
the same way is what lets `plumb:retro` count them and `plumb:failure-to-rule` turn one into a
change that stops the next. The spec is §E of `.plumb/specs/project-contract-and-improvement-loop.md`.

## What counts

Record a failure when both hold:

- an agent wrote the change, or reported having checked it;
- that change caused rework: review sent it back, a later pull request fixed it, it was found after
  landing, or a trial of the harness failed.

Do not record: a requirement that changed after the work (the work matched the requirement of its
day), rework on a change a person wrote, or a defect of the verification setup itself that is not a
harness failure of plumb (record those as `kind: harness` only when the harness is what failed).

## The record

A failure record is a GitHub issue or pull request labelled `agent-failure` whose body (or a
comment) carries exactly one block:

```html
<!-- plumb:failure v1 {"code": "C08", "kind": "product", "category": "ui", "layer": "contract", "evidence": "https://github.com/o/r/pull/41#discussion_r1", "origin": "#37"} -->
```

| Field | Value |
|---|---|
| `code` | One code from the table below, or one of the contract's `[failure] extra_codes`. `null` while undecided |
| `kind` | `product` (the product misbehaves), `harness` (the way agents work or check failed), `stale_scenario` (a check describes a product that has since changed) |
| `category` | Optional. The ledger class of the affected change (the contract's `[ledger] classify`), so failures can be read against the cohort they came from |
| `layer` | Where the fix belongs: `harness` (plumb), `contract` (the repository: its CI rules, contract file, checks), `personal` (one person's settings or environment), or `null` while undecided |
| `evidence` | A pointer to what shows the failure: a review comment, a run directory, a pull request. A pointer, never pasted output, transcript text or credentials |
| `origin` | The change that introduced it: `#<n>`, `<owner>/<repo>#<n>`, or a commit SHA. `null` when unknown |

The record's id is the issue or pull request number. A `findings.jsonl` line written by
`plumb:verify` is a failure record too, with the finding's id; its fields are the same.

A record without a block, or with a malformed one, is still counted as a failure with every field
unknown, and is reported as such. Nothing is guessed from the title or the prose.

Collect with `plumb-ledger failures`. It reads the label over REST, page by page, and keeps every
record **created** in the period, including the ones updated after it.

## Codes

Each code is one failure **mechanism**, independent of any repository. A product's own codes go in
its contract's `[failure] extra_codes` (`{code, mechanism}`); they never redefine these.

| Code | Mechanism |
|---|---|
| C01 | A boundary, race or state transition was not handled (empty, first, last, concurrent, retried, out of order) |
| C02 | The requirement was misread: the work does what was not asked |
| C03 | A description disagrees with the behaviour: a pull request body, a design document, a comment or a report claims what the code does not do |
| C04 | An error was swallowed: a failure is turned into success, silence or a default |
| C05 | The work departs from its source of truth for design (a mock, a design document, a specification) without saying so |
| C06 | A fix was not carried to the other paths of the same pattern |
| C07 | Text people read (product copy, messages, documentation for users) is wrong or unclear |
| C08 | The tests do not detect the regression they exist for (or were weakened, skipped or removed) |
| C09 | A procedure or CI step was skipped, misread or misconfigured |
| C10 | Authorisation, secrets or another security boundary was weakened |
| C11 | Types, the build or the runtime environment break (it fails to compile, install, start or run where it must) |
| C12 | An existing mechanism was reimplemented instead of used |
| C13 | A data or schema migration is wrong, unsafe or irreversible without saying so |
| C14 | The work went outside the requested scope |
| C15 | Performance or resources regressed (time, memory, layout shift, workers, cost) |

## Layers, and which one owns a fix

Fix a failure in the layer that owns the invariant it broke. A higher row stops more and costs more
people; never write a lower one when a higher one can stop it.

| Layer | Stops it by | Reaches | Decided by |
|---|---|---|---|
| `contract`, as a CI rule | A deterministic check in the repository (a lint rule, a gate, a test; a ratchet that freezes today's count and blocks only increases) | Everyone who works in the repository | The repository's owners. A skill only proposes it |
| `harness` | A plumb skill, playbook, agent or tool, released with a version | Everyone who uses plumb | The plumb owner, by pull request |
| `contract`, as data | The contract file or a repository document the harness reads | Everyone who uses plumb in that repository | The repository's owners |
| `personal` | One person's config, setup script or environment | That person | That person |
