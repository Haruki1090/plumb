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
the JSON output of `plumb-session-audit --session <uuid>`:

```text
<run>/00001-00004/verdict.md
<run>/00001-00004/session.json
```

Candidates receive only the repository, PR number, and pinned SHA from `pr.json`. They do not receive
`truth.json`, `fixed_by`, the fixing PR, or the evaluation playbook.

Template section headings may use any Markdown heading level from `#` through `######`.
Every backticked `path:line` or `path:start-end` in a finding's `Where` cell is part of that one finding, and any overlapping location can match truth.
Outside template sections, a heading containing the whole-word severity `BLOCK` or `FIX` opens a finding (`NOTE` does so only with `--include-note`), whose locations come from its first `Where` row or paragraph.
If a summary row and a later free-form finding share at least one identical parsed location (file and exact start/end), they count as one finding and their location sets are merged.
A BLOCK or FIX row whose `Where` cell has no parseable `path:line` still counts as a false positive
with no location; it cannot match truth.
