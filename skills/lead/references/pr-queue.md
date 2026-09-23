# The PR queue

Each PR is a lane whose seat is a reviewer, not an implementer.

- **Pin the SHA** per PR before reading (`plumb-pr-drift`), and record it on the ledger line.
- **The queue is the owner's**: PRs requesting the owner's review, plus the owner's own. Not every
  open PR in the repository.
- **Depth by risk.** A small, reversible PR gets one clean `plumb:pr-review` pass. A change to
  authentication, billing, prices or money arithmetic, a migration, or anything irreversible gets
  the full stages — however few files it touches. A PR others are stacked on counts as wider.
- **Already landed?** Compare the PR's change with the base: a PR whose content arrived through
  another PR is `landed`, even while it is open. Prove it with a command, not a reading: the head
  is an ancestor of the base (`git merge-base --is-ancestor <head> <base>`), or the diff of the
  PR's files between base and head is empty. Put that command and its result in the evidence
  column; without it the state is not `landed`.
- **Verdicts go to files**, one per PR. The coordinator reads the verdicts, not the transcripts.
- **Do not fix the PR under review.** Findings go back to its author. When the owner is the author
  and asked for fixes, open a separate implementer lane on that branch.
- **Posting is outward-facing.** Post review comments only if this request asked; otherwise the
  report carries the verdict table and the owner posts.

Ledger states for a PR item. At triage: `review-light` or `review-full` (the depth you chose),
`landed` (already merged). After review: `reviewed` (verdict path), `changes-requested` (blocking
findings), `stale` (head moved after the pinned SHA; re-pin before reporting).
