# Review benchmark format

`bench.corpus` points at the private corpus directory. A corpus item is one buggy/fix PR pair:

```text
<corpus>/0001/pr.json
<corpus>/0001/truth.json
```

`pr.json` pins the review target and carries the person's grade:

```json
{"repo":"Haruki1090/plumb","number":1,"sha":"76970035242a357449fd710ca9c426dab3173d71","base_sha":"d276765b77185718335d98909d70e2f2f3821646","title":"docs(i18n): rewrite plumb in English for open-source release","fixed_by":4,"grade":"hard"}
```

`truth.json` is an array of fix-side hunk ranges. Extraction begins with unreviewed entries:

```json
[{"file":"playbooks/opening-a-pr.md","lines":[65,77],"source":"fix#4","reviewed":false,"note":""}]
```

A person deletes entries that are not the bug, sets every retained entry to `reviewed: true`, adds
one sentence to `note`, and grades the item `easy`, `medium`, or `hard`. Extraction never overwrites a
truth file containing a reviewed entry. An item with no reviewed entries is not scored.

A run mirrors corpus ids. `verdict.md` is the return shape in `report-template.md`; `session.json` is
the JSON output of `plumb-session-audit --session <uuid>`:

```text
<run>/0001/verdict.md
<run>/0001/session.json
```

Candidates receive only the repository, PR number, and pinned SHA from `pr.json`. They do not receive
`truth.json`, `fixed_by`, the fixing PR, or the evaluation playbook.
