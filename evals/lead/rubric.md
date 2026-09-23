# plumb:lead — model-graded rubric

`plumb-lead-grade` scores what a script can see. This rubric covers what it cannot: whether the
coordinator put good material in (briefs) and got good material out (reviews, reports). Grade it in
the judge role (`docs/role-map.md`), never in the session that ran the queue, and constrain the
output to `rubric.schema.json`.

Hand the grader only: the brief files, the lane reports, the review verdicts, the final report, and
the owner's golden triage file. Not the coordinator transcript — the grader judges artifacts, not
the story told about them.

## Inputs (garbage in)

| Check | 2 | 1 | 0 |
|---|---|---|---|
| `range` | Names the files or areas, and what is out of range | Area named, boundary vague | "Fix it" |
| `material` | The actual failing output, lines, repro or issue text, with the base SHA | A pointer ("see the issue") | Absent |
| `do_not_touch` | Names the surfaces other lanes own | Generic caution | Absent |
| `acceptance` | Observable conditions and exact check commands | Conditions without commands | Absent |
| `return_contract` | Report path, no push, no PR, reply with the path only | Partly | Absent |
| `no_history` | Only this lane's context | Some unrelated history | Coordinator transcript pasted |

## Outputs (garbage out)

| Check | 2 | 1 | 0 |
|---|---|---|---|
| `review_actionable` | Every blocking finding names an input or state and the wrong result | Some do | Style notes only |
| `report_evidence` | Each ready PR row carries the checked SHA and exit status | Some rows | Claims without evidence |
| `rulings_batched` | Open questions arrive once, each with options | Batched but open-ended | Scattered or missing |

`overall_pass` is true only when no check scores 0 and the mean is at least 1.5.
