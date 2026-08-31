# Picking up a session

**You hold the resume point. Read the previous session's traces. Do not redo them.**

"Pick this up", "resume this conversation", "carry on from this transcript", "from where X
stopped", or inheriting a pushed branch.

**A pickup is an inheritance.** The previous session already paid to read the code, run the
repro, and choose the design. Redoing it burns the context and throws away the check on that
bias as well. **Resist the pull to re-derive it. Read it.**

1. Find the previous session's traces: the transcript, the pushed branch, a `wip:` commit, a
   resume note. `docs/path-map.md` is the source of truth for where transcripts live.
   **Do not glob `~/.claude/projects/*/`** — that reads private conversations from other
   projects. Pin the slug down first, then open it. Hand analysis of a long transcript to the
   explorer role and keep only the shortened timeline in the main session
   (**principle-guard-the-context-window**).
2. Rebuild the operational state: the branch and the worktree, what already landed (`git log`,
   `git diff` against base), the open todos, the decisions that were made. **The previous
   session's traces are authoritative input.** Fight the pull to re-derive them.
3. Diff done against not done. Cross-check what shipped against the plan and name the resume
   point. **Do not re-run the previous session's repro. Do not redo finished work.**
   "Let me verify it from scratch, just in case" is the mark of not trusting an authoritative
   trace.
4. **Before you run anything, verify the claims you inherited against the real thing**
   (**principle-prove-it-works**). **A self-report from the previous session passing is not a
   proof.** This does not conflict with step 3's "do not redo the repro" — **what you do not
   redo is the process the previous session already showed; whether it holds right now is a
   separate question.** If running the same command once is the shortest path, run it. Only
   redoing the exploration from zero is forbidden.
5. Route the remainder to the matching playbook and pick the verdict: keep executing, return a
   finished recommendation, uphold or overturn the previous session's conclusion, or run a
   post-mortem on a failed run. **This playbook ends here.** What comes next belongs to the
   playbook you routed to, and you do not interrupt it.

**What you return:** where the previous session stopped, what you inherited and what you redid
(ideally nothing), the resume point, and the result.
