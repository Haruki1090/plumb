# Failure modes

| Symptom | Cause | Where the skill prevents it |
|---|---|---|
| Built an issue that had already landed | Trusted the open state | Triage: search merged PRs first |
| Called an open PR landed that was not | Asserted ancestry without running it | PR queue: prove landed with a command |
| A lane grew past its item unseen | Unnamed work went in without a word | Report: name it in the row and the PR body |
| A second PR for work already in review | Did not search open PRs | Triage: open PRs |
| Two lanes rewrote one file | Fanned out before the inventory | Decompose: shared writes |
| The owner's approvals became the bottleneck | Too many live lanes | Decompose: 3-4 cap |
| Heavy checks side by side all stalled | Parallel machine-wide checks | Decompose: one at a time |
| Pressed enter on an approval unread | Relayed blind | Loop: blocked |
| The lane's answer vanished from the pane | Long output on the alternate screen | Brief: report file |
| The coordinator started writing lane code | Seat drift | Seats table |
| "Done" reported from the lane's self-report | No gate | Loop: separate review, final-commit checks |
| Progress lost after compaction | State held in memory | Intake: the ledger |
