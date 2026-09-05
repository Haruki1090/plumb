# Review benchmark format

`bench.corpus` points at the private corpus directory. A corpus item is one buggy/fix PR pair:

```text
<corpus>/00001-00004/pr.json
<corpus>/00001-00004/truth.json
```

`pr.json` pins the review target and carries the person's grade:

```json
{"repo":"Haruki1090/plumb","number":1,"sha":"76970035242a357449fd710ca9c426dab3173d71","buggy_sha":"76970035242a357449fd710ca9c426dab3173d71","base_sha":"d276765b77185718335d98909d70e2f2f3821646","title":"docs(i18n): rewrite plumb in English for open-source release","fixed_by":4,"grade":"hard"}
```

`truth.json` is an array of old-side hunk ranges. `lines` are line numbers in the tree at
`pr.json.sha`, which is the tree the candidate reviews; `fix_lines` locate the replacement text.
Extraction begins with unreviewed entries:

```json
[{"file":"playbooks/opening-a-pr.md","lines":[65,72],"fix_lines":[65,77],"source":"fix#4","reviewed":false,"note":""}]
```

A person deletes entries that are not the bug, sets every retained entry to `reviewed: true`, adds
one sentence to `note`, and grades the item `easy`, `medium`, or `hard`. Extraction keeps every
existing truth file; `--refresh <id>` rewrites one unreviewed item and refuses reviewed truth. An
item with no reviewed entries is not scored.

A run mirrors corpus ids. `verdict.md` is the return shape in `report-template.md`; `session.json` is
the JSON output of `plumb-session-audit --transcripts <the dedicated project directory> --all --json`,
because a review that spawns teammates is several sessions and auditing one session would omit them:

For another runtime, use its adapter's explicit audit mode and gather all participants into a dedicated
directory. Never combine overlapping exports of the same session. Missing cost categories must stay
unavailable; do not substitute zero to get a Pareto result.

```text
<run>/00001-00004/verdict.md
<run>/00001-00004/session.json
```

Candidates receive only the repository, PR number, and pinned SHA from `pr.json`. They do not receive
`truth.json`, `fixed_by`, the fixing PR, or the evaluation playbook.

For an acceptance decision, supply `--baseline <run-name> --candidate <run-name>` to the scorer.
The gate requires a fully pruned corpus, nonempty verdict coverage and complete token costs, no precision/recall/F1
regression overall or within any grade, and strict improvement in both mean and median tokens per
review. It uses exact count ratios for quality, so display rounding cannot conceal a regression.
Exit 0 means this measured comparison passes; exit 1 means the gate rejected it; exit 2 is invalid
input. The gate never changes routing configuration. A pass on fixtures or one small corpus does not
establish production quality, statistical significance, or dollar savings.

Template section headings may use any Markdown heading level from `#` through `######`.
Every backticked `path:line` or `path:start-end` in a finding's `Where` cell is part of that one finding, and any overlapping location can match truth.
In a findings table without a `Where` header, locations come from the first cell, left to right, that contains a backticked `path:line` or `path:start-end`; a row without one remains a locationless finding, while tables with `Where` keep their normal column behavior.
Outside template sections, a heading containing the whole-word severity `BLOCK` or `FIX` opens a finding (`NOTE` does so only with `--include-note`), whose locations come from its first `Where` row or paragraph.
If a summary row and a later free-form finding share at least one identical parsed location (file and exact start/end), they count as one finding and their location sets are merged.
A BLOCK or FIX row whose `Where` cell has no parseable `path:line` still counts as a false positive
with no location; it cannot match truth.
NOTE rows are recorded, never scored: the template defines NOTE as "not fixed this time", and a
defect the PR touches or widens is FIX under `plumb:pr-review` stage 5 even when it predates the
PR. `--include-note` exists to inspect what a run put there, not to compare runs. Measured on
2026-09-03: counting NOTE moved one run's precision from 0.222 to 0.140 because NOTE also carries
body-versus-diff mismatches and test-fixture remarks that are not defects.
